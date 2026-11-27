import base64
import io
import json

import numpy as np
import pytest
from PIL import Image

from .conftest import png_bytes
from .test_api import _embed, _embed_logo


def _attack(client, stego, keys, steps, **form):
    files = {"image": ("s.png", stego, "image/png")}
    if keys is not None:
        files["keys"] = ("k.npz", keys, "application/octet-stream")
    return client.post("/api/attack", files=files, data={"steps": json.dumps(steps), **form})


def test_catalog(client):
    j = client.get("/api/attacks").json()
    assert len(j) == 20 and {a["group"] for a in j} == {"Nén", "Nhiễu", "Lọc", "Màu sắc", "Hình học"}


def test_attack_jpeg_then_read(client, photo):
    _, stego, keys = _embed(client, png_bytes(photo), "PDK 2026", redundancy=10, delta=24)
    r = _attack(client, stego, keys, [{"id": "jpeg", "value": 60}])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "intact" and j["ber"] == 0
    assert j["extract"]["message"] == "PDK 2026" and j["steps"] == ["Nén JPEG (Q60)"]
    assert Image.open(io.BytesIO(base64.b64decode(j["attacked_png_base64"]))).size == (512, 384)


def test_attack_geometric_logo(client, photo):
    _, stego, keys = _embed_logo(client, png_bytes(photo), redundancy=8, delta=24)
    j = _attack(client, stego, keys, [{"id": "crop", "value": 1}]).json()
    assert j["width"] < 512 and j["extract"]["kind"] == "logo" and j["extract"]["used_resync"]
    assert j["ber"] < 0.1


def test_attack_without_keys_only_returns_image(client, photo):
    j = _attack(client, png_bytes(photo), None, [{"id": "rotate", "value": 2}]).json()
    assert j["extract"] is None and j["status"] is None and j["attacked_png_base64"]


def test_attack_encrypted_needs_password(client, photo):
    _, stego, keys = _embed(client, png_bytes(photo), "bí mật", password="pw123456", redundancy=10)
    j = _attack(client, stego, keys, [{"id": "brightness_up", "value": 1}]).json()
    assert j["extract"] is None and "mật khẩu" in j["extract_error"]
    j = _attack(client, stego, keys, [{"id": "brightness_up", "value": 1}], password="pw123456").json()
    assert j["extract"]["message"] == "bí mật"


@pytest.mark.parametrize("steps", [
    "not json", [], [{"id": "nope"}], [{"id": "jpeg", "value": 200}], [{"id": "rotate", "value": 9}],
    [{"id": "rotate", "value": "2"}], [{"id": "jpeg", "value": 50}] * 2, {"id": "jpeg"},
])
def test_attack_bad_steps(client, photo, steps):
    raw = steps if isinstance(steps, str) else json.dumps(steps)
    r = client.post("/api/attack", files={"image": ("s.png", png_bytes(photo), "image/png")},
                    data={"steps": raw})
    assert r.status_code == 400


def test_battery(client, photo):
    _, stego, keys = _embed(client, png_bytes(photo), "PDK", redundancy=15, delta=24)
    r = client.post("/api/attack/battery", data={"level": "1"}, files={
        "image": ("s.png", stego, "image/png"), "keys": ("k.npz", keys, "application/octet-stream")})
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(j["rows"]) == 20 and j["intact"] + j["partial"] + j["broken"] == 20
    assert j["intact"] >= 12


def test_compare(client, photo):
    orig = png_bytes(photo)
    _, stego, _ = _embed(client, orig, "PDK", redundancy=2)
    r = client.post("/api/compare", files={"original": ("a.png", orig, "image/png"),
                                           "stego": ("b.png", stego, "image/png")})
    assert r.status_code == 200, r.text
    j = r.json()
    n_bits = (3 + 5) * 8
    assert 0 < j["changed_blocks"] <= n_bits * 2 and j["changed_pixels"] <= n_bits * 2 * 16
    assert j["max_diff"] > 0 and j["psnr_db"] > 40
    heat = np.array(Image.open(io.BytesIO(base64.b64decode(j["heatmap_png_base64"]))))
    assert heat.shape == (384, 512, 3)


def test_compare_identical_and_mismatch(client, photo):
    a = png_bytes(photo)
    j = client.post("/api/compare", files={"original": ("a.png", a, "image/png"),
                                           "stego": ("b.png", a, "image/png")}).json()
    assert j["changed_pixels"] == 0 and j["psnr_db"] is None
    r = client.post("/api/compare", files={"original": ("a.png", a, "image/png"),
                                           "stego": ("b.png", png_bytes(photo[:100]), "image/png")})
    assert r.status_code == 400


def test_custom_crop_and_resize_steps():
    import json
    import numpy as np
    from app import attacks as atk
    img = (np.random.RandomState(0).rand(100, 120, 3) * 255).astype(np.uint8)
    crop = atk.parse_steps(json.dumps([{"id": "crop_custom", "params": {"x": 0.25, "y": 0.1, "w": 0.5, "h": 0.5}}]))
    assert atk.apply_steps(img, crop).shape[:2] == (50, 60) and "Cắt vùng" in crop[0].label
    rs = atk.parse_steps(json.dumps([{"id": "resize_custom", "params": {"w": 80, "h": 40}}]))
    assert atk.apply_steps(img, rs).shape[:2] == (40, 80) and "80×40" in rs[0].label
    for bad in ({"x": 0.8, "y": 0, "w": 0.5, "h": 0.5}, {"x": 0, "y": 0, "w": 0.0, "h": 1}):
        try:
            atk.parse_steps(json.dumps([{"id": "crop_custom", "params": bad}]))
            assert False
        except atk.AttackError:
            pass
    try:
        atk.apply_steps(img, atk.parse_steps(json.dumps([{"id": "resize_custom", "params": {"w": 4000, "h": 4000}}])))
        assert False
    except atk.AttackError:
        pass


def test_custom_erase_keeps_size_and_blanks_region():
    import json
    import numpy as np
    from app import attacks as atk
    img = np.zeros((100, 120, 3), np.uint8)
    out = atk.apply_steps(img, atk.parse_steps(json.dumps(
        [{"id": "erase_custom", "params": {"x": 0.5, "y": 0.5, "w": 0.25, "h": 0.25}}])))
    assert out.shape == img.shape and out[60, 70].min() == 255 and out[10, 10].max() == 0
