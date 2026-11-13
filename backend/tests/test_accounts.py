"""Tài khoản, phiên đăng nhập và lịch sử."""
import base64

import pytest
from fastapi.testclient import TestClient

from tests.conftest import png_bytes


def _client():
    from app.main import app
    return TestClient(app)


_n = 0


def _register(c, password="mat-khau-dai-1"):
    global _n
    _n += 1
    name = f"user{_n}_{id(c) % 10000}"
    r = c.post("/api/auth/register", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    return name


@pytest.fixture(scope="module")
def embedded():
    """Một ảnh đã giấu tin + file khoá thật."""
    from tests.conftest import _photo_like
    c = _client()
    r = c.post("/api/embed", files={"image": ("a.png", png_bytes(_photo_like()), "image/png")},
               data={"message": "xin chao", "redundancy": "3"})
    assert r.status_code == 200, r.text
    j = r.json()
    return base64.b64decode(j["stego_png_base64"]), base64.b64decode(j["keys_npz_base64"])


def _save(c, embedded, name="the-bai"):
    stego, keys = embedded
    return c.post("/api/history", files={"stego": ("s.png", stego, "image/png"), "keys": ("k.npz", keys)},
                  data={"name": name, "psnr": "41.5"})


def test_guest_has_no_account_and_cannot_use_history(embedded):
    c = _client()
    assert c.get("/api/auth/me").json()["user"] is None
    assert c.get("/api/history").status_code == 401
    assert _save(c, embedded).status_code == 401


def test_register_login_logout():
    c = _client()
    name = _register(c)
    assert c.get("/api/auth/me").json()["user"]["username"] == name
    cookie = c.headers.get("cookie") or ""
    set_cookie = c.post("/api/auth/login", json={"username": name, "password": "mat-khau-dai-1"}).headers["set-cookie"]
    assert "HttpOnly" in set_cookie and "samesite=strict" in set_cookie.lower()

    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").json()["user"] is None

    assert c.post("/api/auth/login", json={"username": name, "password": "sai-mat-khau"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "khong-ton-tai", "password": "x" * 10}).status_code == 401
    # tên đăng nhập không phân biệt hoa thường
    assert c.post("/api/auth/login", json={"username": name.upper(), "password": "mat-khau-dai-1"}).status_code == 200
    assert c.get("/api/auth/me").json()["user"]["username"] == name


def test_register_validation():
    c = _client()
    name = _register(c)
    c2 = _client()
    assert c2.post("/api/auth/register", json={"username": name, "password": "mat-khau-dai-1"}).status_code == 409
    assert c2.post("/api/auth/register", json={"username": "ab", "password": "mat-khau-dai-1"}).status_code == 400
    assert c2.post("/api/auth/register", json={"username": "ten co dau cach", "password": "mat-khau-dai-1"}).status_code == 400
    assert c2.post("/api/auth/register", json={"username": "hople123", "password": "ngan"}).status_code == 400
    assert c2.post("/api/auth/register", json={"username": "hople123", "password": "HopLe123"}).status_code == 400


def test_password_is_hashed_and_session_token_not_stored():
    from app import db
    c = _client()
    name = _register(c, "bi-mat-rieng-tu-9")
    token = c.cookies.get("apex_session")
    with db.connect() as con:
        pw_hash = con.execute("SELECT pw_hash FROM users WHERE username = ?", (name,)).fetchone()["pw_hash"]
        tokens = [r["token_hash"] for r in con.execute("SELECT token_hash FROM sessions").fetchall()]
    assert pw_hash.startswith("scrypt$") and "bi-mat-rieng-tu-9" not in pw_hash
    assert token and token not in tokens


def test_history_roundtrip_and_extract(embedded):
    c = _client()
    _register(c)
    r = _save(c, embedded, "thẻ/bài: số 1")
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["kind"] == "text" and item["encrypted"] is False and item["redundancy"] == 3
    assert item["width"] == 512 and item["height"] == 384
    assert "/" not in item["name"] and ":" not in item["name"]

    h = c.get("/api/history").json()
    assert [i["id"] for i in h["items"]] == [item["id"]]
    assert h["used_bytes"] == item["stego_bytes"] + item["keys_bytes"]

    stego = c.get(f"/api/history/{item['id']}/stego")
    keys = c.get(f"/api/history/{item['id']}/keys")
    thumb = c.get(f"/api/history/{item['id']}/thumb")
    assert stego.content == embedded[0] and keys.content == embedded[1]
    assert thumb.headers["content-type"] == "image/jpeg" and thumb.content[:2] == b"\xff\xd8"
    assert "attachment" in stego.headers["content-disposition"]

    # File lấy lại từ lịch sử vẫn đọc ra đúng nội dung.
    r = c.post("/api/extract", files={"image": ("s.png", stego.content, "image/png"), "keys": ("k.npz", keys.content)})
    assert r.json()["message"] == "xin chao"

    assert c.delete(f"/api/history/{item['id']}").status_code == 200
    assert c.get("/api/history").json()["items"] == []
    assert c.get(f"/api/history/{item['id']}/stego").status_code == 404


def test_users_cannot_see_each_other(embedded):
    a, b = _client(), _client()
    _register(a)
    _register(b)
    item = _save(a, embedded).json()
    assert b.get("/api/history").json()["items"] == []
    for what in ("stego", "keys", "thumb"):
        assert b.get(f"/api/history/{item['id']}/{what}").status_code == 404
    assert b.delete(f"/api/history/{item['id']}").status_code == 404
    assert len(a.get("/api/history").json()["items"]) == 1
    assert a.get("/api/history/..%2F..%2Fapp.db/stego").status_code == 404


def test_history_rejects_bad_files(embedded):
    c = _client()
    _register(c)
    stego, keys = embedded
    bad = c.post("/api/history", files={"stego": ("s.png", b"<html>", "image/png"), "keys": ("k.npz", keys)})
    assert bad.status_code == 400
    bad = c.post("/api/history", files={"stego": ("s.png", stego, "image/png"), "keys": ("k.npz", b"khong phai npz")})
    assert bad.status_code == 400
    assert c.get("/api/history").json()["items"] == []


def test_item_quota(embedded, monkeypatch):
    from app import accounts
    c = _client()
    _register(c)
    monkeypatch.setattr(accounts, "settings", type("S", (), {**{k: getattr(accounts.settings, k) for k in dir(accounts.settings) if not k.startswith("_")}, "max_items_per_user": 1})())
    assert _save(c, embedded).status_code == 200
    assert _save(c, embedded).status_code == 409


def test_logout_invalidates_stolen_cookie(embedded):
    c = _client()
    _register(c)
    token = c.cookies.get("apex_session")
    c.post("/api/auth/logout")
    thief = _client()
    thief.cookies.set("apex_session", token)
    assert thief.get("/api/history").status_code == 401


def test_change_password_logs_out_other_devices():
    c = _client()
    name = _register(c, "mat-khau-cu-123")
    other = _client()
    assert other.post("/api/auth/login", json={"username": name, "password": "mat-khau-cu-123"}).status_code == 200
    assert c.post("/api/auth/password", json={"current": "sai", "new": "mat-khau-moi-456"}).status_code == 401
    assert c.post("/api/auth/password", json={"current": "mat-khau-cu-123", "new": "mat-khau-moi-456"}).status_code == 200
    assert other.get("/api/history").status_code == 401
    assert c.get("/api/history").status_code == 200
    assert _client().post("/api/auth/login", json={"username": name, "password": "mat-khau-cu-123"}).status_code == 401


def test_delete_account_removes_data(embedded):
    from app import accounts, db
    c = _client()
    name = _register(c)
    _save(c, embedded)
    from app.storage import storage
    with db.connect() as con:
        uid = con.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()["id"]
        item_ids = [r["id"] for r in con.execute("SELECT id FROM items WHERE user_id = ?", (uid,)).fetchall()]
    keys = [k for i in item_ids for k in accounts._keys_of(uid, i).values()]
    assert len(keys) == 3 and all(storage.get(k) for k in keys)
    assert c.post("/api/auth/delete", json={"password": "sai"}).status_code == 401
    assert c.post("/api/auth/delete", json={"password": "mat-khau-dai-1"}).status_code == 200
    assert not any(storage.get(k) for k in keys)
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) AS n FROM items WHERE user_id = ?", (uid,)).fetchone()["n"] == 0
    assert c.post("/api/auth/login", json={"username": name, "password": "mat-khau-dai-1"}).status_code == 401


