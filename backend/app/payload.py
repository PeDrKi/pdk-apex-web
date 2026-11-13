"""Đóng gói thông điệp thành chuỗi bit trước khi nhúng.

Định dạng "apexweb-v1" (byte):
    flags (1)                      bit0 = đã mã hoá bằng mật khẩu
                                   bit1 = nội dung là logo (xem logo.py)
                                   bit2 = nội dung là file: name_len (1) | tên UTF-8 | dữ liệu
    [salt (16) | nonce (12)]       chỉ khi mã hoá
    body                           UTF-8 (hoặc ciphertext AES-256-GCM + tag 16 byte)
    crc32 (4, big-endian)          tính trên toàn bộ phần phía trước

CRC32 giúp trang web báo được "thông điệp nguyên vẹn hay đã hỏng" sau khi
trích xuất. Khi mã hoá, khoá AES được dẫn xuất từ mật khẩu bằng PBKDF2-SHA256.
"""
from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass

import numpy as np
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

FORMAT = "apexweb-v1"
FLAG_ENCRYPTED = 0x01
FLAG_LOGO = 0x02
FLAG_FILE = 0x04
KINDS = {"text": 0, "logo": FLAG_LOGO, "file": FLAG_FILE}
SALT_LEN = 16
NONCE_LEN = 12
TAG_LEN = 16
KDF_ITERATIONS = 600_000  # theo khuyến nghị OWASP cho PBKDF2-HMAC-SHA256

PLAIN_OVERHEAD = 1 + 4
ENCRYPTED_OVERHEAD = PLAIN_OVERHEAD + SALT_LEN + NONCE_LEN + TAG_LEN


class PayloadError(ValueError):
    pass


class WrongPassword(PayloadError):
    pass


@dataclass
class Decoded:
    body: bytes
    integrity_ok: bool
    encrypted: bool
    kind: str

    @property
    def is_logo(self) -> bool:
        return self.kind == "logo"

    @property
    def message(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def overhead_bytes(encrypted: bool) -> int:
    return ENCRYPTED_OVERHEAD if encrypted else PLAIN_OVERHEAD


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=KDF_ITERATIONS)
    return kdf.derive(password.encode("utf-8"))


def encode(message: str, password: str | None = None) -> bytes:
    return encode_bytes(message.encode("utf-8"), password)


def pack_file(name: str, data: bytes) -> bytes:
    raw = name.encode("utf-8")[:255]
    # cắt theo byte có thể làm đứt ký tự cuối: bỏ phần đứt
    raw = raw.decode("utf-8", errors="ignore").encode("utf-8")
    return bytes([len(raw)]) + raw + data


def unpack_file(body: bytes) -> tuple[str, bytes]:
    if not body or len(body) < 1 + body[0]:
        raise PayloadError("Dữ liệu file bị hỏng.")
    n = body[0]
    return body[1:1 + n].decode("utf-8", errors="replace"), body[1 + n:]


def encode_bytes(body: bytes, password: str | None = None, *, is_logo: bool = False,
                 kind: str | None = None) -> bytes:
    kind = KINDS[kind or ("logo" if is_logo else "text")]
    if password:
        salt, nonce = os.urandom(SALT_LEN), os.urandom(NONCE_LEN)
        ct = AESGCM(_derive_key(password, salt)).encrypt(nonce, body, None)
        head = bytes([FLAG_ENCRYPTED | kind]) + salt + nonce + ct
    else:
        head = bytes([kind]) + body
    return head + struct.pack(">I", zlib.crc32(head) & 0xFFFFFFFF)


def decode(data: bytes, password: str | None = None, *, kind: str | None = None,
           encrypted: bool | None = None) -> Decoded:
    """kind/encrypted: giá trị lưu trong file khoá (đáng tin hơn byte flags,
    vốn có thể bị lật bit khi ảnh bị biến đổi). None = đọc từ flags."""
    if len(data) < PLAIN_OVERHEAD:
        raise PayloadError("Dữ liệu trích xuất quá ngắn.")
    head, crc = data[:-4], struct.unpack(">I", data[-4:])[0]
    integrity_ok = (zlib.crc32(head) & 0xFFFFFFFF) == crc
    flags = head[0]
    if encrypted is None:
        encrypted = bool(flags & FLAG_ENCRYPTED)
    if kind is None:
        kind = "logo" if flags & FLAG_LOGO else "file" if flags & FLAG_FILE else "text"

    if not encrypted:
        return Decoded(head[1:], integrity_ok, False, kind)

    if not password:
        raise WrongPassword("Thông điệp đã được mã hoá — cần nhập mật khẩu.")
    if len(head) < 1 + SALT_LEN + NONCE_LEN + TAG_LEN:
        raise PayloadError("Dữ liệu mã hoá bị hỏng (quá ngắn).")
    salt = head[1:1 + SALT_LEN]
    nonce = head[1 + SALT_LEN:1 + SALT_LEN + NONCE_LEN]
    ct = head[1 + SALT_LEN + NONCE_LEN:]
    try:
        body = AESGCM(_derive_key(password, salt)).decrypt(nonce, ct, None)
    except InvalidTag:
        if not integrity_ok:
            raise PayloadError("Ảnh đã bị biến đổi quá mạnh, dữ liệu mã hoá bị hỏng "
                               "nên không giải mã được.")
        raise WrongPassword("Sai mật khẩu.")
    return Decoded(body, integrity_ok, True, kind)


def bytes_to_bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def bits_to_bytes(bits: np.ndarray) -> bytes:
    n = (bits.size // 8) * 8
    return np.packbits(bits[:n].astype(np.uint8)).tobytes()
