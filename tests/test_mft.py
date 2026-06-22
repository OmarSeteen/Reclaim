"""Tests for the pure NTFS MFT parsing/assembly. No volume access, no admin.

Records are synthesised in-memory so the byte-level parsing (fixups, attributes,
data runs) and the tree assembly are verified deterministically — the only part
not exercised here is the raw volume read in winapi, which needs an elevated NTFS
handle.
"""

import struct
import unittest

from Reclaim import mft

SECTOR = 512
RECORD_SIZE = 1024
USN = b"\x7f\x7f"


def build_record(number, name, parent, size=0, is_dir=False, non_resident=False):
    """Construct one valid 1024-byte FILE record (with a no-op fixup applied)."""
    rec = bytearray(RECORD_SIZE)
    rec[0:4] = b"FILE"
    usa_off = 48
    rec[4:6] = struct.pack("<H", usa_off)
    rec[6:8] = struct.pack("<H", 3)            # 1 USN + 2 sectors
    rec[20:22] = struct.pack("<H", 56)         # first attribute offset
    rec[22:24] = struct.pack("<H", 0x01 | (0x02 if is_dir else 0))
    rec[28:32] = struct.pack("<I", RECORD_SIZE)
    # Update-sequence array: USN, then the real bytes that belong at sector ends.
    rec[48:50] = USN
    rec[50:52] = b"\x00\x00"
    rec[52:54] = b"\x00\x00"
    rec[510:512] = USN                          # on-disk: sector ends hold USN
    rec[1022:1024] = USN

    off = 56
    # --- $FILE_NAME (0x30), resident ---
    nm = name.encode("utf-16-le")
    content = (
        struct.pack("<Q", parent)               # parent reference (low 48 bits)
        + b"\x00" * 32                           # 4 timestamps
        + struct.pack("<Q", 0)                    # alloc size
        + struct.pack("<Q", 0)                    # real size
        + b"\x00" * 4                             # flags
        + b"\x00" * 4                             # reparse
        + bytes([len(name)])                      # filename length (chars)
        + bytes([1])                              # namespace: Win32
        + nm
    )
    attr_len = (24 + len(content) + 7) // 8 * 8
    struct.pack_into("<I", rec, off, 0x30)
    struct.pack_into("<I", rec, off + 4, attr_len)
    rec[off + 8] = 0                             # resident
    rec[off + 9] = 0                             # unnamed
    struct.pack_into("<I", rec, off + 16, len(content))
    struct.pack_into("<H", rec, off + 20, 24)    # content offset
    rec[off + 24:off + 24 + len(content)] = content
    off += attr_len

    # --- $DATA (0x80) for files ---
    if not is_dir:
        if non_resident:
            data_len = 64
            struct.pack_into("<I", rec, off, 0x80)
            struct.pack_into("<I", rec, off + 4, data_len)
            rec[off + 8] = 1                     # non-resident
            rec[off + 9] = 0                     # unnamed
            struct.pack_into("<Q", rec, off + 48, size)   # real size
            off += data_len
        else:
            # We write only the resident length field, not `size` bytes of
            # content — the parser reads that field, and a real resident file is
            # tiny anyway. This keeps the synthetic record within 1024 bytes for
            # any test size.
            data_len = 24
            struct.pack_into("<I", rec, off, 0x80)
            struct.pack_into("<I", rec, off + 4, data_len)
            rec[off + 8] = 0
            rec[off + 9] = 0
            struct.pack_into("<I", rec, off + 16, size)   # resident length
            struct.pack_into("<H", rec, off + 20, 24)     # content offset
            off += data_len

    struct.pack_into("<I", rec, off, 0xFFFFFFFF)  # end marker
    struct.pack_into("<I", rec, 24, off + 8)      # used size
    return bytes(rec)


