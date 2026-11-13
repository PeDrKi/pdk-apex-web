import base64
import io

import numpy as np
from PIL import Image

from .conftest import png_bytes


def _embed(client, img_bytes, message, **form):
    data = {"message": message, **{k: str(v) for k, v in form.items()}}
    r = client.post("/api/embed", files={"image": ("a.png", img_bytes, "image/png")}, data=data)
    assert r.status_code == 200, r.text
    j = r.json()
    return j, base64.b64decode(j["stego_png_base64"]), base64.b64decode(j["keys_npz_base64"])


def _extract(client, img_bytes, keys_bytes, **form):
    return client.post(
        "/api/extract",
        files={"image": ("s.png", img_bytes, "image/png"),
               "keys": ("k.npz", keys_bytes, "application/octet-stream")},
        data={k: str(v) for k, v in form.items()},
    )


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_capacity(client, photo):
    r = client.post("/api/capacity", files={"image": ("a.png", png_bytes(photo), "image/png")},
                    data={"redundancy": "4"})
    j = r.json()
    assert j["width"] == 512 and j["height"] == 384
    assert j["capacity_bits"] == (512 // 4) * (384 // 4)
    assert j["usable_bits"] == j["capacity_bits"] // 4
    assert j["max_message_bytes_encrypted"] < j["max_message_bytes"]


def test_roundtrip_plain_unicode(client, photo):
    msg = "Bản quyền © PDK 2026 — giấu tin trong ảnh 🔒"
    j, stego, keys = _embed(client, png_bytes(photo), msg, redundancy=3)
    assert j["psnr_db"] > 35
    assert not j["encrypted"]
    r = _extract(client, stego, keys)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["message"] == msg
    assert out["integrity_ok"] is True


def test_roundtrip_encrypted(client, photo):
    j, stego, keys = _embed(client, png_bytes(photo), "bí mật", password="matkhau123")
    assert j["encrypted"]
    assert _extract(client, stego, keys).status_code == 401
    assert _extract(client, stego, keys, password="sai").status_code == 401
    r = _extract(client, stego, keys, password="matkhau123")
    assert r.status_code == 200 and r.json()["message"] == "bí mật"


def test_survives_jpeg(client, photo):
    _, stego, keys = _embed(client, png_bytes(photo), "PDK", redundancy=10, delta=24)
    buf = io.BytesIO()
    Image.open(io.BytesIO(stego)).save(buf, format="JPEG", quality=85)
    out = _extract(client, buf.getvalue(), keys).json()
    assert out["message"] == "PDK" and out["integrity_ok"]


def test_survives_crop_with_resync(client, photo):
    _, stego, keys = _embed(client, png_bytes(photo), "PDK", redundancy=10, delta=24)
    arr = np.array(Image.open(io.BytesIO(stego)))
    cropped = arr[20:-24, 16:-12]
    out = _extract(client, png_bytes(cropped), keys, resync="true").json()
    assert out["used_resync"]
    # Cắt mất mép ảnh làm mất hẳn một số khối: thông điệp vẫn đọc được,
    # nhưng CRC có thể báo lệch vài bit. Không ép integrity_ok ở đây.
    assert out["message"] == "PDK"


def test_message_too_long(client, photo):
    r = client.post("/api/embed", files={"image": ("a.png", png_bytes(photo), "image/png")},
                    data={"message": "x" * 5000, "redundancy": "10"})
    assert r.status_code == 400
    assert "quá dài" in r.json()["detail"]


def test_bad_files(client, photo):
    r = client.post("/api/capacity", files={"image": ("a.png", b"not an image", "image/png")})
    assert r.status_code == 400
    r = _extract(client, png_bytes(photo), b"garbage")
    assert r.status_code == 400


def test_rgba_preserved(client, photo):
    rgba = np.dstack([photo, np.full(photo.shape[:2], 200, np.uint8)])
    _, stego, keys = _embed(client, png_bytes(rgba), "alpha")
    im = Image.open(io.BytesIO(stego))
    assert im.mode == "RGBA"
    assert (np.array(im)[..., 3] == 200).all()
    assert _extract(client, stego, keys).json()["message"] == "alpha"


def _logo_png():
    arr = np.full((120, 200, 4), 0, np.uint8)  # nền trong suốt
    arr[30:90, 40:160, :3] = 20
    arr[30:90, 40:160, 3] = 255  # khối đặc màu tối = nét logo
    return png_bytes(arr)


def _embed_logo(client, img_bytes, **form):
    data = {"kind": "logo", **{k: str(v) for k, v in form.items()}}
    r = client.post("/api/embed", data=data, files={
        "image": ("a.png", img_bytes, "image/png"),
        "logo": ("logo.png", _logo_png(), "image/png")})
    assert r.status_code == 200, r.text
    j = r.json()
    return j, base64.b64decode(j["stego_png_base64"]), base64.b64decode(j["keys_npz_base64"])


def test_logo_binary_roundtrip(client, photo):
    j, stego, keys = _embed_logo(client, png_bytes(photo), redundancy=2)
    assert j["kind"] == "logo" and j["logo_width"] > 0
    out = _extract(client, stego, keys).json()
    assert out["kind"] == "logo" and out["integrity_ok"]
    got = np.array(Image.open(io.BytesIO(base64.b64decode(out["logo_png_base64"]))))
    preview = np.array(Image.open(io.BytesIO(base64.b64decode(j["logo_preview_base64"]))))
    assert got.shape == preview.shape and (got == preview).all()
    # logo tối trên nền trong suốt -> giữa logo đen, góc trắng
    h, w = got.shape
    assert got[h // 2, w // 2] == 0 and got[0, 0] == 255


def test_logo_gray_encrypted(client, photo):
    j, stego, keys = _embed_logo(client, png_bytes(photo), logo_mode="gray", password="pw")
    out = _extract(client, stego, keys, password="pw").json()
    assert out["kind"] == "logo" and out["encrypted"] and out["integrity_ok"]


def test_logo_missing_file(client, photo):
    r = client.post("/api/embed", data={"kind": "logo"},
                    files={"image": ("a.png", png_bytes(photo), "image/png")})
    assert r.status_code == 400


def test_logo_survives_jpeg(client, photo):
    _, stego, keys = _embed_logo(client, png_bytes(photo), redundancy=10, delta=24)
    buf = io.BytesIO()
    Image.open(io.BytesIO(stego)).save(buf, format="JPEG", quality=85)
    out = _extract(client, buf.getvalue(), keys).json()
    assert out["kind"] == "logo" and out["logo_png_base64"]
