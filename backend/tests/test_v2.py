"""Chế độ đóng gói sẵn (mã hoá phía trình duyệt), giấu file, cỡ logo, tự dự phòng, khoá gọn."""
import base64
import io

import numpy as np

from app import payload

from .conftest import png_bytes
from .test_api import _embed, _embed_logo, _extract


def _post_embed(client, img, data, files=None):
    r = client.post("/api/embed", data={k: str(v) for k, v in data.items()},
                    files={"image": ("a.png", img, "image/png"), **(files or {})})
    assert r.status_code == 200, r.text
    j = r.json()
    return j, base64.b64decode(j["stego_png_base64"]), base64.b64decode(j["keys_npz_base64"])


def test_prepacked_payload_roundtrip_raw(client, photo):
    # Trình duyệt tự mã hoá: máy chủ không nhận mật khẩu ở cả hai chiều.
    packed = payload.encode("chỉ trình duyệt biết", "mat-khau")
    j, stego, keys = _post_embed(client, png_bytes(photo),
                                 {"kind": "text", "payload_encrypted": "true"},
                                 {"payload": ("p.bin", packed, "application/octet-stream")})
    assert j["encrypted"]
    out = _extract(client, stego, keys, raw="true").json()
    assert out["payload_format"] == payload.FORMAT and out["encrypted"] and out["message"] == ""
    got = base64.b64decode(out["payload_base64"])
    assert got == packed
    assert payload.decode(got, "mat-khau").message == "chỉ trình duyệt biết"
    # đường cũ (máy chủ giải mã) vẫn dùng được với cùng khoá
    assert _extract(client, stego, keys, password="mat-khau").json()["message"] == "chỉ trình duyệt biết"


def test_prepacked_logo_header_validated(client, photo):
    packed = payload.encode_bytes(b"\x00\x00\x08\x00\x08" + bytes(8), kind="logo")
    files = {"image": ("a.png", png_bytes(photo), "image/png"),
             "payload": ("p.bin", packed, "application/octet-stream")}
    assert client.post("/api/embed", data={"kind": "logo", "logo_header": "0,9999,8"}, files=files).status_code == 400
    r = client.post("/api/embed", data={"kind": "logo", "logo_header": "0,8,8"}, files=files)
    assert r.status_code == 200 and r.json()["logo_width"] == 8


def test_file_roundtrip(client, photo):
    content = bytes(range(256)) * 2
    j, stego, keys = _post_embed(client, png_bytes(photo), {"kind": "file", "redundancy": 1, "password": "pw"},
                                 {"file": ("thẻ bài.json", content, "application/json")})
    assert j["kind"] == "file"
    out = _extract(client, stego, keys, password="pw").json()
    assert out["kind"] == "file" and out["file_name"] == "thẻ bài.json" and out["integrity_ok"]
    assert base64.b64decode(out["file_base64"]) == content


def test_logo_max_side_and_auto_redundancy(client, photo):
    big, _, _ = _embed_logo(client, png_bytes(photo), redundancy=2)
    small, stego, keys = _embed_logo(client, png_bytes(photo), redundancy=2, logo_max_side=32,
                                     auto_redundancy="true")
    assert max(small["logo_width"], small["logo_height"]) == 32 < max(big["logo_width"], big["logo_height"])
    assert small["redundancy"] > 10 and small["usage_ratio"] <= 1
    assert _extract(client, stego, keys).json()["kind"] == "logo"


def test_keys_are_compact(client, photo):
    _, stego, keys = _embed(client, png_bytes(photo), "x" * 300, redundancy=3)
    with np.load(io.BytesIO(keys)) as z:
        assert z["selected_coords"].dtype == np.uint16 and z["deltas"].dtype == np.float32
    assert len(keys) < 120_000
    assert _extract(client, stego, keys).json()["message"] == "x" * 300


def test_heavy_crop_reads_back_exactly(client):
    """Cắt 15% mỗi cạnh (mất ~51% diện tích): căn chỉnh chính xác + bỏ phiếu có mặt nạ."""
    import json
    from .conftest import _photo_like
    rng = np.random.default_rng(5)
    img = _photo_like(600, 800).astype(np.float64)
    for _ in range(25):  # thêm chi tiết không lặp lại để định vị được
        y, x, s = rng.integers(0, 520), rng.integers(0, 720), rng.integers(20, 80)
        img[y:y + s, x:x + s] = rng.integers(0, 255, 3)
    _, stego, keys = _embed(client, png_bytes(img.astype(np.uint8)), "Thẻ rồng #001",
                            redundancy=15, delta=16)
    for steps in ([{"id": "crop", "value": 2}], [{"id": "shift", "value": 3}],
                  [{"id": "crop", "value": 2}, {"id": "jpeg", "value": 70}]):
        r = client.post("/api/attack", data={"steps": json.dumps(steps)}, files={
            "image": ("s.png", stego, "image/png"), "keys": ("k.npz", keys, "application/octet-stream")})
        j = r.json()
        assert j["status"] == "intact" and j["extract"]["message"] == "Thẻ rồng #001", (steps, j["ber"])
