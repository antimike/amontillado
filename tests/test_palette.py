from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from amontillado.colour import contrast_ratio, hex_to_oklch, hue_distance
from amontillado.palette import (
    BASE24_KEYS,
    ROLES,
    PaletteError,
    complete_variant,
    dump_palette,
    load_palette,
    palette_from_data,
    palette_from_schemes,
)

# A synthetic dark base16 scheme: neutral ramp, then red ... magenta, brown.
DARK = {
    "base00": "#1b1d2b",
    "base01": "#23263a",
    "base02": "#33467c",
    "base03": "#565f89",
    "base04": "#9aa5ce",
    "base05": "#c0caf5",
    "base06": "#d5d6db",
    "base07": "#e6e7ed",
    "base08": "#f7768e",
    "base09": "#ff9e64",
    "base0A": "#e0af68",
    "base0B": "#9ece6a",
    "base0C": "#7dcfff",
    "base0D": "#7aa2f7",
    "base0E": "#bb9af7",
    "base0F": "#a0644b",
}
LIGHT = {
    **DARK,
    "base00": "#f4f4f8",
    "base01": "#e6e7ed",
    "base05": "#343b58",
    "base07": "#1b1d2b",
}


def _lightness(colour: str) -> float:
    return hex_to_oklch(colour)[0]


def test_base24_is_derived_from_base16() -> None:
    dark = complete_variant("dark", DARK).base24
    assert list(dark) == list(BASE24_KEYS)
    assert {key: dark[key] for key in DARK} == DARK
    assert _lightness(dark["base10"]) == pytest.approx(_lightness(DARK["base00"]) - 0.03, abs=0.01)
    assert _lightness(dark["base11"]) == pytest.approx(_lightness(DARK["base00"]) - 0.06, abs=0.01)
    light = complete_variant("light", LIGHT).base24
    assert _lightness(light["base11"]) > _lightness(light["base10"]) > _lightness(LIGHT["base00"])
    for bright, base in (("base12", "base08"), ("base16", "base0D"), ("base17", "base0E")):
        assert _lightness(dark[bright]) == pytest.approx(_lightness(DARK[base]) + 0.08, abs=0.01)
        assert hue_distance(hex_to_oklch(dark[bright])[2], hex_to_oklch(DARK[base])[2]) < 3


def test_given_base24_keys_are_kept() -> None:
    variant = complete_variant("dark", {**DARK, "base12": "#ff0000", "base10": "#000000"})
    assert (variant.base24["base12"], variant.base24["base10"]) == ("#ff0000", "#000000")


def test_roles_are_derived() -> None:
    roles = complete_variant("dark", DARK).roles
    assert list(roles) == list(ROLES)
    assert roles["accent"] == DARK["base0D"]
    # Cyan is the named accent nearest in hue to blue.
    assert roles["secondary"] == DARK["base0C"]
    assert roles["on_accent"] == DARK["base00"]
    assert roles["border"] == roles["accent"]
    assert (roles["border_inactive"], roles["selection"], roles["on_selection"]) == (
        DARK["base03"],
        DARK["base02"],
        DARK["base05"],
    )
    assert (roles["error"], roles["warning"], roles["success"], roles["info"]) == (
        DARK["base08"],
        DARK["base0A"],
        DARK["base0B"],
        DARK["base0C"],
    )


def test_on_accent_is_the_better_label() -> None:
    roles = complete_variant("dark", DARK, {"accent": "#202020"}).roles
    assert roles["on_accent"] == DARK["base07"]
    assert contrast_ratio(roles["on_accent"], "#202020") > contrast_ratio(DARK["base00"], "#202020")


def test_accent_follows_the_picture_hue() -> None:
    roles = complete_variant("dark", DARK, hue=hex_to_oklch(DARK["base0B"])[2] + 5).roles
    assert roles["accent"] == DARK["base0B"]
    assert roles["secondary"] != roles["accent"]


def test_given_roles_are_kept() -> None:
    roles = complete_variant("dark", DARK, {"accent": "#abcdef", "warning": "#123456"}).roles
    assert (roles["accent"], roles["border"], roles["warning"]) == ("#abcdef", "#abcdef", "#123456")


def _palette_data() -> dict:
    return {
        "version": 1,
        "name": "night",
        "source": {"file": "night.png"},
        "variants": {"dark": {"base24": dict(DARK), "roles": {"accent": "#7AA2F7"}}},
    }


def test_palette_file_is_completed_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "night.yaml"
    path.write_text(yaml.safe_dump(_palette_data()))
    palette = load_palette(path)
    assert palette.name == "night" and palette.source == {"file": "night.png"}
    [(name, variant)] = palette.variants.items()
    assert name == "dark"
    assert list(variant.base24) == list(BASE24_KEYS)
    assert variant.roles["accent"] == "#7aa2f7"
    dumped = dump_palette(palette)
    assert "'#1b1d2b'" in dumped  # quoted, or YAML would read a comment
    assert palette_from_data(yaml.safe_load(dumped), "dumped") == palette


