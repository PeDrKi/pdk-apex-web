# Đánh giá bảo mật PDK APEX Web

Ngày rà soát: 13/11/2026. Phạm vi: `backend/app`, `frontend/src`, cách deploy. Không gồm thuật toán bên trong apexmark.

## Kết quả tóm tắt

| # | Vấn đề | Mức độ | Trạng thái |
|---|---|---|---|
| 1 | File khoá `.npz` giả mạo làm máy chủ lỗi (chỉ số ngoài phạm vi, chia cho 0, cấp phát bộ nhớ lớn) | Cao | Đã vá |
| 2 | "Zip bomb" trong file khoá: file vài KB giải nén ra hàng GB | Cao | Đã vá |
| 3 | Không giới hạn kích thước request: gửi body rất lớn làm đầy đĩa tạm | Cao | Đã vá |
| 4 | Không giới hạn tần suất: mỗi request tốn CPU (ACO, PBKDF2, dò xoay) nên dễ bị làm quá tải | Trung bình | Đã vá |
| 5 | Logo tải lên không bị kiểm tra số điểm ảnh (bom giải nén ảnh) | Trung bình | Đã vá |
| 6 | Thiếu header bảo mật (CSP, chống nhúng iframe, nosniff, HSTS) | Trung bình | Đã vá |
| 7 | PBKDF2 chỉ 200.000 vòng, thấp hơn khuyến nghị OWASP | Thấp | Đã vá (600.000) |
| 8 | Trang `/api/docs` mở công khai và tải script từ CDN ngoài | Thấp | Đã vá (tắt mặc định) |
| 9 | Tham số `seed`, độ dài mật khẩu/thông điệp không bị chặn, gây lỗi 500 | Thấp | Đã vá |
| 10 | Pillow mở mọi định dạng ảnh, kể cả bộ giải mã ít dùng | Thấp | Đã vá (danh sách cho phép) |
| 11 | Mật khẩu và nội dung được gửi lên máy chủ để xử lý | Thiết kế | Đã vá: mã hoá tại trình duyệt (Web Crypto). Vẫn cần HTTPS, vì Web Crypto chỉ chạy trên HTTPS/localhost |
| 12 | Không mật khẩu thì nội dung không được mã hoá; CRC32 không chống giả mạo | Thiết kế | Đã cảnh báo trên giao diện |
| 13 | File khoá chứa ảnh thu nhỏ của ảnh gốc | Thiết kế | Đã ghi chú, có thể tắt |
| 14 | Giới hạn tần suất lưu trong bộ nhớ từng tiến trình | Còn lại | Xem mục "Việc nên làm khi deploy" |

## Chi tiết các bản vá

1. **Kiểm tra file khoá** (`security.validate_keys`): mọi trường đều được kiểm tra kiểu dữ liệu, kích thước và phạm vi
   trước khi đưa vào apexmark: toạ độ không âm, delta hữu hạn và dương, hoán vị hợp lệ, chỉ số bin trong phạm vi,
   kích thước gốc không vượt `MAX_PIXELS`. `np.load` luôn dùng `allow_pickle=False` nên không thể chạy mã qua pickle.
   Có 14 ca thử file khoá bị sửa, tất cả trả về lỗi 400 thay vì làm sập.
2. **Zip bomb** (`security.check_npz_size`): đọc mục lục zip, từ chối nếu tổng dung lượng giải nén vượt 64 MB hoặc quá 32 mục.
3. **Giới hạn request** (`SecurityMiddleware`): chặn theo `Content-Length` và đếm byte thực nhận, trước khi dữ liệu
   được ghi ra đĩa tạm. Mặc định 2 × `MAX_UPLOAD_MB` + 1 MB.
