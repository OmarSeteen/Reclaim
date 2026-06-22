"""Regenerate Reclaim/ui/assets/app_icon.ico from the high-res master.

Why this exists: a Windows .ico must embed several sizes — the taskbar/alt-tab
pick ~24-48px, the desktop/large-icons view picks 256. The original app_icon.ico
shipped a single 16x16 image, so every surface upscaled it into a blurry blob.
This rebuilds a multi-resolution icon (PNG-compressed entries, the Vista+ format)
by smoothly downscaling icon_master_512.png with Qt — no third-party deps, since
PySide6 is already the UI toolkit.

Run:  python tools/make_app_icon.py     (needs PySide6; no GUI window is shown)
"""

import os
import struct
import sys

# Headless: we only touch QImage, so the offscreen platform avoids needing a
# display and keeps this runnable in CI / over SSH.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, Qt                      # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage           # noqa: E402

# Standard Windows icon sizes. 16/24/32/48 cover the taskbar, alt-tab and small
# list views; 64/128/256 cover the larger "big icons" / file-explorer views.
SIZES = (16, 24, 32, 48, 64, 128, 256)

_ASSETS = os.path.join(os.path.dirname(__file__), "..",
                       "Reclaim", "ui", "assets")
MASTER = os.path.join(_ASSETS, "icon_master_512.png")
OUT = os.path.join(_ASSETS, "app_icon.ico")


def _png_bytes(image, size):
    """Smoothly scale `image` to size×size and return its PNG-encoded bytes."""
    scaled = image.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    buf = QBuffer()                 # owns its own backing store (no dangling ref)
    buf.open(QBuffer.WriteOnly)
    scaled.save(buf, "PNG")
    return bytes(buf.data())


def build_ico(master_path, out_path, sizes=SIZES):
    src = QImage(master_path)
    if src.isNull():
        raise SystemExit(f"Could not load master image: {master_path}")

    pngs = [(s, _png_bytes(src, s)) for s in sizes]

    # ICO layout: 6-byte header, then one 16-byte dir entry per image, then the
    # image payloads. Offsets are measured from the start of the file.
    header = struct.pack("<HHH", 0, 1, len(pngs))    # reserved, type=1 (icon), count
    offset = len(header) + 16 * len(pngs)
    entries, payloads = [], []
    for size, data in pngs:
        # Width/height of 256 are stored as 0 in the byte-wide fields.
        dim = 0 if size >= 256 else size
        entries.append(struct.pack(
            "<BBBBHHII",
            dim, dim,         # width, height
            0,                # palette count (0 = no palette)
            0,                # reserved
            1,                # color planes
            32,               # bits per pixel
            len(data),        # bytes of image data
            offset,           # offset to image data
        ))
        payloads.append(data)
        offset += len(data)

    with open(out_path, "wb") as f:
        f.write(header)
        for e in entries:
            f.write(e)
        for p in payloads:
            f.write(p)


def main():
    # QImage needs a Q*Application instance to exist before it's used.
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    build_ico(MASTER, OUT)
    print("Wrote", os.path.normpath(OUT), "with sizes", SIZES)
    # PySide6 can crash (access violation) running Qt's destructors at normal
    # interpreter shutdown on Windows. The icon is already written by here, so
    # exit hard to skip that teardown and return a clean status code.
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
