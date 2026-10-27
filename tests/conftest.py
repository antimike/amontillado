from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from amontillado.config import Config

SaveImage = Callable[..., Path]


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """A library root, an NSFW root and an index, all under tmp_path."""
    (tmp_path / "library").mkdir()
    (tmp_path / "nsfw").mkdir()
    return Config(
        library_roots=(tmp_path / "library",),
        nsfw_root=tmp_path / "nsfw",
        index_path=tmp_path / "state" / "index.sqlite",
    )


@pytest.fixture
def save_image() -> SaveImage:
    """Write a solid-colour image: save_image(path, rgb=(0, 0, 0), size=(64, 36))."""

    def save(
        path: Path, rgb: tuple[int, int, int] = (0, 0, 0), size: tuple[int, int] = (64, 36)
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.full((size[1], size[0], 3), rgb, dtype=np.uint8)).save(path)
        return path

    return save
