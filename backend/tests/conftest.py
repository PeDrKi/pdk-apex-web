import io
import os
import sys

os.environ.setdefault("RATE_LIMIT_PER_MIN", "0")
os.environ.setdefault("HIBP_CHECK", "0")  # test không gọi ra mạng
os.environ.setdefault("SHOW_DETECT", "1")
os.environ.setdefault("LOGIN_ATTEMPTS_PER_MIN", "0")
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="apexweb-test-")
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _photo_like(h=384, w=512, seed=0):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    base = 128 + 60 * np.sin(x / 37.0) * np.cos(y / 23.0) + 30 * np.sin((x + y) / 11.0)
    rgb = np.stack([base, base * 0.9 + 20, 255 - base * 0.8], axis=-1)
    rgb += rng.normal(0, 8, rgb.shape)
    return np.clip(rgb, 0, 255).astype(np.uint8)


def png_bytes(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def photo():
    return _photo_like()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)
