"""Bộ lưu file: thư mục cục bộ và client Supabase Storage (gọi vào máy chủ giả lập)."""
import pytest

from app.storage import LocalStorage, StorageError, SupabaseStorage
from tests import fake_supabase

KEY = "7/" + "ab" * 12 + ".png"


@pytest.fixture
def fake():
    srv = fake_supabase.start(0, "bi-mat")
    yield srv
    srv.shutdown()


def _url(srv):
    return f"http://127.0.0.1:{srv.server_address[1]}"


def test_supabase_roundtrip_and_bucket_autocreate(fake):
    st = SupabaseStorage(_url(fake), "bi-mat", "apex-history")
    assert st.get(KEY) is None
    st.put(KEY, b"\x89PNG data", "image/png")
    assert fake.buckets["apex-history"]["public"] is False  # bucket riêng tư
    assert st.get(KEY) == b"\x89PNG data"
    st.put(KEY, b"moi", "image/png")  # ghi đè được
    assert st.get(KEY) == b"moi"
    st.delete([KEY])
    assert st.get(KEY) is None
    st.delete([KEY])  # xoá thứ không còn: không lỗi

    # Tiến trình khác khởi động lại: bucket đã có sẵn cũng không lỗi.
    st2 = SupabaseStorage(_url(fake), "bi-mat", "apex-history")
    st2.put(KEY, b"x", "image/png")
    assert st2.get(KEY) == b"x"


def test_supabase_wrong_key_and_unreachable(fake):
    with pytest.raises(StorageError):
        SupabaseStorage(_url(fake), "sai-khoa", "b").put(KEY, b"x", "image/png")
    with pytest.raises(StorageError):
        SupabaseStorage("http://127.0.0.1:9", "k", "b", timeout=2).get(KEY)


@pytest.mark.parametrize("bad", ["../app.db", "7/../../x.png", "7/" + "ab" * 12 + ".exe", "abc/" + "ab" * 12 + ".png"])
def test_keys_are_validated(tmp_path, bad):
    with pytest.raises(StorageError):
        LocalStorage(tmp_path).put(bad, b"x", "image/png")
    with pytest.raises(StorageError):
        SupabaseStorage("http://127.0.0.1:9", "k", "b").get(bad)


def test_client_ip_header(monkeypatch):
    from app import security
    scope = {"client": ("10.0.0.1", 1), "headers": [(b"x-forwarded-for", b"203.0.113.5, 10.0.0.9")]}
    assert security.client_ip(scope) == "10.0.0.1"  # mặc định không tin header
    monkeypatch.setattr(security, "settings", type("S", (), {"client_ip_header": "x-forwarded-for"})())
    assert security.client_ip(scope) == "203.0.113.5"


def test_history_downloads_are_rate_limited(monkeypatch, client):
    from app import security
    monkeypatch.setattr(security, "rate_limiter", security.RateLimiter(2))
    codes = [client.get("/api/history").status_code for _ in range(3)]
    assert codes == [401, 401, 429]
    assert client.get("/api/health").status_code == 200  # đọc thông thường không bị tính


def test_spoofed_forwarded_ip_cannot_bypass_rate_limit(monkeypatch, client):
    """Gọi thẳng vào máy chủ với x-forwarded-for giả, đổi IP mỗi lần: vẫn bị chặn theo IP kết nối thật."""
    from app import security
    monkeypatch.setattr(security, "settings", type("S", (), {"client_ip_header": "x-forwarded-for",
                                                          "max_request_bytes": 10**8})())
    monkeypatch.setattr(security, "rate_limiter", security.RateLimiter(2))
    monkeypatch.setattr(security, "conn_rate_limiter", security.RateLimiter(5))
    codes = [client.get("/api/history", headers={"x-forwarded-for": f"198.51.100.{i}, 203.0.113.7"}).status_code
             for i in range(8)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429] * 3
    scope = {"client": ("10.0.0.1", 1), "headers": [(b"x-forwarded-for", b"1.2.3.4, 203.0.113.7")]}
    assert security.client_ip(scope) == "1.2.3.4" and security.conn_ip(scope) == "203.0.113.7"
