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


def test_proof_lookup_by_hash(embedded):
    import hashlib
    stego, keys = embedded
    c = _client()
    name = _register(c)
    item = _save(c, embedded, "bang-chung").json()
    assert item["stego_sha256"] == hashlib.sha256(stego).hexdigest()

    guest = _client()  # tra cứu là công khai
    for data, what in ((stego, "stego"), (keys, "keys")):
        j = guest.get(f"/api/proof/{hashlib.sha256(data).hexdigest()}").json()
        assert j["found"] and j["matched"] == what  # file dùng chung giữa các test: người lưu đầu tiên thắng
        assert j["registered_at"] <= item["created_at"]  # trả về lần lưu sớm nhất
    assert guest.get(f"/api/proof/{'0' * 64}").json() == {
        "found": False, "matched": None, "registered_at": None, "owner": None, "name": None}
    assert guest.get("/api/proof/khong-phai-ma-bam").status_code == 400
    assert j["owner"]  # tên tài khoản của người lưu đầu tiên
    assert name


def test_sealed_keys_are_stored_without_parsing(embedded):
    stego, _ = embedded
    c = _client()
    _register(c)
    sealed = b"APEXKEY1" + bytes([1]) + (7).to_bytes(2, "big") + bytes(16 + 12) + b"x" * 64
    r = c.post("/api/history", files={"stego": ("s.png", stego, "image/png"), "keys": ("k.apexkey", sealed)},
               data={"name": "kin"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["kind"] == "logo" and j["encrypted"] is True and j["redundancy"] == 7
    assert c.get(f"/api/history/{j['id']}/keys").content == sealed
    bad = b"APEXKEY1" + bytes([9]) + bytes(60)
    assert c.post("/api/history", files={"stego": ("s.png", stego, "image/png"), "keys": ("k", bad)}).status_code == 400


def test_old_database_gets_new_columns(tmp_path, monkeypatch):
    import sqlite3
    from app import db
    path = tmp_path / "cu.db"
    con = sqlite3.connect(path)
    con.executescript(db.SQLITE_SCHEMA.replace(",\n    stego_sha256 TEXT,\n    keys_sha256  TEXT", ""))
    con.close()
    assert "stego_sha256" not in {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(items)")}
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "_ready", False)
    monkeypatch.setattr(db, "IS_POSTGRES", False)
    with db.connect() as c2:
        cols = {r[1] for r in c2.execute("PRAGMA table_info(items)")}
    assert {"stego_sha256", "keys_sha256"} <= cols


def test_weak_passwords_are_refused():
    c = _client()
    for pw, name in (("password123", "weak_a"), ("12345678", "weak_b"), ("aaaaaaaa", "weak_c"),
                     ("weak_d2024", "weak_d"), ("qwertyui", "weak_e")):
        r = c.post("/api/auth/register", json={"username": name, "password": pw})
        assert r.status_code == 400, (pw, r.text)
    assert c.post("/api/auth/register", json={"username": "weak_ok", "password": "con-meo-xanh-7"}).status_code == 200


def test_recovery_code_resets_password_once():
    c = _client()
    r = c.post("/api/auth/register", json={"username": "khoiphuc1", "password": "mat-khau-dai-1"})
    code = r.json()["recovery_code"]
    assert len(code) == 24 and r.json()["has_recovery"]
    assert c.get("/api/auth/me").json()["user"]["recovery_code"] is None  # chỉ hiện một lần

    other = _client()
    bad = other.post("/api/auth/recover", json={"username": "khoiphuc1", "code": "AAAA-AAAA-AAAA-AAAA-AAAA",
                                                "new": "mat-khau-moi-22"})
    assert bad.status_code == 401
    # Gõ thường, thiếu gạch vẫn được.
    ok = other.post("/api/auth/recover", json={"username": "KhoiPhuc1", "code": code.lower().replace("-", " "),
                                               "new": "mat-khau-moi-22"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["recovery_code"] != code
    assert c.get("/api/auth/me").json()["user"] is None  # thiết bị cũ bị đăng xuất
    assert other.post("/api/auth/recover", json={"username": "khoiphuc1", "code": code,
                                                 "new": "mat-khau-moi-33"}).status_code == 401  # mã cũ hết hiệu lực
    assert _client().post("/api/auth/login", json={"username": "khoiphuc1", "password": "mat-khau-moi-22"}).status_code == 200

    new = other.post("/api/auth/recovery-code", json={"password": "mat-khau-moi-22"})
    assert new.status_code == 200 and new.json()["recovery_code"]
    assert other.post("/api/auth/recovery-code", json={"password": "sai"}).status_code == 401


def test_activity_log_and_db_lockout(monkeypatch):
    from app import accounts
    from app.config import settings
    monkeypatch.setattr(accounts, "_ip_limiter", accounts.RateLimiter(1000))
    monkeypatch.setattr(accounts, "_name_limiter", accounts.RateLimiter(1000))
    object.__setattr__(settings, "lockout_fails_per_ip", 3)
    try:
        c = _client()
        c.post("/api/auth/register", json={"username": "nhatky1", "password": "mat-khau-dai-1"})
        g = _client()
        for _ in range(3):
            assert g.post("/api/auth/login", json={"username": "nhatky1", "password": "sai-mat-khau"}).status_code == 401
        # Đủ số lần sai: bị khoá kể cả khi nhập đúng, và bộ đếm nằm trong cơ sở dữ liệu.
        assert g.post("/api/auth/login", json={"username": "nhatky1", "password": "mat-khau-dai-1"}).status_code == 429
        events = [e["event"] for e in c.get("/api/auth/activity").json()]
        assert events.count("login_fail") == 3 and "register" in events
        assert all("ip" in e and "label" in e for e in c.get("/api/auth/activity").json())
        assert _client().get("/api/auth/activity").status_code == 401
    finally:
        object.__setattr__(settings, "lockout_fails_per_ip", 10)


def test_totp_matches_rfc6238_vector():
    import base64
    from app import totp
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp.code_at(secret, 59 // 30) == "287082"          # RFC 6238, T = 59 giây
    assert totp.code_at(secret, 1111111109 // 30) == "081804"
    assert totp.verify(secret, "287 082", now=59) == 1
    assert totp.verify(secret, "287082", last_step=1, now=59) is None  # không dùng lại được


def test_two_factor_login_flow():
    import time
    from app import totp
    c = _client()
    r = c.post("/api/auth/register", json={"username": "hailop1", "password": "mat-khau-dai-1"})
    code = r.json()["recovery_code"]
    assert c.post("/api/auth/2fa/setup", json={"password": "sai"}).status_code == 401
    s = c.post("/api/auth/2fa/setup", json={"password": "mat-khau-dai-1"}).json()
    assert s["uri"].startswith("otpauth://totp/") and s["secret"] in s["uri"]
    assert c.get("/api/auth/me").json()["user"]["has_2fa"] is False  # chưa xác nhận thì chưa bật
    assert c.post("/api/auth/2fa/enable", json={"code": "000000"}).status_code in (400, 200)
    now = int(time.time() // 30)
    assert c.post("/api/auth/2fa/enable", json={"code": totp.code_at(s["secret"], now)}).status_code == 200
    assert c.get("/api/auth/me").json()["user"]["has_2fa"] is True

    g = _client()
    creds = {"username": "hailop1", "password": "mat-khau-dai-1"}
    assert g.post("/api/auth/login", json={**creds, "password": "sai-mat-khau"}).status_code == 401
    assert g.post("/api/auth/login", json=creds).status_code == 428
    assert g.post("/api/auth/login", json={**creds, "code": "123456"}).status_code in (401,)
    # Mã của bước vừa dùng lúc bật không dùng lại được; mã của bước kế tiếp thì được.
    assert g.post("/api/auth/login", json={**creds, "code": totp.code_at(s["secret"], now)}).status_code == 401
    ok = g.post("/api/auth/login", json={**creds, "code": totp.code_at(s["secret"], now + 1)})
    assert ok.status_code == 200 and ok.json()["has_2fa"] is True

    # Mất điện thoại: mã khôi phục đặt lại mật khẩu và tắt 2FA.
    h = _client()
    assert h.post("/api/auth/recover", json={"username": "hailop1", "code": code, "new": "mat-khau-moi-44"}).status_code == 200
    assert h.get("/api/auth/me").json()["user"]["has_2fa"] is False
    assert _client().post("/api/auth/login", json={"username": "hailop1", "password": "mat-khau-moi-44"}).status_code == 200


def test_pwned_password_is_refused(monkeypatch):
    import hashlib
    from app import passwords
    from app.config import settings

    class FakeResp:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n): return self.body

    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        leaked = hashlib.sha1(b"mat-khau-bi-lo-9").hexdigest().upper()
        return FakeResp(f"0000000000000000000000000000000000A:3\r\n{leaked[5:]}:4521\r\n".encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert passwords.pwned_count("mat-khau-bi-lo-9") == 4521
    assert seen["url"].endswith(hashlib.sha1(b"mat-khau-bi-lo-9").hexdigest().upper()[:5])  # chỉ gửi 5 ký tự
    assert passwords.pwned_count("mat-khau-chua-lo-9") == 0

    object.__setattr__(settings, "hibp_check", True)
    try:
        c = _client()
        r = c.post("/api/auth/register", json={"username": "lo_mk_1", "password": "mat-khau-bi-lo-9"})
        assert r.status_code == 400 and "4,521" in r.json()["detail"]
        assert c.post("/api/auth/register", json={"username": "lo_mk_1", "password": "mat-khau-chua-lo-9"}).status_code == 200
        # Dịch vụ ngoài sập thì vẫn đăng ký được.
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("mat mang")))
        assert c.post("/api/auth/logout").status_code == 200
        assert _client().post("/api/auth/register", json={"username": "lo_mk_2", "password": "mat-khau-bi-lo-9"}).status_code == 200
    finally:
        object.__setattr__(settings, "hibp_check", False)
