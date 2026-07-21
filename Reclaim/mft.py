"""Optional NTFS Master File Table reader — the WizTree-style fast path.

Reading the MFT directly turns a whole-drive scan from "stat every file" into
"parse one table", which is dramatically faster on a full volume. It is an
*accelerator only*: it needs admin + an NTFS volume, so the analyzer always
falls back to the scandir walk (fsutils/analyzer) when any precondition or parse
fails. Nothing here deletes anything — it only reads and measures.

Layering: every function in this module is **pure byte parsing** except `scan`,
which pulls raw MFT bytes through a `reader` callable supplied by winapi (the one
module allowed to touch the volume via ctypes). That keeps the fiddly,
correctness-critical parsing unit-testable with synthetic records, and confines
the unverifiable raw-I/O to a thin, well-guarded seam.

References: the on-disk layout of NTFS FILE records, attributes, and mapping
pairs ("data runs") is the documented standard; offsets below follow it.
"""

import heapq
import os
from collections import defaultdict, namedtuple

from . import config, fsutils

# A parsed MFT record, reduced to what a size map needs.
Record = namedtuple("Record", "number in_use is_dir name parent size")

# NTFS constants.
ROOT_RECORD = 5  # the MFT record number of the volume root directory
FIRST_USER_RECORD = 16  # records 0..15 are reserved metafiles ($MFT, etc.)
ATTR_FILE_NAME = 0x30
ATTR_DATA = 0x80
ATTR_END = 0xFFFFFFFF


def _u(data, off, size):
    """Little-endian unsigned int of `size` bytes at `off`, or 0 if out of range."""
    if off + size > len(data) or off < 0:
        return 0
    return int.from_bytes(data[off : off + size], "little", signed=False)


def apply_fixup(record, sector_size=512):
    """Apply the NTFS update-sequence fixup to a raw FILE record.

    NTFS overwrites the last two bytes of every sector in a record with an
    "update sequence number" for torn-write detection, stashing the real bytes
    in an array at the record's start. We must restore those bytes before
    parsing or the tail of each sector is garbage. Returns the corrected bytes,
    or None if this isn't a valid FILE record.
    """
    if len(record) < 8 or record[0:4] != b"FILE":
        return None
    usa_off = _u(record, 4, 2)
    usa_cnt = _u(record, 6, 2)
    if usa_cnt == 0:
        return record
    fixed = bytearray(record)
    for i in range(1, usa_cnt):
        sector_end = i * sector_size - 2
        src = usa_off + i * 2
        if sector_end + 2 > len(fixed) or src + 2 > len(record):
            break
        fixed[sector_end : sector_end + 2] = record[src : src + 2]
    return bytes(fixed)


def _iter_attributes(rec):
    """Yield (type, non_resident, name_len, attr_offset, attr_len) for each
    attribute in a fixed-up record, stopping at the end marker. Bounds-checked so
    a malformed record can't run off the end."""
    off = _u(rec, 20, 2)  # offset to first attribute
    while off + 8 <= len(rec):
        atype = _u(rec, off, 4)
        if atype == ATTR_END:
            return
        alen = _u(rec, off + 4, 4)
        if alen < 16 or off + alen > len(rec):
            return
        yield atype, rec[off + 8], rec[off + 9], off, alen
        off += alen


def _ns_priority(ns):
    """Rank a $FILE_NAME namespace: prefer Win32 names over the short DOS alias.

    A file often has two names (long "Win32" + short "DOS 8.3"); we want the
    readable one. POSIX(0)=2, Win32(1)=3, DOS(2)=0, Win32+DOS(3)=3.
    """
    return {1: 3, 3: 3, 0: 2, 2: 0}.get(ns, 1)


