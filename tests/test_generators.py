from __future__ import annotations

from pathlib import Path

import pytest
from conftest import fixture_json

from amontillado.colour import hex_to_oklch
from amontillado.generators import (
    Generated,
    GeneratorError,
    choose_generator,
    generate,
    parse_matugen,
    picture_palette,
    run_matugen,
)
from amontillado.hues import named_hues
from amontillado.palette import BASE16_KEYS


def test_parse_matugen_gives_both_variants() -> None:
    variants = parse_matugen(fixture_json("matugen-4.2.0.json"))
    assert set(variants) == {"dark", "light"}
    dark, light = variants["dark"], variants["light"]
    # Material primary and secondary, per mode.
    assert dark.roles == {"accent": "#99ccfa", "secondary": "#b8c8da"}
    assert light.roles == {"accent": "#2c638b", "secondary": "#51606f"}
    assert list(dark.ramp) == list(BASE16_KEYS[:8])
    assert list(dark.base16) == list(BASE16_KEYS)
    # The ramp runs dark to light for the dark variant, light to dark for the light one.
    dark_l = [hex_to_oklch(colour)[0] for colour in dark.ramp.values()]
    light_l = [hex_to_oklch(colour)[0] for colour in light.ramp.values()]
    assert dark_l == sorted(dark_l)
    assert light_l == sorted(light_l, reverse=True)
    assert dark.ramp["base00"] == "#0f1113"  # neutral tone 5
    # base16 keys are lower-case in matugen's JSON.
    assert dark.base16["base0A"] == "#090e12"


def test_parse_matugen_names_what_is_missing() -> None:
    data = fixture_json("matugen-4.2.0.json")
    del data["palettes"]["neutral"]["50"]
    with pytest.raises(GeneratorError, match=r"unexpected JSON.*'50'"):
        parse_matugen(data)
    data = fixture_json("matugen-4.2.0.json")
    data["colors"]["primary"]["dark"]["color"] = "blue"
    with pytest.raises(GeneratorError, match="'blue' is not a #rrggbb colour"):
        parse_matugen(data)


def test_run_matugen(fake_matugen: Path, tmp_path: Path) -> None:
    generated = run_matugen(tmp_path / "a.jpg")
    assert generated.generator == "matugen 4.2.0"
    assert generated.variants["dark"].roles["accent"] == "#99ccfa"
    calls = fake_matugen.read_text().splitlines()
    assert calls[0].startswith("--version")
    image = calls[1]
    assert image.startswith(f"image {tmp_path / 'a.jpg'} -c ")
    assert "--dry-run -j hex -q --source-color-index 0" in image
    # Run in a throwaway cache, gone afterwards.
    cache = image.rsplit("XDG_CACHE_HOME=", 1)[1]
    assert "amo-matugen-" in cache
    assert not Path(cache).exists()


def test_matugen_3_is_refused(
    fake_matugen: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MATUGEN_VERSION", "3.1.0")
    with pytest.raises(GeneratorError, match=r"matugen 3\.1\.0 is too old.*>= 4\.0"):
        run_matugen(tmp_path / "a.jpg")
    assert len(fake_matugen.read_text().splitlines()) == 1


def test_a_failing_generator_says_so(fake_matugen: Path, tmp_path: Path) -> None:
    script = fake_matugen.parent / "fake-bin" / "matugen"
    script.write_text(
        '#!/bin/sh\necho "matugen 4.2.0"\n[ "$1" = --version ] || { echo boom >&2; exit 2; }\n'
    )
    with pytest.raises(GeneratorError, match=r"matugen failed \(exit 2\): boom"):
        run_matugen(tmp_path / "a.jpg")


def test_choose_generator(fake_matugen: Path) -> None:
    assert choose_generator(None) == "matugen"
    assert choose_generator("matugen") == "matugen"
    with pytest.raises(GeneratorError, match="wallust is not installed"):
        choose_generator("wallust")


def test_no_generator_installed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(GeneratorError, match="install one of matugen, wallust"):
        choose_generator(None)


def test_generate_without_an_adapter(tmp_path: Path) -> None:
    with pytest.raises(GeneratorError, match="wallust: no adapter yet"):
        generate(tmp_path / "a.jpg", "wallust")


def test_picture_palette() -> None:
    generated = Generated("matugen 4.2.0", parse_matugen(fixture_json("matugen-4.2.0.json")))
    palette = picture_palette(
        generated, name="sea", hues="generator", hue=200.0, source={"picture": "abc"}
    )
    assert palette.name == "sea"
    assert list(palette.source) == ["picture", "generator", "hues", "generated"]
    dark = palette.variants["dark"]
    # The generator's own colours under hues: generator; its accent, not one derived.
    assert dark.base24["base08"] == generated.variants["dark"].base16["base08"]
    assert dark.roles["accent"] == "#99ccfa"
    assert len(dark.base24) == 24
    assert palette.source["hues"] == "generator"
    # Named hues under hues: amontillado; the ramp and accent are still the generator's.
    named = picture_palette(generated, name="sea", hues="amontillado", hue=None, source={})
    assert named.source["hues"] == "amontillado"
    for variant in ("dark", "light"):
        base24 = named.variants[variant].base24
        assert {key: base24[key] for key in BASE16_KEYS[8:]} == named_hues(
            variant, generated.variants[variant].roles["accent"]
        )
        assert base24["base00"] == generated.variants[variant].ramp["base00"]
