"""Bộ đo khả năng bị phát hiện."""
import base64
import io

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import _photo_like, png_bytes


def _embed(**data):
    from app.main import app
    r = TestClient(app).post("/api/embed", files={"image": ("a.png", png_bytes(_photo_like()), "image/png")},
                             data={"message": "thong diep bi mat de thu bo do", **data})
    assert r.status_code == 200, r.text
    return r.json()


def test_cover_has_no_lattice_trace():
    from app.detect import analyze, lattice_scores
    cover = _photo_like()
    assert lattice_scores(cover).max() < 0.05
    assert analyze(cover, cover)["level"] == "low"


def test_more_blocks_used_means_easier_to_detect():
    quiet = _embed(redundancy="1", delta="5")
    loud = _embed(redundancy="5", delta="5", auto_redundancy="true")
    assert quiet["detect_level"] == "low"
    assert loud["detect_level"] == "high" and loud["detect_score"] > 0.5
    assert loud["detect_score"] > quiet["detect_score"] and loud["detect_baseline"] < 0.05


def test_default_strength_is_gentle_and_still_reads_back():
    from app.main import app
    j = _embed()  # mặc định: dự phòng 5, cường độ 5
    assert j["redundancy"] == 5 and j["psnr_db"] > 48
    stego = base64.b64decode(j["stego_png_base64"])
    assert np.array(Image.open(io.BytesIO(stego))).shape[:2] == (j["height"], j["width"])
    r = TestClient(app).post("/api/extract", files={"image": ("s.png", stego, "image/png"),
                                                    "keys": ("k.npz", base64.b64decode(j["keys_npz_base64"]))})
    assert r.status_code == 200 and r.json()["message"] == "thong diep bi mat de thu bo do"


def test_detect_hidden_when_disabled(monkeypatch):
    import dataclasses
    from app import main
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, show_detect=False))
    out = _embed(redundancy="1", delta="5")
    assert out["detect_level"] is None and out["detect_score"] is None
