# PDK APEX Web

Web giấu thông điệp vào ảnh (steganography / watermark), dựa trên thư viện **apexmark 1.0.0**
(ACO + Adaptive Block-Mean QIM + N-GDC, bền vững với nén).

- **Frontend:** React 18 + Vite 6 + TypeScript (`frontend/`)
- **Backend:** Python FastAPI bọc apexmark (`backend/`). apexmark được đặt sẵn trong `backend/apexmark/`.
- **Deploy:** không cần Docker. Backend phục vụ luôn frontend đã build (một server), hoặc tách riêng.

## Tính năng

- Giấu thông điệp UTF-8 (tiếng Việt, emoji…) vào ảnh PNG/JPEG/WEBP/BMP, xuất ảnh PNG + file khoá `.npz`.
- Giấu **logo** vào ảnh: đen trắng (1 bit/điểm ảnh) hoặc xám 256 mức, tự thu nhỏ cho vừa dung lượng, nền trong suốt được coi là nền.
- **Thử tấn công:** chọn và ghép tối đa 6 trong 20 phép (nén JPEG, nhiễu, lọc, chỉnh màu, hình học), chỉnh mức độ, rồi đọc lại nội dung từ ảnh đã bị tấn công. Có nút quét tất cả phép và bảng kết quả.
- **So sánh:** xem chính xác điểm ảnh nào đã đổi (lớp phủ vị trí, bản đồ nhiệt, trượt trước/sau, phóng to ×8).
- Mã hoá tuỳ chọn bằng mật khẩu (AES-256-GCM, PBKDF2-SHA256 600.000 vòng), thực hiện **ngay trong trình duyệt** bằng Web Crypto: mật khẩu và nội dung gốc không được gửi lên máy chủ (cần HTTPS hoặc localhost; nếu không có thì máy chủ mã hoá thay).
- Giấu **file** nhỏ bất kỳ (JSON, mã serial…), giữ nguyên tên file.
- Chọn **kích thước logo** (32 đến 96 px hoặc tối đa) và tự dùng hết chỗ trống của ảnh để lặp lại nội dung.
- Tải ảnh và khoá trong **một file .zip**; thả lại file zip đó vào tab Đọc tin hoặc Thử tấn công để đọc.
- **Hàng loạt:** giấu tin vào tối đa 50 ảnh một lượt, mỗi ảnh một nội dung (`{ten}`, `{stt}` hoặc mỗi dòng một ảnh), tải về một gói zip kèm `danh_sach.csv`.
- **Căn chỉnh chính xác đến từng điểm ảnh** khi ảnh bị cắt/dịch, và bỏ phiếu chỉ trên phần ảnh còn lại (`app/align.py`).
- Kiểm tra toàn vẹn CRC32: lúc đọc báo thông điệp nguyên vẹn hay có thể đã sai bit.
- Ba mức bền vững (Dung lượng cao / Cân bằng / Bền vững) + tuỳ chọn nâng cao (độ dự phòng, delta, ACO).
- Hiển thị dung lượng tối đa theo ảnh, PSNR, so sánh ảnh trước/sau.
- Đọc tin từ ảnh đã bị nén JPEG, cắt mép, co giãn, xoay (dùng ảnh thu nhỏ lưu trong khoá + OpenCV).
- Đọc được cả khoá tạo bằng CLI `python -m apexmark embed --text`.
- **Tài khoản và lịch sử:** khách dùng được mọi chức năng, lịch sử chỉ nằm trong tab và mất khi đóng trang; máy chủ
  không lưu gì của khách. Đăng ký và đăng nhập thì ảnh đã giấu tin cùng file khoá được lưu lại (tab **Lịch sử**) để
  tải về hoặc mở lại ở tab Đọc tin. Ảnh gốc và mật khẩu nội dung không bao giờ được lưu.

## Bảo mật

Xem [SECURITY.md](SECURITY.md): kết quả rà soát, các lớp bảo vệ (kiểm tra file khoá, giới hạn request và tần suất,
header bảo mật) và việc cần làm khi deploy. **Khi đưa lên mạng phải chạy qua HTTPS.**

## Chạy khi phát triển (Windows / macOS / Linux)

Cần Python 3.10+ và Node.js 20+.

Trên Windows chỉ cần bấm đúp `run-dev.bat`. Hoặc chạy tay:

**Backend** (cửa sổ terminal 1):

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Tài liệu API (cần đặt biến `ENABLE_DOCS=1` trước khi chạy): http://localhost:8000/api/docs

