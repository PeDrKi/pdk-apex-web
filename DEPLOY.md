# Triển khai miễn phí: GitHub + Supabase + Render + Vercel

Không cần máy của bạn bật, không cần Docker, không tốn phí. Mỗi dịch vụ giữ một vai trò:

```
Người dùng ──HTTPS──► Vercel (giao diện, tải nhanh từ CDN)
                         │  /api/* được Vercel chuyển tiếp
                         ▼
                      Render (backend FastAPI + apexmark)
                         │
                         ▼
                      Supabase (Postgres: tài khoản · Storage: ảnh và khoá đã lưu)

GitHub giữ mã nguồn. Đẩy mã mới lên GitHub là Render và Vercel tự triển khai lại.
```

Thời gian làm lần đầu: khoảng 30 phút. Làm đúng thứ tự dưới đây.

> Điều kiện gói miễn phí của các dịch vụ thay đổi theo thời gian. Hướng dẫn này viết ngày 13/11/2026;
> tên nút trên giao diện các trang có thể khác đôi chút.

## Cách nhanh: chạy file .bat

Trên Windows, bấm đúp **`deploy.bat`** ở thư mục gốc. Script đi lần lượt 4 bước bên dưới, tự làm những gì làm được
và mở đúng trang web ở những chỗ bạn phải bấm (đăng nhập, dán khoá):

| File | Việc |
|---|---|
| `deploy.bat` | Chạy cả 4 bước. Chạy lại được: bước nào xong rồi sẽ hỏi để bỏ qua |
| `deploy\1-github.bat` | Xoá file Docker cũ, tạo kho git, tạo repo (qua GitHub CLI nếu có) và đẩy mã lên |
| `deploy\2-supabase-render.bat` | Mở Supabase và trang tạo dịch vụ Render từ `render.yaml`, rồi chờ backend chạy |
| `deploy\3-vercel.bat` | Sửa địa chỉ Render trong `frontend/vercel.json`, đăng nhập và deploy giao diện qua Vercel CLI |
| `deploy\4-ket-noi.bat` | Đặt `TRUSTED_ORIGINS` trên Render (qua Render API key, hoặc chỉ chỗ làm tay), đặt `SITE_URL` trên GitHub, kiểm tra cuối |
| `cap-nhat-web.bat` | Về sau: commit, đẩy lên GitHub (Render tự build) và deploy lại Vercel |
| `deploy\trang-thai.bat` | Xem các địa chỉ đã deploy và kiểm tra web còn chạy không |

Cần có Git và Node.js; nếu thiếu, script đề nghị cài bằng `winget`. GitHub CLI là tuỳ chọn nhưng nên có.
Script không lưu mật khẩu hay khoá nào; `deploy\deploy-config.json` chỉ ghi các địa chỉ công khai.

Nếu script báo lỗi ở bước nào, làm tay bước đó theo hướng dẫn dưới đây rồi chạy lại `deploy.bat`.

---

## Bước 1. GitHub: đưa mã nguồn lên

1. Vào <https://github.com/new>, đặt tên repo (ví dụ `pdk-apex-web`), chọn **Private** nếu không muốn công khai mã,
   **không** tích thêm README hay .gitignore. Bấm **Create repository**.
2. Đưa mã lên repo:
   - Cách dễ nhất: nhờ Claude đẩy giúp (cần kết nối GitHub cho Claude).
   - Hoặc dùng GitHub Desktop: *File > Add local repository* chọn thư mục `pdk-apex-web`, rồi *Publish*.

Không đưa file `.env` hay thư mục `backend/data` lên GitHub (đã có sẵn trong `.gitignore`).

## Bước 2. Supabase: cơ sở dữ liệu và kho file

1. Vào <https://supabase.com>, đăng nhập bằng GitHub, bấm **New project**.
   - **Region:** Southeast Asia (Singapore), cùng vùng với Render ở bước 3 để nhanh hơn.
   - **Database password:** bấm *Generate*, rồi **chép lại mật khẩu này**, bước sau cần dùng.
2. Đợi dự án tạo xong (1 đến 2 phút), rồi lấy 3 giá trị sau và dán tạm vào Notepad:

| Giá trị | Lấy ở đâu | Dùng cho biến |
|---|---|---|
| Project URL, dạng `https://abcd1234.supabase.co` | *Project Settings > Data API* (hoặc *API*) | `SUPABASE_URL` |
| Khoá **service_role** (hoặc *secret key*) | *Project Settings > API Keys* | `SUPABASE_SERVICE_KEY` |
| Chuỗi kết nối **Session pooler** | Nút **Connect** ở đầu trang > *Connection string* > *Session pooler* | `DATABASE_URL` |

Lưu ý:
- Chuỗi kết nối có dạng `postgresql://postgres.abcd1234:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres`.
  Thay `[YOUR-PASSWORD]` bằng mật khẩu đã chép ở bước 1, bỏ cả dấu ngoặc vuông.
- Phải dùng **Session pooler**, không dùng *Direct connection*: kết nối trực tiếp chỉ có IPv6 và Render free không gọi được.
- Khoá **service_role** có toàn quyền với dự án. Chỉ dán vào Render, **không** đưa vào mã nguồn hay gửi cho ai.

Không cần tạo bảng hay bucket: backend tự tạo ở lần chạy đầu (bucket `apex-history`, chế độ riêng tư).

## Bước 3. Render: chạy backend