class TestParsing(unittest.TestCase):
    def test_apply_fixup_restores_sector_ends(self):
        rec = build_record(20, "x.txt", 5, size=10)
        fixed = mft.apply_fixup(rec)
        self.assertEqual(fixed[510:512], b"\x00\x00")
        self.assertEqual(fixed[1022:1024], b"\x00\x00")
        self.assertIsNone(mft.apply_fixup(b"NOPE" + b"\x00" * 100))

    def test_parse_resident_file(self):
        r = mft.parse_record(build_record(20, "report.pdf", 16, size=1234), 20)
        self.assertEqual((r.name, r.parent, r.size, r.is_dir, r.in_use),
                         ("report.pdf", 16, 1234, False, True))

    def test_parse_nonresident_file(self):
        r = mft.parse_record(
            build_record(21, "movie.mkv", 16, size=9_000_000_000, non_resident=True), 21)
        self.assertEqual(r.size, 9_000_000_000)   # 64-bit real size
        self.assertEqual(r.name, "movie.mkv")

    def test_parse_directory_has_no_size(self):
        r = mft.parse_record(build_record(16, "photos", 5, is_dir=True), 16)
        self.assertTrue(r.is_dir)
        self.assertEqual(r.size, 0)

    def test_parse_data_runs_positive_and_negative_deltas(self):
        # run1: len 0x18 @ +0x5634 ; run2: len 5 @ -1 ; then terminator
        data = bytes([0x21, 0x18, 0x34, 0x56, 0x11, 0x05, 0xFF, 0x00])
        self.assertEqual(mft.parse_data_runs(data), [(0x18, 0x5634), (5, 0x5634 - 1)])

    def test_parse_data_runs_handles_sparse(self):
        data = bytes([0x01, 0x07, 0x00])         # length 7, no offset = sparse hole
        self.assertEqual(mft.parse_data_runs(data), [(7, None)])


class TestAssemble(unittest.TestCase):
    def _tree(self):
        return [
            mft.parse_record(build_record(16, "photos", 5, is_dir=True), 16),
            mft.parse_record(build_record(17, "a.jpg", 16, size=1000), 17),
            mft.parse_record(build_record(18, "b.jpg", 16, size=2000), 18),
            mft.parse_record(build_record(19, "root.txt", 5, size=50), 19),
            mft.parse_record(build_record(20, "empty", 5, is_dir=True), 20),
        ]

    def test_sizes_paths_and_rollup(self):
        dir_sizes, top_files, top_types, total, scanned = mft.assemble(
            self._tree(), "C:\\")
        self.assertEqual(total, 3050)
        self.assertEqual(scanned, 3)
        self.assertEqual(dir_sizes["C:\\"], 3050)
        self.assertEqual(dir_sizes["C:\\photos"], 3000)
        self.assertEqual(dir_sizes["C:\\empty"], 0)
        self.assertEqual(top_files[0], (2000, "C:\\photos\\b.jpg"))
        self.assertEqual(dict(top_types)[".jpg"], 3000)
        self.assertEqual(dict(top_types)[".txt"], 50)

    def test_orphan_is_dropped(self):
        # A file whose parent record doesn't exist must not crash, and (since it
        # can't be placed under the root) must not appear in the tree total.
        recs = [mft.parse_record(build_record(30, "lost.bin", 999, size=5), 30)]
        dir_sizes, top_files, _t, total, _scanned = mft.assemble(recs, "C:\\")
        self.assertEqual(total, 0)        # root rollup excludes the unplaceable file
        self.assertEqual(top_files, [])   # and it resolves to no path

    def test_metafiles_excluded(self):
        # A reserved record (< 16) such as $MFT must not inflate the totals.
        recs = self._tree() + [
            mft.parse_record(build_record(0, "$MFT", 5, size=10_000_000), 0)]
        _d, _f, _t, total, scanned = mft.assemble(recs, "C:\\")
        self.assertEqual(total, 3050)
        self.assertEqual(scanned, 3)


if __name__ == "__main__":
    unittest.main()
