# UI assets

Optional drop-in brand assets, loaded by `widgets.py`. Like the bundled fonts,
everything here is **optional**: if a file is missing the UI falls back (text
brand, default window icon) rather than failing.

## Brand logo

Filenames are matched **best-first**, so either layout works:

- A single transparent **`logo.svg`** (preferred — crisp at any DPI) or
  **`logo.png`**, or
- the exported icon set: **`app_icon.ico`** (used for the window/taskbar icon)
  plus **`icon_master_512.png`** / `icon_256x256.png` / `icon_64x64.png` /
  `icon_32x32.png` (the largest is used for the title-bar logo, downscaled).

Use a **transparent background** so it reads on both themes (dark is warm
near-black `#161512`, light is warm off-white `#F6F2EA`).

Where it shows:

- **Title bar (top-left)** — in **both light and dark mode** (the text brand is
  the fallback only when no logo file is present). Scaled to
  `tokens.BRAND_LOGO_HEIGHT` px tall.
- **Window / taskbar icon** — set on the app in `gui.py`.

`build.py` bundles this folder into the frozen app automatically when it exists.