def test_adjusted_is_kept() -> None:
    data = _palette_data()
    data["variants"]["dark"]["adjusted"] = ["base03"]
    palette = palette_from_data(data, "p")
    assert palette.variants["dark"].adjusted == ("base03",)
    assert yaml.safe_load(dump_palette(palette))["variants"]["dark"]["adjusted"] == ["base03"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(version=2), "version must be 1"),
        (lambda d: d.update(name=""), "name must be"),
        (lambda d: d.update(variants={}), "dark, light or both"),
        (lambda d: d["variants"].update(dusk=d["variants"]["dark"]), "unknown variant 'dusk'"),
        (lambda d: d["variants"]["dark"]["base24"].update(base05="c0caf5"), "base05 must be"),
        (lambda d: d["variants"]["dark"]["base24"].update(base05=123456), "base05 must be"),
        (lambda d: d["variants"]["dark"]["base24"].pop("base0F"), "lacks base0F"),
        (lambda d: d["variants"]["dark"]["base24"].update(base18="#000000"), "'base18'"),
        (lambda d: d["variants"]["dark"]["roles"].update(acent="#000000"), "'acent'"),
        (lambda d: d["variants"]["dark"].update(adjusted="base03"), "adjusted must be"),
        (lambda d: d["variants"]["dark"].update(colours={}), "unknown key 'colours'"),
    ],
)
def test_invalid_palette(change: object, message: str) -> None:
    data = _palette_data()
    change(data)  # type: ignore[operator]
    with pytest.raises(PaletteError, match=message):
        palette_from_data(data, "p")


def test_unknown_top_level_key_warns(caplog: pytest.LogCaptureFixture) -> None:
    palette_from_data({**_palette_data(), "comment": "x"}, "p")
    assert "unknown key 'comment'" in caplog.text


def test_unreadable_palette(tmp_path: Path) -> None:
    with pytest.raises(PaletteError, match="No such file"):
        load_palette(tmp_path / "none.yaml")
    (tmp_path / "bad.yaml").write_text("variants: [")
    with pytest.raises(PaletteError, match="not valid YAML"):
        load_palette(tmp_path / "bad.yaml")


def _scheme(path: Path, colours: dict[str, str], *, name: str, variant: str | None) -> Path:
    data: dict[str, object] = {"system": "base16", "name": name, "author": "someone"}
    if variant is not None:
        data["variant"] = variant
    data["palette"] = dict(colours)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def _legacy_scheme(path: Path, colours: dict[str, str], *, name: str) -> Path:
    data = {"scheme": name, "author": "someone"}
    data.update({key: value.removeprefix("#").upper() for key, value in colours.items()})
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def test_one_scheme(tmp_path: Path) -> None:
    path = _scheme(tmp_path / "night.yaml", DARK, name="Night", variant="dark")
    palette = palette_from_schemes([path])
    assert palette.name == "Night"
    assert list(palette.variants) == ["dark"]
    assert palette.variants["dark"] == complete_variant("dark", DARK)
    assert palette.source == {
        "schemes": {"dark": {"name": "Night", "author": "someone", "file": "night.yaml"}}
    }


def test_legacy_scheme_without_a_variant(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    path = _legacy_scheme(tmp_path / "day.yaml", LIGHT, name="Day")
    palette = palette_from_schemes([path])
    assert list(palette.variants) == ["light"]
    assert palette.variants["light"].base24["base00"] == LIGHT["base00"]
    assert "light by its background" in caplog.text


def test_dark_and_light_schemes_make_one_palette(tmp_path: Path) -> None:
    light = _scheme(tmp_path / "l.yaml", LIGHT, name="Night light, soft", variant="light")
    dark = _legacy_scheme(tmp_path / "d.yaml", DARK, name="Night dark, soft")
    palette = palette_from_schemes([light, dark])
    assert palette.name == "Night"
    assert list(palette.variants) == ["dark", "light"]
    assert palette.variants["dark"].base24["base00"] == DARK["base00"]
    assert palette.variants["light"].base24["base00"] == LIGHT["base00"]


def test_base24_scheme_keeps_its_brights(tmp_path: Path) -> None:
    path = _scheme(tmp_path / "s.yaml", {**DARK, "base12": "#ff0000"}, name="S", variant="dark")
    assert palette_from_schemes([path]).variants["dark"].base24["base12"] == "#ff0000"


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ({"system": "base17", "name": "S", "palette": {}}, "system must be"),
        ({"author": "nobody"}, "not a tinted-theming scheme"),
        ({"scheme": "S", "base00": "123"}, "base00 must be"),
        ({"scheme": "S", "base00": 282828}, "base00 must be a quoted"),
        ({"scheme": "S", "base00": "282828"}, "lacks base01"),
        (["base00"], "must be a mapping"),
    ],
)
def test_invalid_scheme(tmp_path: Path, contents: object, message: str) -> None:
    path = tmp_path / "s.yaml"
    path.write_text(yaml.safe_dump(contents))
    with pytest.raises(PaletteError, match=message):
        palette_from_schemes([path])


def test_two_schemes_of_one_variant_are_refused(tmp_path: Path) -> None:
    first = _scheme(tmp_path / "a.yaml", DARK, name="A", variant="dark")
    second = _scheme(tmp_path / "b.yaml", DARK, name="B", variant="dark")
    with pytest.raises(PaletteError, match="both dark"):
        palette_from_schemes([first, second])
    with pytest.raises(PaletteError, match="one scheme"):
        palette_from_schemes([first, second, first])
