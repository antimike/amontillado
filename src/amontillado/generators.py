"""Generator adapters: a picture in, per variant the colours a palette is completed from.

docs/design.md, "Theme engine (v0.2)", "Generators". An adapter runs an external program and
returns, per variant, the neutral ramp (`base00`-`base07`), the accents it knows (`accent`,
`secondary`) and its own sixteen colours (used only under `theme.hues: generator`). Generators
are detected at run time; the commands that need one say so when none is installed.

matugen (>= 4.0) gives both variants in one run: its Material `primary` and `secondary` are the
accents, its `neutral` tonal palette the ramp. Its `base16` block is pywal-style clustering, not
named hues: `picture_palette` uses it only under `hues: generator`.

wallust (>= 3.0, checked on 3.5.1) runs twice: `-p dark16` clusters the picture (the ramp's hue
from its background, the accent from its most chromatic colour), and `-k -c lchansi -p
ansidark16` puts each hue in its ANSI slot (its own colours, for `hues: generator`). wallust has
no light ANSI palette, so both variants take the second run's hues.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from logging import getLogger
from pathlib import Path

from amontillado.colour import HEX_PATTERN, hex_to_oklch, oklch_to_hex
from amontillado.config import GENERATORS
from amontillado.hues import named_hues
from amontillado.palette import BASE16_KEYS, VARIANTS, Palette, complete_variant

logger = getLogger(__name__)

MATUGEN_MINIMUM = (4, 0)
# The neutral tones that make the ramp base00-base07, per variant (*initial*, calibrated
# 2026-11-03): a near-black background (Material's surface is tone 6) to a near-white
# foreground, and the reverse. The text is that far from the background so that it stays
# legible on an accent used as a background (base05 on base0D at 3:1) while the accent still
# reaches 4.5:1 on base01.
RAMP_TONES = {
    "dark": (5, 10, 20, 50, 70, 95, 98, 100),
    "light": (98, 95, 90, 50, 40, 10, 5, 0),
}
WALLUST_MINIMUM = (3, 0)
# The wallust accent's lightness per variant: matugen's primary tones (Material's), so that a
# wallust palette's accent sits where a matugen one does.
ACCENT_TONES = {"dark": 80, "light": 40}
# The wallust ramp's chroma at most: about matugen's neutral palette's (*initial*).
NEUTRAL_CHROMA = 0.006
# wallust's ANSI colours 1-6 onto base16 (base16-shell's table in reverse). ANSI has no orange or
# brown: base09 and base0F come from the named hues.
ANSI_BASE16 = {1: "base08", 2: "base0B", 3: "base0A", 4: "base0D", 5: "base0E", 6: "base0C"}
_SCHEME_LINE = re.compile(r"^#[0-9a-fA-F]{6}$", re.MULTILINE)
# matugen 4.2's config must hold both tables; an empty [config] alone does not parse.
_MATUGEN_CONFIG = "[config]\n\n[templates]\n"
_VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


class GeneratorError(Exception):
    """A generator is missing, too old, or failed; the message says why."""


@dataclass(frozen=True)
class GeneratedVariant:
    """What a generator gives for one variant."""

    # base00-base07.
    ramp: dict[str, str]
    # accent and secondary.
    roles: dict[str, str]
    # The generator's own base00-base0F.
    base16: dict[str, str]


@dataclass(frozen=True)
class Generated:
    # Name and version, e.g. "matugen 4.2.0".
    generator: str
    variants: dict[str, GeneratedVariant]


def choose_generator(name: str | None) -> str:
    """`name`, or the first installed of GENERATORS. Raises GeneratorError if not installed."""
    if name is not None:
        if shutil.which(name) is None:
            raise GeneratorError(f"generator {name} is not installed (not on PATH)")
        return name
    for candidate in GENERATORS:
        if shutil.which(candidate) is not None:
            return candidate
    raise GeneratorError(f"no palette generator installed: install one of {', '.join(GENERATORS)}")


def generate(picture: Path, name: str) -> Generated:
    """Run generator `name` on `picture`. Raises GeneratorError."""
    if name == "matugen":
        return run_matugen(picture)
    if name == "wallust":
        return run_wallust(picture)
    raise GeneratorError(f"generator {name}: no adapter (one of {', '.join(GENERATORS)})")


def _version(text: str) -> tuple[int, ...]:
    match = _VERSION.search(text)
    if match is None:
        raise GeneratorError(f"cannot read a version from {text.strip()!r}")
    return tuple(int(part) for part in match.groups() if part is not None)


def _run(command: list[str], env: Mapping[str, str] | None = None) -> str:
    logger.debug("running %s", " ".join(command))
    try:
        result = subprocess.run(
            command, check=False, capture_output=True, text=True, env=env, timeout=120
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GeneratorError(f"{command[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        raise GeneratorError(
            f"{command[0]} failed (exit {result.returncode})"
            + (f": {detail[-1]}" if detail else "")
        )
    return result.stdout


def matugen_label() -> str:
    """The installed matugen's name and version ("matugen 4.2.0"). Raises GeneratorError if
    it is missing or older than MATUGEN_MINIMUM."""
    if shutil.which("matugen") is None:
        raise GeneratorError("matugen is not installed (not on PATH)")
    version = _version(_run(["matugen", "--version"]))
    label = "matugen " + ".".join(map(str, version))
    if version[:2] < MATUGEN_MINIMUM:
        raise GeneratorError(
            f"{label} is too old: amontillado reads matugen >= "
            f"{'.'.join(map(str, MATUGEN_MINIMUM))} (3.x's JSON and command line differ)"
        )
    return label


def _throwaway_env(work: str) -> dict[str, str]:
    """A config, cache and state home in `work`: matugen touches nothing of the user's."""
    keys = ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME")
    return {**os.environ, **{key: work for key in keys}}