4. **Giới hạn tần suất**: 60 request POST mỗi phút cho mỗi IP (`RATE_LIMIT_PER_MIN`), trả về 429.
5. **Ảnh và logo**: kiểm tra số điểm ảnh trước khi giải nén, chỉ nhận PNG, JPEG, WEBP, BMP, TIFF, GIF.
6. **Header**: `Content-Security-Policy` (chỉ tải tài nguyên cùng nguồn, cấm iframe), `X-Frame-Options: DENY`,
   `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, `Cache-Control: no-store`
   cho API, và `Strict-Transport-Security` khi chạy qua HTTPS.

## Những điểm đã kiểm tra và ổn

- **XSS:** React tự thoát ký tự, nội dung đọc ra hiển thị dạng văn bản; không dùng `dangerouslySetInnerHTML`. CSP cấm script ngoài.
- **CSRF:** API không dùng cookie hay phiên đăng nhập nên không có gì để giả mạo.
- **CORS:** mặc định đóng, chỉ mở cho domain khai báo trong `CORS_ORIGINS`.
- **Path traversal:** đường dẫn file tĩnh được chuẩn hoá và kiểm tra nằm trong thư mục `dist`.
- **Mã hoá:** AES-256-GCM với nonce 96 bit và salt 128 bit ngẫu nhiên cho mỗi lần giấu; sai mật khẩu hay sửa dữ liệu đều bị phát hiện.
- **Quyền riêng tư:** với khách, máy chủ không ghi ảnh, khoá, mật khẩu hay nội dung ra đĩa hoặc log. Ảnh xuất ra đã loại EXIF. Với người đã đăng nhập, xem mục Tài khoản và lịch sử bên dưới.
- **Thư viện:** `npm audit` báo 0 lỗ hổng; `requirements.txt` yêu cầu các phiên bản đã vá lỗi đã biết.

## Tài khoản và lịch sử

Mã nguồn: `backend/app/accounts.py`, `backend/app/db.py`; test: `backend/tests/test_accounts.py`.

- **Mật khẩu tài khoản** băm bằng scrypt (N=2^15, r=8, p=1, muối 128 bit riêng cho mỗi người). Không lưu dạng gốc.
- **Phiên đăng nhập** là token ngẫu nhiên 256 bit đặt trong cookie `HttpOnly`, `SameSite=Strict`, thêm `Secure` khi
  chạy HTTPS. JavaScript không đọc được cookie. Cơ sở dữ liệu chỉ giữ SHA-256 của token, nên lộ file `app.db` cũng
  không dùng lại được phiên. Đăng xuất xoá phiên ở máy chủ; đổi mật khẩu đăng xuất mọi thiết bị khác.
- **Chống CSRF:** `SameSite=Strict` cộng với kiểm tra header `Origin` trên mọi yêu cầu thay đổi dữ liệu.
- **Chống dò mật khẩu:** tối đa 10 lần thử mỗi phút cho mỗi IP và mỗi tên đăng nhập; thông báo lỗi và thời gian phản
  hồi giống nhau dù tên có tồn tại hay không.
- **Phân quyền:** mọi truy vấn lịch sử đều lọc theo người dùng; mục của người khác trả về 404. Mã mục là 96 bit
  ngẫu nhiên và được kiểm tra định dạng trước khi ghép thành đường dẫn file.
- **File lưu lên** được kiểm tra như khi đọc tin (ảnh phải là PNG hợp lệ, file khoá qua `validate_keys`); loại nội
  dung, kích thước và độ dự phòng do máy chủ tự rút ra từ file chứ không tin số liệu trình duyệt gửi.
- **Giới hạn:** 200 mục và 500 MB mỗi tài khoản (chỉnh được).
- **Những gì được lưu:** ảnh đã giấu tin, file khoá, ảnh thu nhỏ và tên ảnh. **Không lưu** ảnh gốc, nội dung đã giấu
  ở dạng rõ, và mật khẩu nội dung. Người dùng tắt được việc tự lưu, xoá từng mục, xoá hết, hoặc xoá tài khoản.

Điểm cần biết:

1. Ảnh và khoá lưu cùng một chỗ, nên **nội dung không đặt mật khẩu thì người quản trị máy chủ đọc được**. Nội dung
   có mật khẩu thì máy chủ không đọc được, vì việc mã hoá diễn ra trong trình duyệt.
2. Không thu email nên không có chức năng lấy lại mật khẩu và không xác minh người đăng ký. Nếu mở cho công chúng,
   nên thêm CAPTCHA hoặc đặt `ALLOW_REGISTRATION=0` sau khi tạo đủ tài khoản.
3. File trong `backend/data` không được mã hoá trên đĩa. Hãy giới hạn quyền đọc thư mục này và sao lưu định kỳ.
4. Bộ đếm số lần thử đăng nhập nằm trong bộ nhớ của từng tiến trình, giống bộ giới hạn tần suất chung.
5. Khi triển khai theo DEPLOY.md, file lịch sử nằm trong bucket **riêng tư** của Supabase Storage và chỉ backend
   (giữ khoá service_role) đọc được; người dùng tải file qua API đã kiểm tra quyền sở hữu. Khoá file do máy chủ tự
   tạo và được kiểm tra định dạng (`backend/app/storage.py`). Khoá service_role chỉ nằm trong biến môi trường của
   Render, không có trong mã nguồn.
6. Giới hạn tần suất áp cho mọi yêu cầu ghi, xoá và tải file lịch sử. Sau proxy, IP lấy từ header đặt trong
   `CLIENT_IP_HEADER`; ai gọi thẳng vào backend bỏ qua proxy có thể giả header này.

## Việc nên làm khi deploy

1. **Bắt buộc dùng HTTPS** (Nginx/Caddy/Cloudflare phía trước), vì mật khẩu và nội dung đi qua mạng tới máy chủ.
2. Chạy uvicorn sau reverse proxy và đặt thêm giới hạn kích thước body, giới hạn tần suất ở proxy. Bộ giới hạn trong
   ứng dụng tính riêng cho từng worker và theo IP mà uvicorn nhìn thấy.
3. Chạy dịch vụ bằng tài khoản không có quyền quản trị.
4. Cập nhật thư viện định kỳ (`pip list --outdated`, `npm audit`).
5. Khi có mật khẩu, trình duyệt tự mã hoá (`frontend/src/lib/payload.ts`) và gửi dữ liệu đã đóng gói qua trường `payload`; lúc đọc, máy chủ trả dữ liệu thô (`raw=true`) để trình duyệt giải mã. Nếu trang chạy qua HTTP thường, giao diện báo rõ và chuyển sang nhờ máy chủ mã hoá.
6. Tên file nhúng trong ảnh là dữ liệu không tin cậy: giao diện loại bỏ ký tự đường dẫn trước khi cho tải về.
7. Giới hạn tần suất mặc định là 60 request POST mỗi phút cho mỗi IP.