**Frontend** (cửa sổ terminal 2):

```bash
cd frontend
npm install
npm run dev
```

Mở http://localhost:5173. Vite tự chuyển các request `/api` sang backend cổng 8000.

**Kiểm thử backend:** `cd backend && pytest -q`

## Deploy (không dùng Docker)

**Miễn phí, chạy hoàn toàn trên mạng:** GitHub + Supabase + Render + Vercel. Làm theo [DEPLOY.md](DEPLOY.md).

Tự chạy trên máy chủ riêng:

### Cách 1: một server duy nhất (đơn giản nhất)

Backend tự phục vụ luôn giao diện đã build trong `frontend/dist`, nên chỉ cần chạy một tiến trình:

- Windows: chạy `run-prod.bat`
- Linux/macOS (VPS): chạy `./run-prod.sh` (đổi cổng bằng biến `PORT`)

Script sẽ cài thư viện Python, build frontend rồi chạy uvicorn ở cổng 8000. Trên VPS nên đặt Nginx/Caddy phía
trước để có HTTPS, và dùng systemd (hoặc NSSM trên Windows) để tự khởi động lại.

Các nền tảng chạy Python trực tiếp (Render, Railway…) cũng dùng được:
build `pip install -r backend/requirements.txt && cd frontend && npm ci && npm run build`,
start `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

### Cách 2: tách frontend và backend

1. Frontend (Vercel/Netlify/Cloudflare Pages): thư mục gốc `frontend`, lệnh build `npm run build`, thư mục ra `dist`,
   đặt biến `VITE_API_BASE=https://api.ten-mien-cua-ban.com`.
2. Backend (VPS hoặc dịch vụ Python): thư mục `backend`, lệnh chạy như trên, đặt `CORS_ORIGINS=https://ten-mien-frontend.com`.

## Biến môi trường backend

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `MAX_UPLOAD_MB` | 20 | Dung lượng tối đa mỗi file tải lên |
| `MAX_PIXELS` | 25000000 | Số điểm ảnh tối đa mỗi ảnh (chống quá tải) |
| `MAX_REDUNDANCY` | 50 | Độ dự phòng tối đa cho phép |
| `RATE_LIMIT_PER_MIN` | 60 | Số request POST mỗi phút cho mỗi IP (0 = tắt) |
| `ENABLE_DOCS` | (trống) | Đặt `1` để bật `/api/docs` khi phát triển |
| `CORS_ORIGINS` | (trống) | Domain frontend, phân cách bằng dấu phẩy |
| `STATIC_DIR` | (trống) | Thư mục frontend đã build. Trống = tự dùng `../frontend/dist` nếu có |
| `MAX_HEAVY_JOBS` | số nhân CPU, tối đa 4 | Số việc nặng (giấu, đọc, tấn công) chạy cùng lúc; yêu cầu dư ra xếp hàng |
| `DATA_DIR` | (trống) | Nơi chứa `app.db` (SQLite) và file người dùng đã lưu. Trống = `backend/data` |
| `ALLOW_REGISTRATION` | 1 | Đặt `0` để khoá đăng ký tài khoản mới |
| `SESSION_DAYS` | 30 | Số ngày một phiên đăng nhập còn hiệu lực |
| `MAX_ITEMS_PER_USER` | 200 | Số mục lịch sử tối đa mỗi tài khoản |
| `MAX_STORAGE_MB_PER_USER` | 500 | Dung lượng lưu trữ tối đa mỗi tài khoản |
| `LOGIN_ATTEMPTS_PER_MIN` | 10 | Số lần thử đăng nhập/đăng ký mỗi phút cho mỗi IP và mỗi tên (0 = tắt) |
| `DATABASE_URL` | (trống) | Chuỗi kết nối Postgres (ví dụ Supabase Session pooler). Trống = SQLite |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | (trống) | Lưu file lịch sử trên Supabase Storage. Trống = thư mục `DATA_DIR/files` |
| `SUPABASE_BUCKET` | apex-history | Tên bucket (tự tạo, riêng tư) |
| `TRUSTED_ORIGINS` | (trống) | Địa chỉ giao diện khi khác domain backend, ví dụ trang Vercel |
| `CLIENT_IP_HEADER` | (trống) | Header chứa IP thật khi chạy sau proxy, ví dụ `x-forwarded-for`. Chỉ đặt khi có proxy |
| `COOKIE_SECURE` | (trống) | `1` = cookie phiên chỉ gửi qua HTTPS, `0` = tắt, trống = tự nhận theo request |

