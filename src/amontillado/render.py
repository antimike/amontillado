"""Views of a palette and the renderers that fill templates from them.

docs/design.md, "Theme engine (v0.2)", "Formats and views". A view is the set of variables a
template format expects, made from one variant of a palette. Mustache is tinted-theming's
builder spec: per colour (every base24 key and every role) its hex, per-channel hex, BGR hex,
RGB 0-255, RGB 0-65535 and 0-1 decimals, plus the scheme variables. A variable a template
names that the view does not have is a render error, never an empty string.
"""

from __future__ import annotations

import re

import pystache
from pystache.common import PystacheError
from pystache.parser import ParsingError

from amontillado.palette import Palette, Variant


class RenderError(Exception):
    """A template cannot be rendered; the message says why."""


def mustache_view(palette: Palette, variant: str) -> dict[str, object]:
    """The tinted builder variables of `palette`'s `variant`."""
    colours: Variant = palette.variants[variant]
    view: dict[str, object] = {}
    for name, colour in (*colours.base24.items(), *colours.roles.items()):
        hex_ = colour.removeprefix("#")
        channels = dict(zip("rgb", (hex_[0:2], hex_[2:4], hex_[4:6]), strict=True))
        view[f"{name}-hex"] = hex_
        view[f"{name}-hex-bgr"] = channels["b"] + channels["g"] + channels["r"]
        for channel, pair in channels.items():
            value = int(pair, 16)
            view[f"{name}-hex-{channel}"] = pair
            view[f"{name}-rgb-{channel}"] = value
            view[f"{name}-rgb16-{channel}"] = value * 257
            view[f"{name}-dec-{channel}"] = f"{value / 255:.8f}"
    slug = _slug(palette.name)
    view.update(
        {
            "scheme-name": palette.name,
            # Template headers name them; amontillado's palettes have no description.
            "scheme-author": _author(palette, variant),
            "scheme-description": "",
            "scheme-slug": slug,
            "scheme-slug-underscored": slug.replace("-", "_"),
            "scheme-system": "base24",
            "scheme-variant": variant,
            "scheme-is-dark-variant": variant == "dark",
            "scheme-is-light-variant": variant == "light",
        }
    )
    return view


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "palette"


def _author(palette: Palette, variant: str) -> str:
    schemes = palette.source.get("schemes")
    scheme = schemes.get(variant) if isinstance(schemes, dict) else None
    author = scheme.get("author") if isinstance(scheme, dict) else None
    return author if isinstance(author, str) else ""


def render_mustache(template: str, view: dict[str, object]) -> str:
    """`template` filled from `view`. Raises RenderError for an unknown variable, a template
    that does not parse, or a partial (templates are single files)."""
    # No HTML escaping: the output is a config file. An empty partials mapping keeps `{{> x}}`
    # from reading x.mustache out of the working directory.
    renderer = pystache.Renderer(missing_tags="strict", escape=lambda text: text, partials={})
    try:
        return renderer.render(template, view)
    # ParsingError is not a PystacheError.
    except (PystacheError, ParsingError) as exc:
        raise RenderError(str(exc)) from exc