def _source(picture: Path | None, accent: str) -> list[str]:
    """matugen's subcommand for `picture`, or for the colour `accent` without one."""
    if picture is None:
        return ["color", "hex", accent]
    # Off a terminal matugen asks which source colour to use unless told.
    return ["image", str(picture), "--source-color-index", "0"]


def run_matugen(picture: Path) -> Generated:
    """matugen's palette of `picture`, both variants. Raises GeneratorError."""
    label = matugen_label()
    with tempfile.TemporaryDirectory(prefix="amo-matugen-") as work:
        config = Path(work) / "config.toml"
        config.write_text(_MATUGEN_CONFIG)
        command = ["matugen", *_source(picture, ""), "-c", str(config), "--dry-run", "-j", "hex"]
        output = _run([*command, "-q"], _throwaway_env(work))
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise GeneratorError(f"{label}: output is not JSON ({exc})") from exc
    return Generated(label, parse_matugen(data, label))


def matugen_render(
    templates: Mapping[str, str], *, mode: str, picture: Path | None, accent: str
) -> tuple[str, dict[str, str]]:
    """`templates` (name to template text) rendered by matugen itself, in one run: from
    `picture`, or from the colour `accent` without one, in `mode` (dark or light). Returns
    matugen's label and the rendered texts by name. The colours are matugen's, not a
    palette's (`render_with: matugen`). Raises GeneratorError."""
    label = matugen_label()
    with tempfile.TemporaryDirectory(prefix="amo-matugen-") as work:
        root = Path(work)
        tables = ["[config]\n"]
        outputs = {}
        for index, (name, text) in enumerate(templates.items()):
            source, output = root / f"in-{index}", root / f"out-{index}"
            source.write_text(text)
            outputs[name] = output
            # JSON strings are TOML basic strings: any path is quoted safely.
            tables.append(
                f"[templates.t{index}]\n"
                f"input_path = {json.dumps(str(source))}\n"
                f"output_path = {json.dumps(str(output))}\n"
            )
        config = root / "config.toml"
        config.write_text("\n".join(tables))
        command = ["matugen", *_source(picture, accent), "-c", str(config), "-m", mode, "-q"]
        _run(command, _throwaway_env(work))
        rendered = {}
        for name, output in outputs.items():
            try:
                rendered[name] = output.read_text()
            except OSError as exc:
                raise GeneratorError(f"{label} rendered no {name}: {exc}") from exc
    return label, rendered


def parse_matugen(data: object, label: str = "matugen") -> dict[str, GeneratedVariant]:
    """Both variants from matugen 4's JSON (`-j hex`). Raises GeneratorError."""
    try:
        neutral = data["palettes"]["neutral"]
        variants = {}
        for variant in VARIANTS:
            ramp = {
                key: _hex(neutral[str(tone)]["color"], label)
                for key, tone in zip(BASE16_KEYS[:8], RAMP_TONES[variant], strict=True)
            }
            roles = {
                role: _hex(data["colors"][role][variant]["color"], label)
                for role in ("primary", "secondary")
            }
            base16 = {
                key: _hex(data["base16"][key.lower()][variant]["color"], label)
                for key in BASE16_KEYS
            }
            variants[variant] = GeneratedVariant(
                ramp, {"accent": roles["primary"], "secondary": roles["secondary"]}, base16
            )
    except (KeyError, TypeError) as exc:
        raise GeneratorError(f"{label}: unexpected JSON (missing {exc})") from exc
    return variants


