"""Classes such as dark, muted or busy, computed from the raw metrics at query time.

Nothing here is stored: retuning a threshold needs no recomputation. The rules are in
docs/design.md, "Classes"; the thresholds are *initial* until calibrated.
"""

from __future__ import annotations

from collections.abc import Callable

from amontillado.metrics import HUE_NAMES, Metrics

DARK_MAX = 0.35
LIGHT_MIN = 0.65
MUTED_MAX = 0.03
SATURATED_MIN = 0.08
SPARSE_MAX = 0.04
BUSY_MIN = 0.12
HUE_SHARE_MIN = 0.40
MONOCHROME_MAX = 0.30
MULTI_HUE_MIN = 0.60
WARM_MIN = 0.3
COOL_MAX = -0.3


def _is_muted(m: Metrics) -> bool:
    return m.chroma < MUTED_MAX


CLASSES: dict[str, Callable[[Metrics], bool]] = {
    "dark": lambda m: m.lightness < DARK_MAX,
    "light": lambda m: m.lightness > LIGHT_MIN,
    "muted": _is_muted,
    "saturated": lambda m: m.chroma > SATURATED_MIN,
    "sparse": lambda m: m.busy < SPARSE_MAX,
    "busy": lambda m: m.busy > BUSY_MIN,
    # A greyscale image has no hue at all: it is muted, never monochrome.
    "monochrome": lambda m: m.hue_name is not None and m.hue_spread < MONOCHROME_MAX,
    "multi-hue": lambda m: m.hue_spread > MULTI_HUE_MIN,
    "warm": lambda m: m.warmth > WARM_MIN,
    "cool": lambda m: m.warmth < COOL_MAX,
}


def has_hue(m: Metrics, name: str) -> bool:
    """Whether `name` (one of HUE_NAMES) is the image's dominant hue, as `--hue NAME` means."""
    return m.hue_name == name and m.hue_share >= HUE_SHARE_MIN and not _is_muted(m)


def classify(m: Metrics) -> list[str]:
    """The classes an image belongs to, in CLASSES order, then its hue name if it has one."""
    names = [name for name, rule in CLASSES.items() if rule(m)]
    names.extend(hue for hue in HUE_NAMES if has_hue(m, hue))
    return names
