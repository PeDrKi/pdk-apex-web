import io
import zipfile

import numpy as np
import pytest

from .conftest import png_bytes
from .test_api import _embed, _extract


def _load(keys_bytes):
    with np.load(io.BytesIO(keys_bytes)) as z:
        return {k: z[k] for k in z.files}


def _dump(d):
    buf = io.BytesIO()
    np.savez_compressed(buf, **d)
    return buf.getvalue()


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_docs_disabled_by_default(client):
    assert client.get("/api/openapi.json").status_code == 404


def test_oversized_request_rejected(client, monkeypatch):
    from app import security
    monkeypatch.setattr(type(security.settings), "max_request_bytes", property(lambda s: 1000))
    r = client.post("/api/capacity", files={"image": ("a.png", b"x" * 5000, "image/png")})
    assert r.status_code == 413


def test_rate_limit(client, photo, monkeypatch):
    from app.security import rate_limiter
    monkeypatch.setattr(rate_limiter, "limit", 3)
    rate_limiter._hits.clear()
    codes = [client.post("/api/capacity", files={"image": ("a.png", b"x", "image/png")}).status_code
             for _ in range(5)]
    assert codes[:3] == [400, 400, 400] and codes[3:] == [429, 429]
    rate_limiter._hits.clear()


def test_pickle_in_keys_rejected(client, photo):
    buf = io.BytesIO()
    np.savez(buf, selected_coords=np.array([{"a": 1}], dtype=object), allow_pickle=True)
    assert _extract(client, png_bytes(photo), buf.getvalue()).status_code == 400


def test_zip_bomb_keys_rejected(client, photo):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("selected_coords.npy", b"\0" * (70 * 1024 * 1024))
    assert len(buf.getvalue()) < 1024 * 1024
    r = _extract(client, png_bytes(photo), buf.getvalue())
    assert r.status_code == 400 and "quá lớn" in r.json()["detail"]


@pytest.mark.parametrize("mutate", [
    lambda k: k.update(selected_coords=-k["selected_coords"] - 1),
    lambda k: k.update(selected_coords=k["selected_coords"] + 10**7),
    lambda k: k.update(deltas=k["deltas"] * 0),
    lambda k: k.update(deltas=k["deltas"] * np.nan),
    lambda k: k.update(K1_perm=k["K1_perm"] * 0),
    lambda k: k.update(K1_perm=k["K1_perm"] + 10**6),
    lambda k: k.update(slot_bit_map=k["slot_bit_map"] + 10**6),
    lambda k: k.update(n_bits=np.array(10**9)),
    lambda k: k.update(redundancy=np.array(0)),
    lambda k: k.update(ngdc_bin_ids=k["ngdc_bin_ids"] + 1000),
    lambda k: k.update(n_bins=np.array(10**9)),
    lambda k: k.update(orig_shape=np.array([10**5, 10**5], dtype=np.int32)),
    lambda k: k.update(thumbnail=np.zeros((1, 1))),
    lambda k: k.pop("deltas"),
])
def test_tampered_keys_never_crash(client, photo, mutate):
    _, stego, keys = _embed(client, png_bytes(photo), "PDK", redundancy=3)
    k = {n: (v.astype(np.int64) if v.dtype.kind == "u" else v) for n, v in _load(keys).items()}
    mutate(k)
    r = _extract(client, stego, _dump(k))
    assert r.status_code == 400, r.text


def test_bad_params_rejected(client, photo):
    img = {"image": ("a.png", png_bytes(photo), "image/png")}
    for data in ({"message": "x", "seed": "-1"}, {"message": "x", "delta": "nan"},
                 {"message": "x", "redundancy": "0"}, {"message": "x", "password": "p" * 300}):
        assert client.post("/api/embed", files=img, data=data).status_code == 400, data


def test_unusual_image_format_rejected(client):
    # Pillow đọc được PPM, nhưng định dạng này không nằm trong danh sách cho phép.
    ppm = b"P6 2 2 255 " + bytes(12)
    r = client.post("/api/capacity", files={"image": ("a.ppm", ppm, "image/x-portable-pixmap")})
    assert r.status_code == 400
