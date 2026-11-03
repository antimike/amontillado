from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import FIXTURES, fixture_json

from amontillado.colour import hex_to_oklch
from amontillado.contrast import apply_contrast, check
from amontillado.generators import (
    Generated,
    GeneratorError,
    choose_generator,
    generate,
    parse_matugen,
    parse_wallust,
    picture_palette,
    run_matugen,
    run_wallust,
    tone_lightness,
    wallust_variants,
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
    assert image.startswith(f"image {tmp_path / 'a.jpg'} --source-color-index 0 -c ")
    assert "--dry-run -j hex -q" in image
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
    with pytest.raises(GeneratorError, match="pywal: no adapter"):
        generate(tmp_path / "a.jpg", "pywal")


def _wallust_runs() -> tuple[list[str], list[str]]:
    return tuple(
        parse_wallust((FIXTURES / f"wallust-3.5.1-{name}.txt").read_text())
        for name in ("dark16", "ansidark16")
    )


def test_parse_wallust_skips_its_log_line() -> None:
    clustered, ansi = _wallust_runs()
    assert clustered[0] == "#393838" and len(clustered) == 16
    assert ansi[1] == "#7f3a3a"
    with pytest.raises(GeneratorError, match="expected 16 colours, got 2"):
        parse_wallust("#000000\n#ffffff\n")


def test_tone_lightness_is_a_greys_oklch_lightness() -> None:
    assert tone_lightness(0) == 0
    assert tone_lightness(100) == pytest.approx(1.0)
    # matugen's neutral tone 5, #0f1113, has OKLCH lightness 0.176.
    assert tone_lightness(5) == pytest.approx(0.177, abs=0.002)


def test_wallust_variants() -> None:
    clustered, ansi = _wallust_runs()
    variants = wallust_variants(clustered, ansi)
    dark, light = variants["dark"], variants["light"]
    # The ramp: matugen's tones, at the background's hue, nearly grey.
    for variant, descending in ((dark, False), (light, True)):
        lightness = [hex_to_oklch(colour)[0] for colour in variant.ramp.values()]
        assert lightness == sorted(lightness, reverse=descending)
        assert all(chroma < 0.01 for _, chroma, _ in map(hex_to_oklch, variant.ramp.values()))
    assert hex_to_oklch(dark.ramp["base00"])[0] == pytest.approx(tone_lightness(5), abs=0.01)
    # The accent: the most chromatic of colours 1-6, at matugen's primary tones.
    most = max(clustered[1:7], key=lambda colour: hex_to_oklch(colour)[1])
    for variant, tone in ((dark, 80), (light, 40)):
        lightness, _, hue = hex_to_oklch(variant.roles["accent"])
        assert lightness == pytest.approx(tone_lightness(tone), abs=0.01)
        assert hue == pytest.approx(hex_to_oklch(most)[2], abs=2)
    # Its own hues: ANSI 1-6 by the table in reverse; orange and brown named.
    assert [
        dark.base16[k] for k in ("base08", "base0B", "base0A", "base0D", "base0E", "base0C")
    ] == (ansi[1:7])
    assert light.base16["base08"] == ansi[1]
    named = named_hues("light", light.roles["accent"])
    assert (light.base16["base09"], light.base16["base0F"]) == (named["base09"], named["base0F"])


def test_run_wallust(fake_wallust: Path, tmp_path: Path) -> None:
    generated = run_wallust(tmp_path / "a.jpg")
    assert generated.generator == "wallust 3.5.1"
    assert generated.variants == wallust_variants(*_wallust_runs())
    calls = fake_wallust.read_text().splitlines()
    assert calls[0].startswith("--version")
    assert calls[1].startswith(f"run {tmp_path / 'a.jpg'} -N -n -s -T -q --print-scheme -p dark16")
    assert "-k -c lchansi -p ansidark16" in calls[2]
    cache = calls[1].rsplit("XDG_CACHE_HOME=", 1)[1]
    assert "amo-wallust-" in cache and not Path(cache).exists()
    assert generate(tmp_path / "a.jpg", "wallust").generator == "wallust 3.5.1"


def test_wallust_2_is_refused(
    fake_wallust: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_WALLUST_VERSION", "2.10.0")
    with pytest.raises(GeneratorError, match=r"wallust 2\.10\.0 is too old.*>= 3\.0"):
        run_wallust(tmp_path / "a.jpg")


def test_wallust_is_chosen_without_matugen(
    fake_wallust: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    which = shutil.which
    # A system matugen (Fedora's /usr/bin, on PATH as /bin) must not count.
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "matugen" else which(name))
    assert choose_generator(None) == "wallust"


def test_a_wallust_palette_passes_its_contrast_checks() -> None:
    generated = Generated("wallust 3.5.1", wallust_variants(*_wallust_runs()))
    for hues in ("amontillado", "generator"):
        palette = apply_contrast(
            picture_palette(generated, name="x", hues=hues, hue=None, source={}), "adjust"
        )
        for variant in palette.variants.values():
            assert check(variant) == []


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