1. Vào <https://render.com>, đăng nhập bằng GitHub.
2. Bấm **New > Blueprint**, chọn repo `pdk-apex-web`. Render đọc file `render.yaml` và đề xuất dịch vụ `pdk-apex-api`.
3. Render hỏi giá trị cho các biến bí mật. Dán:
   - `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`: lấy từ bước 2.
   - `TRUSTED_ORIGINS`: tạm để trống, điền ở bước 5.
4. Bấm **Apply**. Lần build đầu mất khoảng 5 đến 10 phút (cài numpy, OpenCV…).
5. Khi xong, mở `https://pdk-apex-api.onrender.com/api/health?db_check=true`. Thấy `"status":"ok"` là backend đã
   chạy và nối được Supabase.

Nếu tên `pdk-apex-api` đã có người dùng, Render sẽ đặt một địa chỉ khác (ví dụ `pdk-apex-api-x1y2.onrender.com`).
Chép lại địa chỉ đó cho bước 4.

## Bước 4. Vercel: chạy giao diện

1. Nếu địa chỉ Render của bạn **khác** `https://pdk-apex-api.onrender.com`, sửa dòng `destination` trong
   `frontend/vercel.json` thành địa chỉ đúng, rồi đẩy thay đổi lên GitHub.
2. Vào <https://vercel.com>, đăng nhập bằng GitHub, bấm **Add New > Project**, chọn repo `pdk-apex-web`.
3. Ở **Root Directory** bấm *Edit* và chọn **`frontend`**. Vercel tự nhận ra Vite. Không cần biến môi trường nào.
4. Bấm **Deploy**. Khoảng 1 phút sau bạn có địa chỉ, ví dụ `https://pdk-apex-web.vercel.app`.

## Bước 5. Nối Vercel với Render

1. Trên Render: mở dịch vụ `pdk-apex-api` > **Environment**, sửa `TRUSTED_ORIGINS` thành địa chỉ Vercel ở bước 4
   (ví dụ `https://pdk-apex-web.vercel.app`, không có dấu `/` ở cuối). Bấm **Save**, Render tự khởi động lại.
2. Mở địa chỉ Vercel, thử: giấu tin, đăng ký tài khoản, giấu tin lần nữa, rồi vào tab **Lịch sử** xem mục đã lưu.

Thiếu bước này thì đăng nhập, đăng xuất và lưu lịch sử sẽ báo lỗi *"Yêu cầu không đến từ trang web này"*.

## Bước 6 (nên làm). Giữ Supabase không bị tạm dừng

Supabase tạm dừng dự án miễn phí nếu cả tuần không có ai dùng. Repo đã có sẵn
`.github/workflows/keepalive.yml`, gọi web mỗi ngày một lần để tránh việc này:

1. Trên GitHub, mở repo > **Settings > Secrets and variables > Actions > Variables > New repository variable**.
2. Tên `SITE_URL`, giá trị là địa chỉ Vercel (ví dụ `https://pdk-apex-web.vercel.app`).
3. Vào tab **Actions**, chọn *keepalive* > **Run workflow** để thử một lần.

GitHub tự tắt lịch chạy nếu repo không có thay đổi nào trong 60 ngày; khi đó vào tab Actions bật lại.
Nếu dự án Supabase đã bị tạm dừng, vào trang Supabase bấm **Restore project**.

---

## Những giới hạn cần biết

- **Render ngủ sau khoảng 15 phút không ai dùng.** Người đầu tiên vào sau đó thấy dòng *"Đang đánh thức máy
  chủ…"* và phải chờ khoảng một phút. Giao diện từ Vercel vẫn hiện ngay.
- **Render free có 512 MB RAM và CPU yếu.** Vì vậy `render.yaml` giới hạn ảnh ở khoảng 2,1 triệu điểm ảnh
  (ảnh Full HD 1920×1080) và 10 MB, mỗi lúc xử lý một ảnh. Giấu tin sẽ chậm hơn chạy trên máy tính, có thể mất
  vài chục giây với ảnh lớn.
- **Vercel chuyển tiếp `/api`** nên có giới hạn riêng về dung lượng và thời gian mỗi yêu cầu. Nếu ảnh lớn báo lỗi
  413 hoặc 504, hãy dùng ảnh nhỏ hơn hoặc mức bền vững thấp hơn.
- **Supabase free:** khoảng 500 MB cơ sở dữ liệu và 1 GB kho file. Mỗi tài khoản trên web bị giới hạn 200 mục
  và 500 MB (đổi bằng `MAX_ITEMS_PER_USER`, `MAX_STORAGE_MB_PER_USER` trên Render), nên với gói free hãy hạ
  `MAX_STORAGE_MB_PER_USER` xuống khoảng 50 nếu có nhiều người dùng.
- **Giới hạn tần suất theo IP** dựa vào header `x-forwarded-for` do Vercel và Render ghi. Ai gọi thẳng vào địa chỉ
  `onrender.com` (bỏ qua Vercel) có thể giả header này để né giới hạn theo IP. Giới hạn theo tên đăng nhập vẫn
  có hiệu lực.

## Cập nhật web về sau

Sửa mã trên máy rồi bấm đúp `cap-nhat-web.bat`. Hoặc tự đẩy lên GitHub: Render tự build lại; giao diện thì chạy
`npx vercel deploy --prod` trong thư mục `frontend` (hoặc nối repo với dự án Vercel để tự deploy).
Dữ liệu tài khoản và lịch sử nằm ở Supabase nên không mất khi triển khai lại.

## Chạy trên máy như trước

Không đặt `DATABASE_URL` và `SUPABASE_*` thì backend dùng SQLite và thư mục `backend\data` như cũ.
`run-dev.bat` và `run-prod.bat` vẫn dùng được.
