# Contributing

Thanks for helping improve Reclaim. It's a Windows desktop tool with a strict
architecture by design, so some context up front makes contributing easier.

## Getting set up

```bash
git clone https://github.com/OmarSeteen/Reclaim.git
cd Reclaim
pip install -r requirements.txt
python -m Reclaim            # launch the app
python -m unittest discover -s tests -v
```

Python 3.10+ is required. PySide6 is the only runtime dependency.

## The one rule that matters: the safety invariant

**Deletion may only ever touch paths produced by `locations.py`, and user files
are never hard-deleted — they go to the Recycle Bin or are moved.**

If a change would let any other module compute its own paths to delete, it will
not be merged. The Disk Analyzer, Duplicates, and Old-files finders only ever
*propose*; a separate, confirmed step deletes. See `CLAUDE.md` for the full
architecture and the one-way dependency flow.

## Before you open a PR

The standing verification bar (also enforced by CI):

1. Every module compiles:
   `python -m compileall Reclaim`
2. Importing the package loads **no GUI toolkit**:
   `python -c "import sys, Reclaim; assert not ({'PySide6','tkinter'} & set(sys.modules))"`
3. All unit tests pass (the GUI smoke test runs with `QT_QPA_PLATFORM=offscreen`).

## Good first contributions

- **Translations** — add a language by extending `i18n.py` (the English text is
  the key, so partial translations fall back to English automatically).
- **New cleanup categories** — one resolver in `locations.py` + one record in
  `cleaners.py` + one test. See "How to add a cleanup category" in `CLAUDE.md`.
- **More app/dev caches** — the safe, regenerable kind.

## Reporting bugs

Open an issue with your Windows version, whether you ran as administrator, and
the relevant lines from the in-app activity log. Never paste full file paths you
consider private.
