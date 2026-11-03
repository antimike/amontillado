"""Named hues for a picture's palette: base08-base0F at fixed hues (`theme.hues: amontillado`).

docs/design.md, "Theme engine (v0.2)", "Generators" (Named hues) and decision 11. Each named
accent keeps a fixed nominal OKLCH hue, with no blending toward the picture: red stays red. Its
chroma follows the picture's accent (scaled, within bounds) and its lightness a target per
variant; the contrast check then adjusts as for any palette. The picture shows in the ramp, the
accent and the chroma.
"""

from __future__ import annotations

from amontillado.colour import hex_to_oklch, oklch_to_hex

# The sRGB colour whose OKLCH hue each named accent keeps: the ANSI primaries of
# amontillado.accents for colours 1-6, #ff8000 for orange. Brown is orange's hue, darker and
# duller.
PROMISED = {
    "base08": "#ff0000",
    "base09": "#ff8000",
    "base0A": "#ffff00",
    "base0B": "#00ff00",
    "base0C": "#00ffff",
    "base0D": "#0000ff",
    "base0E": "#ff00ff",
    "base0F": "#ff8000",
}
NOMINAL_HUES = {key: hex_to_oklch(colour)[2] for key, colour in PROMISED.items()}
# OKLCH lightness per variant (*initial*, calibrated 2026-11-03). Each passes 4.5:1 on base01
# before any adjusting. Yellow sits apart from green in lightness: their nominal hues are 33 deg
# apart, too close at one lightness ("Accent metrics"). Blue is the darkest dark-variant accent:
# terminals use it as a background under base05 (fast-syntax-highlighting's paired brackets,
# less's prompt), which needs 3:1.
LIGHTNESS = {
    "dark": {
        "base08": 0.72,
        "base09": 0.76,
        "base0A": 0.86,
        "base0B": 0.76,
        "base0C": 0.80,
        "base0D": 0.625,
        "base0E": 0.74,
        "base0F": 0.62,
    },
    "light": {
        "base08": 0.50,
        "base09": 0.53,
        "base0A": 0.53,
        "base0B": 0.45,
        "base0C": 0.50,
        "base0D": 0.52,
        "base0E": 0.48,
        "base0F": 0.42,
    },
}
# Chroma: the accent's times CHROMA_SCALE, within [CHROMA_MIN, CHROMA_MAX] (*initial*); brown at
# BROWN_CHROMA of that. The floor keeps a grey picture's accents on their hue (accents.MIN_CHROMA
# is 0.03); the ceiling keeps a vivid picture's from glaring. Out-of-gamut colours lose chroma.
CHROMA_SCALE = 1.0
CHROMA_MIN = 0.09
CHROMA_MAX = 0.16
BROWN_CHROMA = 0.6


def accent_chroma(accent: str) -> float:
    """The named accents' chroma for a picture whose accent is `accent`."""
    _, chroma, _ = hex_to_oklch(accent)
    return min(max(chroma * CHROMA_SCALE, CHROMA_MIN), CHROMA_MAX)


def named_hues(variant: str, accent: str) -> dict[str, str]:
    """base08-base0F for `variant` (dark or light) of a picture whose accent is `accent`."""
    chroma = accent_chroma(accent)
    return {
        key: oklch_to_hex(
            LIGHTNESS[variant][key], chroma * (BROWN_CHROMA if key == "base0F" else 1.0), hue
        )
        for key, hue in NOMINAL_HUES.items()
    }