def tone_lightness(tone: float) -> float:
    """The OKLCH lightness of a grey at Material tone `tone` (CIELAB L*, 0-100)."""
    luminance = ((tone + 16) / 116) ** 3 if tone > 8 else tone / 903.3
    # A grey's OKLab lightness is the cube root of its luminance.
    return luminance ** (1 / 3)


def run_wallust(picture: Path) -> Generated:
    """wallust's colours of `picture`, both variants. Raises GeneratorError."""
    version = _version(_run(["wallust", "--version"]))
    label = "wallust " + ".".join(map(str, version))
    if version[:2] < WALLUST_MINIMUM:
        raise GeneratorError(
            f"{label} is too old: amontillado reads wallust >= "
            f"{'.'.join(map(str, WALLUST_MINIMUM))}"
        )
    with tempfile.TemporaryDirectory(prefix="amo-wallust-") as work:
        env = _throwaway_env(work)
        # No config, cache, terminal sequences or templates: only the colours, on stdout.
        command = ["wallust", "run", str(picture), "-N", "-n", "-s", "-T", "-q", "--print-scheme"]
        clustered = parse_wallust(_run([*command, "-p", "dark16"], env), label)
        ansi_command = [*command, "-k", "-c", "lchansi", "-p", "ansidark16"]
        ansi = parse_wallust(_run(ansi_command, env), label)
    return Generated(label, wallust_variants(clustered, ansi))


def parse_wallust(output: str, label: str = "wallust") -> list[str]:
    """Colours 0-15 from `wallust run --print-scheme`, which may also log a line or two."""
    colours = [colour.lower() for colour in _SCHEME_LINE.findall(output)]
    if len(colours) != 16:
        raise GeneratorError(f"{label}: expected 16 colours, got {len(colours)}")
    return colours


def wallust_variants(clustered: list[str], ansi: list[str]) -> dict[str, GeneratedVariant]:
    """Both variants from wallust's clustered colours (`-p dark16`) and its ANSI ones (`-c
    lchansi -p ansidark16`), each colours 0-15."""
    _, background_chroma, background_hue = hex_to_oklch(clustered[0])
    chroma = min(background_chroma, NEUTRAL_CHROMA)
    _, accent_chroma, accent_hue = max(
        (hex_to_oklch(colour) for colour in clustered[1:7]), key=lambda lch: lch[1]
    )
    variants = {}
    for variant in VARIANTS:
        ramp = {
            key: oklch_to_hex(tone_lightness(tone), chroma, background_hue)
            for key, tone in zip(BASE16_KEYS[:8], RAMP_TONES[variant], strict=True)
        }
        accent = oklch_to_hex(tone_lightness(ACCENT_TONES[variant]), accent_chroma, accent_hue)
        named = named_hues(variant, accent)
        own = {key: ansi[index] for index, key in ANSI_BASE16.items()}
        base16 = {**ramp, **{key: own.get(key, named[key]) for key in BASE16_KEYS[8:]}}
        variants[variant] = GeneratedVariant(ramp, {"accent": accent}, base16)
    return variants


def _hex(value: object, label: str) -> str:
    colour = str(value).lower()
    if not HEX_PATTERN.fullmatch(colour):
        raise GeneratorError(f"{label}: {value!r} is not a #rrggbb colour")
    return colour


def picture_palette(
    generated: Generated,
    *,
    name: str,
    hues: str,
    hue: float | None,
    source: dict[str, object],
) -> Palette:
    """The palette, both variants, completed from what a generator gave for a picture.

    `hues` says who assigns base08-base0F: `amontillado` (fixed named hues, amontillado.hues)
    or `generator` (its own colours); `hue` is the picture's hue metric, for a role the
    generator does not give. `source` (the picture's id, file and lightness) is recorded with
    the generator, the hues and the time.
    """
    variants = {}
    for variant, given in generated.variants.items():
        if hues == "amontillado":
            accents = named_hues(variant, given.roles["accent"])
        else:
            accents = {key: given.base16[key] for key in BASE16_KEYS[8:]}
        colours = {**given.ramp, **accents}
        variants[variant] = complete_variant(variant, colours, given.roles, hue=hue)
    recorded = {
        **source,
        "generator": generated.generator,
        "hues": hues,
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    return Palette(name, variants, recorded)