def test_cross_site_requests_are_refused():
    c = _client()
    name = _register(c)
    evil = {"origin": "https://evil.example"}
    assert c.post("/api/auth/logout", headers=evil).status_code == 403
    assert c.delete("/api/history", headers=evil).status_code == 403
    assert c.post("/api/auth/login", json={"username": name, "password": "mat-khau-dai-1"}, headers=evil).status_code == 403
    assert c.post("/api/auth/logout", headers={"origin": "http://testserver"}).status_code == 200


def test_login_throttle(monkeypatch):
    from app import accounts
    from app.security import RateLimiter
    monkeypatch.setattr(accounts, "_ip_limiter", RateLimiter(3))
    c = _client()
    codes = [c.post("/api/auth/login", json={"username": "ai-do", "password": "x" * 9}).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]


def test_embed_can_save_directly_for_logged_in_user():
    from tests.conftest import _photo_like
    c = _client()
    img = {"image": ("a.png", png_bytes(_photo_like()), "image/png")}
    data = {"message": "luu thang", "redundancy": "3", "save": "true", "save_name": "the-01"}
    # Khách gửi save=true cũng không lưu gì.
    j = c.post("/api/embed", files=img, data=data).json()
    assert j["saved_id"] is None and j["save_error"] is None

    _register(c)
    j = c.post("/api/embed", files=img, data=data).json()
    items = c.get("/api/history").json()["items"]
    assert [i["id"] for i in items] == [j["saved_id"]]
    assert items[0]["name"] == "the-01" and items[0]["kind"] == "text" and items[0]["redundancy"] == j["redundancy"]
    stego = c.get(f"/api/history/{j['saved_id']}/stego").content
    assert stego == base64.b64decode(j["stego_png_base64"])
    # Không bật save thì không lưu.
    c.post("/api/embed", files=img, data={"message": "khong luu"})
    assert len(c.get("/api/history").json()["items"]) == 1
    # Yêu cầu từ trang khác không được lưu hộ.
    r = c.post("/api/embed", files=img, data=data, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_responses_are_gzipped():
    c = _client()
    r = c.get("/api/attacks", headers={"accept-encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip" and r.json()