def parse_record(record, number, sector_size=512):
    """Parse one raw MFT record into a Record, or None if it isn't a live file.

    Picks the Win32 name when several exist, reads the file's logical size from
    the unnamed $DATA attribute (resident length, or non-resident "real size"),
    and the parent directory's record number from $FILE_NAME. Directories carry
    no $DATA, so their size is 0 here and is rolled up from children later.
    """
    rec = apply_fixup(record, sector_size)
    if rec is None:
        return None
    flags = _u(rec, 22, 2)
    in_use = bool(flags & 0x01)
    is_dir = bool(flags & 0x02)

    name = None
    name_ns = -1
    parent = None
    size = 0
    for atype, non_resident, name_len, off, _alen in _iter_attributes(rec):
        if atype == ATTR_FILE_NAME:
            content_off = _u(rec, off + 20, 2)
            c = off + content_off
            par = _u(rec, c, 6)  # low 48 bits = parent record no.
            fn_chars = rec[c + 64] if c + 64 < len(rec) else 0
            ns = rec[c + 65] if c + 65 < len(rec) else 0
            nm = rec[c + 66 : c + 66 + fn_chars * 2].decode("utf-16-le", "replace")
            if name is None or _ns_priority(ns) > _ns_priority(name_ns):
                name, name_ns, parent = nm, ns, par
        elif atype == ATTR_DATA and name_len == 0:
            # Only the unnamed stream is "the file"; named streams are ADS and
            # aren't counted by a normal directory walk, so we ignore them.
            if non_resident:
                size = _u(rec, off + 48, 8)  # real (logical) size
            else:
                size = _u(rec, off + 16, 4)  # resident content length
    return Record(number, in_use, is_dir, name, parent, size)


def parse_data_runs(data):
    """Decode an NTFS data-run (mapping-pairs) list into [(clusters, lcn), ...].

    Each run is a header byte (low nibble = #bytes of length, high nibble =
    #bytes of a *signed* LCN delta), then those fields. A zero offset means a
    sparse run (hole), returned as lcn=None. Stops at the terminating 0 byte or
    on any truncation, so a partial buffer can't over-read.
    """
    runs = []
    i = 0
    lcn = 0
    while i < len(data):
        header = data[i]
        if header == 0:
            break
        len_bytes = header & 0x0F
        off_bytes = (header >> 4) & 0x0F
        i += 1
        if len_bytes == 0 or i + len_bytes + off_bytes > len(data):
            break
        run_len = int.from_bytes(data[i : i + len_bytes], "little", signed=False)
        i += len_bytes
        if off_bytes == 0:
            runs.append((run_len, None))  # sparse
            continue
        lcn += int.from_bytes(data[i : i + off_bytes], "little", signed=True)
        i += off_bytes
        runs.append((run_len, lcn))
    return runs


def mft_data_runs(record0, sector_size=512):
    """Return the data runs of $MFT's own unnamed $DATA, from MFT record 0.

    These extents are how we find every other MFT record on disk. Returns [] if
    record 0 doesn't parse as expected (caller then aborts to the fallback).
    """
    rec = apply_fixup(record0, sector_size)
    if rec is None:
        return []
    for atype, non_resident, name_len, off, _alen in _iter_attributes(rec):
        if atype == ATTR_DATA and name_len == 0 and non_resident:
            runs_off = _u(rec, off + 32, 2)
            return parse_data_runs(rec[off + runs_off : off + _alen])
    return []


