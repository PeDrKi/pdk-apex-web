"""Cấu hình đọc từ biến môi trường (xem .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _list(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    # Giới hạn dung lượng file tải lên (MB) và số điểm ảnh tối đa (chống quá tải RAM/CPU).
    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 20))
    max_pixels: int = field(default_factory=lambda: _int("MAX_PIXELS", 25_000_000))
    max_redundancy: int = field(default_factory=lambda: _int("MAX_REDUNDANCY", 50))
    # Danh sách origin được gọi API (chỉ cần khi frontend chạy ở domain khác backend).
    # Số request POST tối đa mỗi phút cho mỗi IP (0 = tắt giới hạn).
    rate_limit_per_min: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MIN", 60))
    # Bật trang tài liệu API /api/docs (chỉ nên bật khi phát triển).
    enable_docs: bool = field(default_factory=lambda: os.environ.get("ENABLE_DOCS", "") == "1")
    max_message_chars: int = field(default_factory=lambda: _int("MAX_MESSAGE_CHARS", 100_000))
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS", ""))
    # Thư mục frontend đã build. Để trống = tự dùng ../frontend/dist nếu có.
    static_dir: str = field(default_factory=lambda: os.environ.get("STATIC_DIR", ""))
    # Số việc nặng (nhúng, trích xuất, tấn công) chạy cùng lúc; yêu cầu dư ra sẽ xếp hàng.
    max_heavy_jobs: int = field(default_factory=lambda: max(1, _int("MAX_HEAVY_JOBS", min(4, os.cpu_count() or 2))))
    # --- Tài khoản và lịch sử ---
    # Nơi chứa cơ sở dữ liệu SQLite và file của người dùng. Để trống = backend/data.
    data_dir: str = field(default_factory=lambda: os.environ.get("DATA_DIR", ""))
    allow_registration: bool = field(default_factory=lambda: os.environ.get("ALLOW_REGISTRATION", "1") != "0")
    session_days: int = field(default_factory=lambda: _int("SESSION_DAYS", 30))
    max_items_per_user: int = field(default_factory=lambda: _int("MAX_ITEMS_PER_USER", 200))
    max_storage_mb_per_user: int = field(default_factory=lambda: _int("MAX_STORAGE_MB_PER_USER", 500))
    # Số lần thử đăng nhập/đăng ký mỗi phút cho mỗi IP và mỗi tên đăng nhập (0 = tắt).
    login_attempts_per_min: int = field(default_factory=lambda: _int("LOGIN_ATTEMPTS_PER_MIN", 10))
    # Mỗi lần băm scrypt tốn khoảng 32 MB: chỉ cho vài lần chạy cùng lúc để máy ít RAM không sập.
    max_password_jobs: int = field(default_factory=lambda: max(1, _int("MAX_PASSWORD_JOBS", 2)))
    # Khoá tạm khi đăng nhập sai nhiều lần (đếm trong cơ sở dữ liệu, không mất khi khởi động lại).
    lockout_window_min: int = field(default_factory=lambda: _int("LOCKOUT_WINDOW_MIN", 15))
    lockout_fails_per_ip: int = field(default_factory=lambda: _int("LOCKOUT_FAILS_PER_IP", 10))
    lockout_fails_per_user: int = field(default_factory=lambda: _int("LOCKOUT_FAILS_PER_USER", 50))
    # Kiểm tra mật khẩu với kho mật khẩu đã lộ (Have I Been Pwned). Chỉ 5 ký tự đầu của mã băm SHA-1 rời máy chủ.
    hibp_check: bool = field(default_factory=lambda: os.getenv("HIBP_CHECK", "1").strip() not in ("0", "false", "no"))
    audit_keep_days: int = field(default_factory=lambda: _int("AUDIT_KEEP_DAYS", 90))
    # Postgres (ví dụ của Supabase). Để trống = SQLite trong DATA_DIR.
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))
    # Supabase Storage cho file lịch sử. Để trống = lưu trong DATA_DIR/files.
    supabase_url: str = field(default_factory=lambda: os.environ.get("SUPABASE_URL", ""))
    supabase_service_key: str = field(default_factory=lambda: os.environ.get("SUPABASE_SERVICE_KEY", ""))
    supabase_bucket: str = field(default_factory=lambda: os.environ.get("SUPABASE_BUCKET", "apex-history"))
    # Địa chỉ giao diện được phép gửi yêu cầu thay đổi dữ liệu khi nó khác domain backend
    # (ví dụ https://ten-web.vercel.app khi Vercel chuyển tiếp /api sang Render).
    trusted_origins: list[str] = field(default_factory=lambda: _list("TRUSTED_ORIGINS", ""))
    # Header chứa IP thật của người dùng khi chạy sau proxy (ví dụ x-forwarded-for).
    # Để trống = dùng IP kết nối trực tiếp. CHỈ đặt khi thực sự có proxy đứng trước.
    client_ip_header: str = field(default_factory=lambda: os.environ.get("CLIENT_IP_HEADER", "").strip().lower())
    # Cookie phiên chỉ gửi qua HTTPS: "1" luôn bật, "0" luôn tắt, để trống = tự nhận theo request.
    cookie_secure: str = field(default_factory=lambda: os.environ.get("COOKIE_SECURE", ""))

    @property
    def max_request_bytes(self) -> int:
        # ảnh + logo/khoá + phần chữ của form
        return 2 * self.max_upload_bytes + 1024 * 1024

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