Tài khoản dùng SQLite có sẵn trong Python, không cần cài thêm gì. **Hãy sao lưu thư mục `backend/data`**: mất thư mục
này là mất toàn bộ tài khoản và lịch sử. Tài khoản chỉ dùng được khi frontend và backend chạy cùng một tên miền (Cách 1).

## API

| Method | Đường dẫn | Mô tả |
|---|---|---|
| GET | `/api/health` | Trạng thái, phiên bản apexmark, có OpenCV/Compressonator không |
| POST | `/api/capacity` | `image`, `redundancy` → kích thước, dung lượng, số byte tối đa |
| POST | `/api/embed` | `image`, `kind` (text/logo), `message` hoặc `logo` + `logo_mode`, `password?`, `redundancy`, `delta`, `store_thumbnail`, `use_aco` → ảnh PNG + khoá (base64), PSNR |
| GET | `/api/attacks` | Danh mục phép tấn công |
| POST | `/api/attack` | `image`, `steps` (JSON), `keys?`, `password?` → ảnh bị tấn công, tỉ lệ bit sai, nội dung đọc lại |
| POST | `/api/attack/battery` | `image`, `keys`, `level` → kết quả của tất cả phép |
| POST | `/api/compare` | `original`, `stego` → bản đồ nhiệt, lớp phủ, thống kê điểm ảnh thay đổi |
| POST | `/api/extract` | `image`, `keys`, `password?`, `resync`, `rotate_range`, `aggregate` → `kind`, thông điệp hoặc logo PNG (base64), `integrity_ok` |

| GET | `/api/auth/me` | Người đang đăng nhập (hoặc `null`) |
| POST | `/api/auth/register`, `/api/auth/login` | JSON `username`, `password` → đặt cookie phiên |
| POST | `/api/auth/logout`, `/api/auth/password`, `/api/auth/delete` | Đăng xuất, đổi mật khẩu, xoá tài khoản |
| GET | `/api/history` | Danh sách mục đã lưu và dung lượng đã dùng |
| POST | `/api/history` | `stego` (PNG), `keys`, `name`, `psnr?` → lưu một mục |
| GET | `/api/history/{id}/stego\|keys\|thumb` | Tải file của một mục |
| DELETE | `/api/history/{id}`, `/api/history` | Xoá một mục hoặc toàn bộ |

Các POST xử lý ảnh dùng `multipart/form-data`; các POST tài khoản dùng JSON.

## Định dạng dữ liệu nhúng (`apexweb-v1`)

`flags(1) [salt(16) nonce(12)] body crc32(4)`. Bit 0 của `flags` = đã mã hoá, bit 1 = body là logo
(`mode(1) cao(2) rộng(2)` + điểm ảnh). Loại nội dung và kích thước logo cũng được lưu trong khoá để đọc được cả khi ảnh bị lỗi bit. Khi mã hoá, `body` là
ciphertext AES-GCM kèm tag 16 byte. Khoá `.npz` có thêm trường `payload_format = "apexweb-v1"`.

## Cấu trúc

```
backend/
  app/main.py        API FastAPI + phục vụ frontend
  app/payload.py     đóng gói thông điệp, mã hoá, CRC
  app/security.py    middleware bảo mật, kiểm tra file khoá
  app/align.py       căn chỉnh chính xác + trích xuất có mặt nạ
  app/attacks.py     danh mục phép tấn công (bọc apexmark.attacks)
  app/compare.py     so sánh ảnh trước/sau
  app/logo.py        chuyển logo <-> bytes
  app/imaging.py     đọc/ghi ảnh, PSNR
  apexmark/          thư viện apexmark 1.0.0 (MIT)
  tests/             test API (pytest)
frontend/
  src/App.tsx        khung trang, tab
  src/api.ts         client gọi API
  src/lib/           payload (mã hoá Web Crypto), logo, zip, codec
  src/components/    EmbedPanel, ExtractPanel, BatchPanel, AttackPanel, ComparePanel, AboutPanel, Dropzone
run-dev.bat, run-prod.bat, run-prod.sh
```

## Ghi chú

- Tính năng BC7-aware của apexmark (cần AMD Compressonator) đang tắt trên web vì máy chủ thường không có công cụ này.
- Nén JPEG chất lượng thấp, chỉnh sửa mạnh hay chụp màn hình có thể làm hỏng thông điệp. Mức “Bền vững” chịu được
  JPEG ~85, cắt mép và nhiễu nhẹ trong thử nghiệm.