def scan(
    reader,
    bytes_per_cluster,
    record_size,
    mft_start_lcn,
    on_progress=None,
    should_cancel=None,
    sector_size=512,
):
    """Read and parse every MFT record, returning a list of Record.

    `reader(byte_offset, length) -> bytes` is supplied by winapi and reads raw
    volume bytes (cluster-aligned, which we always request). We read MFT record 0
    to learn the table's own extents, then stream those extents in record-aligned
    chunks. Record numbers are sequential in MFT order, which is exactly the
    parent-reference numbering, so we just count. Cancellable; progress by count.

    `sector_size` is the volume's bytes-per-sector and drives the update-sequence
    fixup stride; it's 512 on classic disks but 4096 on 4Kn-native volumes, where
    a hardcoded 512 would restore the wrong bytes and corrupt every record.
    """
    record0 = reader(mft_start_lcn * bytes_per_cluster, record_size)
    runs = mft_data_runs(record0, sector_size)
    if not runs:
        return []

    # Read in chunks that are a whole number of records to keep slicing aligned.
    chunk = max(record_size, (4 * 1024 * 1024 // record_size) * record_size)
    records = []
    number = 0
    for clusters, lcn in runs:
        if lcn is None:
            # Sparse stretch of the MFT: those record slots still advance the
            # numbering even though there's nothing on disk to read.
            number += (clusters * bytes_per_cluster) // record_size
            continue
        extent_bytes = clusters * bytes_per_cluster
        base = lcn * bytes_per_cluster
        read = 0
        while read < extent_bytes:
            if should_cancel and should_cancel():
                raise fsutils.Cancelled()
            n = min(chunk, extent_bytes - read)
            data = reader(base + read, n)
            if not data:
                break
            for off in range(0, len(data) - record_size + 1, record_size):
                rec = parse_record(data[off : off + record_size], number, sector_size)
                number += 1
                if rec is not None and rec.in_use and rec.name:
                    records.append(rec)
                if on_progress and (number & 0x3FFF) == 0:
                    on_progress(len(records))
            read += len(data)
    return records


def assemble(records, drive_root):
    """Turn a flat list of Records into a ScanResult-shaped tuple, purely.

    Builds the directory tree from parent references, resolves each directory's
    full path under `drive_root` (the volume root is always record 5), rolls file
    sizes up into their ancestors, and collects the largest files and per-type
    totals — the same outputs as analyzer.build_size_map, so the GUI can't tell
    which engine produced them. Reserved metafiles (records < 16, e.g. $MFT) are
    skipped so totals match what a normal directory walk would see. Orphaned or
    cyclic records (parent missing/looping) are dropped rather than trusted.
    """
    info = {
        r.number: r for r in records if r.in_use and r.name and r.parent is not None
    }

    path_cache = {ROOT_RECORD: drive_root}

    def resolve(number):
        # Iteratively climb to the root, then fill the path of each step.
        chain = []
        cur = number
        while cur not in path_cache:
            rec = info.get(cur)
            if rec is None or rec.parent is None or cur in chain:
                return None  # orphan or cycle
            chain.append(cur)
            cur = rec.parent
        path = path_cache[cur]
        for n in reversed(chain):
            path = os.path.join(path, info[n].name)
            path_cache[n] = path
        return path

    dir_children = defaultdict(list)
    for rec in info.values():
        if rec.is_dir and rec.number != ROOT_RECORD:
            dir_children[rec.parent].append(rec.number)

    own = defaultdict(int)  # dir record -> bytes of files directly inside
    ext_sizes = {}
    heap = []
    total = 0
    scanned = 0
    for rec in info.values():
        if rec.is_dir or rec.number < FIRST_USER_RECORD:
            continue
        own[rec.parent] += rec.size
        total += rec.size
        scanned += 1
        ext = os.path.splitext(rec.name)[1].lower() or "(no ext)"
        ext_sizes[ext] = ext_sizes.get(ext, 0) + rec.size
        if len(heap) < config.FILE_HEAP_SIZE:
            heapq.heappush(heap, (rec.size, rec.number))
        elif rec.size > heap[0][0]:
            heapq.heapreplace(heap, (rec.size, rec.number))

    # Post-order roll-up of directory sizes over the directory tree.
    size_of = {}
    stack = [(ROOT_RECORD, False)]
    while stack:
        node, processed = stack.pop()
        if processed:
            s = own.get(node, 0)
            for child in dir_children.get(node, ()):
                s += size_of.get(child, 0)
            size_of[node] = s
        else:
            stack.append((node, True))
            for child in dir_children.get(node, ()):
                stack.append((child, False))

    dir_sizes = {}
    for number, size in size_of.items():
        path = drive_root if number == ROOT_RECORD else resolve(number)
        if path is not None:
            dir_sizes[path] = size

    top_files = []
    for size, number in heap:
        path = resolve(number)
        if path is not None:
            top_files.append((size, path))
    top_files.sort(reverse=True)
    top_files = top_files[: config.TOP_FILES_SHOWN]
    top_types = sorted(ext_sizes.items(), key=lambda kv: kv[1], reverse=True)[
        : config.TOP_TYPES_SHOWN
    ]

    return dir_sizes, top_files, top_types, dir_sizes.get(drive_root, total), scanned
