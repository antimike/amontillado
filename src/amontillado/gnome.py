"""GNOME's palette (libadwaita's `--blue-1` ... `--dark-5`) remapped onto a palette's colours.

docs/design.md, "Theme engine (v0.2)", "Template sources" (libadwaita-vars) and "Formats and
views". libadwaita 1.9 defines the GNOME palette as literal CSS variables, which apps name on
purpose (`var(--blue-3)`): seven hue families and two greys of five steps each, 1 the lightest,
the same in light and dark. Each hue family keeps GNOME's lightness ladder and takes its hue and
chroma from one or two of the palette's colours (the base16 colour and its base24 bright one);
the greys are the palette's ten ramp colours, lightest first.
"""

from __future__ import annotations

from amontillado.colour import hex_to_oklch, oklch_to_hex
from amontillado.palette import Variant

# Each hue family's source colours: the base16 colour, then its bright one where base24 has one.
FAMILIES = {
    "blue": ("base0D", "base16"),
    "green": ("base0B", "base14"),
    "yellow": ("base0A", "base13"),
    "orange": ("base09",),
    "red": ("base08", "base12"),
    "purple": ("base0E", "base17"),
    "brown": ("base0F",),
}
# OKLCH lightness of steps 1-5 per family (*initial*: libadwaita 1.9's own palette).
LADDERS = {
    "blue": (0.80, 0.70, 0.61, 0.56, 0.49),
    "green": (0.88, 0.82, 0.76, 0.72, 0.63),
    "yellow": (0.94, 0.91, 0.87, 0.84, 0.76),
    "orange": (0.85, 0.79, 0.72, 0.65, 0.57),
    "red": (0.68, 0.62, 0.58, 0.52, 0.47),
    "purple": (0.75, 0.64, 0.53, 0.49, 0.42),
    "brown": (0.76, 0.65, 0.56, 0.52, 0.42),
}
# The ramp, split into GNOME's light and dark greys by lightness.
RAMP_KEYS = (
    "base11",
    "base10",
    "base00",
    "base01",
    "base02",
    "base03",
    "base04",
    "base05",
    "base06",
    "base07",
)
STEPS = 5


def gnome_palette(variant: Variant) -> dict[str, str]:
    """GNOME's palette for `variant`, as {"blue-1": "#rrggbb", ...}, in libadwaita's order."""
    colours: dict[str, str] = {}
    for family, keys in FAMILIES.items():
        sources = [hex_to_oklch(variant.base24[key]) for key in keys]
        for step, lightness in enumerate(LADDERS[family], start=1):
            colours[f"{family}-{step}"] = oklch_to_hex(lightness, *_hue_at(sources, lightness))
    ramp = sorted(
        (variant.base24[key] for key in RAMP_KEYS),
        key=lambda colour: hex_to_oklch(colour)[0],
        reverse=True,
    )
    for offset, grey in ((0, "light"), (STEPS, "dark")):
        for step in range(STEPS):
            colours[f"{grey}-{step + 1}"] = ramp[offset + step]
    return colours


def _hue_at(sources: list[tuple[float, float, float]], lightness: float) -> tuple[float, float]:
    """Chroma and hue at `lightness`: the darker source's below it, the lighter one's above, and
    in between interpolated by lightness (hue the short way round)."""
    darker, lighter = sorted((sources[0], sources[-1]))
    span = lighter[0] - darker[0]
    t = 0.0 if span <= 0 else min(max((lightness - darker[0]) / span, 0.0), 1.0)
    chroma = darker[1] + t * (lighter[1] - darker[1])
    turn = (lighter[2] - darker[2] + 180.0) % 360.0 - 180.0
    return chroma, (darker[2] + t * turn) % 360.0
