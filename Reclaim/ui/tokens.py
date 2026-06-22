"""Design tokens — the single source of the app's look. Values only, no logic.

This is the one file to edit to rebrand: every colour, spacing step, radius,
font and type size lives here, so theme.py can assemble a stylesheet from names
instead of scattering hex codes through the widgets. Each value carries a short
note on *why* it is what it is. Two palettes (dark/light) share the same keys so
switching themes is just swapping the dict.
"""

# --- Palettes -------------------------------------------------------------- #
# One dominant gold accent on a warm neutral base — deliberately not the generic
# blue-on-white dashboard. `on_accent` is the text/icon colour that sits ON the
# accent (must stay legible against it). Hover/press are the interaction states.
DARK = {
    "accent":      "#C9A24B",   # primary actions, selection, focus
    "accent_hover": "#D8B25C",  # lifts slightly on hover
    "accent_press": "#B68E3C",  # darkens on press for tactile feedback
    "on_accent":   "#1A1712",   # near-black warm — readable on gold
    "bg":          "#161512",   # window background (warm near-black)
    "surface":     "#1F1D19",   # cards / panels
    "surface_alt": "#262320",   # rows, inputs, hover fills
    "border":      "#332F29",   # hairline separators — subtle, not harsh
    "text":        "#EDE8DF",   # primary text (warm off-white)
    "muted":       "#9A9183",   # secondary text, captions
    "danger":      "#D9714E",   # destructive accents (warm red, fits palette)
    "good":        "#7FB069",   # success / freed-space confirmations
}
LIGHT = {
    "accent":      "#B5912F",
    "accent_hover": "#C49E36",
    "accent_press": "#856823",
    "on_accent":   "#FFFFFF",
    "bg":          "#F6F2EA",
    "surface":     "#FFFFFF",
    "surface_alt": "#EFEAE0",
    "border":      "#E2DACB",
    "text":        "#1C1A16",
    "muted":       "#6E6557",
    "danger":      "#B4502E",
    "good":        "#4F7A3A",
}
PALETTES = {"dark": DARK, "light": LIGHT}
DEFAULT_THEME = "dark"   # the refined dark palette is the showcase look

# --- Treemap tile colours -------------------------------------------------- #
# A categorical palette so the disk map reads like a modern data-viz dashboard
# (one hue per top-level tile) instead of a flat sheet of gold. Tiles cycle
# through these by index; the muted, desaturated tones keep white labels legible
# on every swatch and sit harmoniously on the warm dark/light bases. One shared
# list (not per-theme) so a tile keeps its colour when the theme is switched.
TREEMAP_COLORS = [
    "#C9A24B",   # gold (the brand accent leads)
    "#5E8BB0",   # slate blue
    "#7FB069",   # sage green
    "#D9714E",   # terracotta
    "#9B6FB0",   # muted violet
    "#4FA39A",   # teal
    "#D89A5B",   # amber
    "#B0586E",   # dusty rose
    "#6E8E5A",   # olive
    "#7A8CC4",   # periwinkle
]

# --- Spacing scale --------------------------------------------------------- #
# A 4px-based scale keeps every margin/padding on a consistent rhythm; referring
# to steps (SP_3) instead of raw pixels makes spacing decisions legible and
# uniform across screens.
SP_1, SP_2, SP_3, SP_4, SP_5, SP_6, SP_8 = 4, 8, 12, 16, 20, 24, 32

# --- Radii ----------------------------------------------------------------- #
# Rounded corners read as "soft/premium"; cards use a larger radius than inputs
# so the hierarchy is visible at a glance.
RADIUS_CARD = 14
RADIUS_CONTROL = 9
RADIUS_PILL = 999   # fully-rounded badges/toasts

# --- Type scale ------------------------------------------------------------ #
# A small modular scale. Display for the app title, body for everything, caption
# for secondary text — fewer sizes = calmer typography.
FS_DISPLAY = 22
FS_HEADING = 15
FS_BODY = 12
FS_CAPTION = 10
FS_MONO = 10        # paths/sizes read better monospaced

# --- Fonts ----------------------------------------------------------------- #
# Family *stacks*: Qt picks the first installed. We prefer a distinctive bundled
# face, then platform UI fonts, so the app looks intentional but never falls back
# to something unreadable. Arabic needs naskh faces with proper shaping.
FONT_LATIN = ['"Inter"', '"Segoe UI"', '"Helvetica Neue"', "Arial", "sans-serif"]
FONT_ARABIC = ['"Tajawal"', '"Cairo"', '"Noto Naskh Arabic"', '"Segoe UI"', "sans-serif"]
FONT_MONO = ['"JetBrains Mono"', '"Cascadia Code"', "Consolas", "monospace"]
# Optional .ttf files are loaded from this dir if present (see theme.load_fonts).
FONTS_DIR_NAME = "fonts"

# --- Misc geometry --------------------------------------------------------- #
# Default window size (width, height). Edit freely to trial different sizes.
WINDOW_SIZE = (960, 640)
SIDEBAR_WIDTH = 200         # narrow rail; each nav item is its own card (still fits "Claim old files")
# Height of the brand logo in the title bar. Sized to sit on the heading line of
# the brand block, a touch taller than the app-name text it replaces.
BRAND_LOGO_HEIGHT = 28
SCROLLBAR_WIDTH = 10        # slim custom scrollbars
# Density knobs: page padding and inter-widget spacing. Lower = more compact
# (less empty space). Change these to tighten/loosen the whole UI at once.
PAGE_MARGIN = SP_3
PAGE_SPACING = SP_2
