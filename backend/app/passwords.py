"""Chặn mật khẩu quá yếu. Danh sách ngắn các mật khẩu phổ biến nhất (từ 8 ký tự trở lên),
không thay được việc kiểm tra với kho mật khẩu đã lộ nhưng chặn được các lựa chọn tệ nhất."""
from __future__ import annotations

import re

COMMON = frozenset("""
12345678 123456789 1234567890 12345678910 123123123 1234512345 11111111 00000000 88888888 99999999
87654321 987654321 0987654321 12341234 11223344 1q2w3e4r 1q2w3e4r5t 1qaz2wsx 1qazxsw2 qwertyui
qwertyuiop qwerty123 qwerty12 qwerty1234 asdfghjk asdfghjkl zxcvbnm1 zxcvbnm123 q1w2e3r4 q1w2e3r4t5
password password1 password12 password123 password1234 passw0rd p@ssw0rd p@ssword pass1234 pass12345
matkhau123 matkhau1 matkhau12 matkhau1234 khongbiet khongco123 anhyeuem anhyeuem123 emyeuanh iloveyou
iloveyou1 iloveyou123 yeuemnhieu toilatoi toilaai123 vietnam123 vietnam1 hanoi123 saigon123 abc12345
abcd1234 abcdefgh abcdefg1 abc123456 a1b2c3d4 aa123456 a1234567 a12345678 admin123 admin1234
administrator welcome1 welcome123 letmein1 letmein123 sunshine princess football baseball superman
starwars computer internet trustno1 whatever michelle jennifer changeme changeme123 secret123
test1234 testtest demo1234 user1234 guest1234 master123 dragon123 monkey123 samsung123 iphone123
google123 facebook facebook123 minecraft pokemon123 naruto123 liverpool arsenal123 chelsea123
""".split())

_KEYBOARD = ("qwertyuiopasdfghjklzxcvbnm", "01234567890", "abcdefghijklmnopqrstuvwxyz")


def weakness(password: str, username: str = "") -> str | None:
    """Trả về lý do (tiếng Việt) nếu mật khẩu quá yếu, None nếu chấp nhận được."""
    low = password.lower()
    if low in COMMON:
        return "Mật khẩu này nằm trong danh sách mật khẩu phổ biến, rất dễ bị dò. Hãy chọn mật khẩu khác."
    if len(set(password)) <= 2:
        return "Mật khẩu chỉ lặp lại một hai ký tự. Hãy chọn mật khẩu khác."
    if password.isdigit() and len(password) < 12:
        return "Mật khẩu chỉ gồm chữ số thì phải dài ít nhất 12 ký tự."
    name = username.lower()
    if len(name) >= 3 and re.sub(r"[\W_\d]+$", "", low) == name:
        return "Mật khẩu không được là tên đăng nhập thêm vài chữ số."
    for row in _KEYBOARD:
        if low in row or low in row[::-1]:
            return "Mật khẩu là một dãy phím liền nhau, rất dễ bị dò. Hãy chọn mật khẩu khác."
    return None


# ---------------------------------------------------------------- kho mật khẩu đã lộ

HIBP_URL = "https://api.pwnedpasswords.com/range/"


def pwned_count(password: str, timeout: float = 3.0) -> int:
    """Số lần mật khẩu này xuất hiện trong các vụ lộ dữ liệu, theo Have I Been Pwned.

    Dùng k-anonymity: chỉ gửi 5 ký tự đầu của mã băm SHA-1, nhận về mọi mã băm cùng tiền tố rồi tự
    so ở đây, nên dịch vụ đó không biết mật khẩu nào được hỏi. Không gọi được thì trả 0 (bỏ qua),
    để việc đăng ký không phụ thuộc vào một dịch vụ bên ngoài.
    """
    import hashlib
    import urllib.request

    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    req = urllib.request.Request(HIBP_URL + prefix, headers={"Add-Padding": "true", "User-Agent": "password-check"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(2_000_000).decode("ascii", "ignore")
    except Exception:
        return 0
    for line in body.splitlines():
        tail, _, count = line.partition(":")
        if tail.strip() == suffix:
            try:
                return int(count)
            except ValueError:
                return 0
    return 0
