// Chính sách quyền riêng tư. Giữ khớp với PRIVACY.md và với những gì máy chủ thực sự lưu
// (backend/app/db.py, accounts.py). Sửa mã lưu trữ thì phải sửa trang này.
export function PrivacyPanel() {
  return (
    <article className="panel prose">
      <h2>Chính sách quyền riêng tư</h2>
      <p className="muted small">Cập nhật ngày 14/11/2026</p>

      <h3>Cam kết</h3>
      <ul>
        <li>
          <strong>Không bán, không chia sẻ, không phát tán</strong> thông tin của bạn cho bất kỳ ai, kể cả để quảng cáo.
        </li>
        <li>
          <strong>Không theo dõi:</strong> web không có quảng cáo, không có công cụ thống kê, không có cookie theo
          dõi, không nhúng mã của mạng xã hội.
        </li>
        <li>
          <strong>Chỉ lưu đúng những gì cần</strong> để web chạy được, và chỉ khi bạn có tài khoản. Toàn bộ danh sách
          nằm ở dưới, không có gì được lưu ngoài danh sách đó.
        </li>
        <li>
          <strong>Không bao giờ lưu mật khẩu nội dung.</strong> Khi bạn đặt mật khẩu, nội dung được mã hoá AES-256 ngay
          trong trình duyệt trước khi gửi đi. Máy chủ không đọc được, và chúng tôi cũng không khôi phục được nếu bạn
          quên.
        </li>
        <li>
          <strong>Bạn có quyền xoá:</strong> từng mục, toàn bộ lịch sử, hoặc cả tài khoản, bất cứ lúc nào, ngay trên
          web.
        </li>
      </ul>

      <h3>Khi bạn dùng mà không đăng nhập</h3>
      <p>
        Ảnh của bạn được gửi lên máy chủ để giấu hoặc đọc tin, xử lý trong bộ nhớ, rồi bỏ đi ngay khi trả kết quả.
        Không có gì được ghi vào cơ sở dữ liệu. Lịch sử của khách chỉ nằm trong tab trình duyệt đang mở và mất khi đóng
        tab.
      </p>

      <h3>Khi bạn có tài khoản, máy chủ lưu</h3>
      <ul>
        <li>
          <strong>Tên đăng nhập.</strong> Web không hỏi email, số điện thoại hay họ tên.
        </li>
        <li>
          <strong>Mật khẩu đăng nhập, mã khôi phục, mã xác thực 2 bước:</strong> mật khẩu và mã khôi phục chỉ lưu dạng
          băm scrypt, không ai đọc ngược lại được. Khoá bí mật của xác thực 2 bước được lưu để kiểm tra mã 6 số.
        </li>
        <li>
          <strong>Phiên đăng nhập:</strong> một cookie duy nhất, chỉ dùng để giữ bạn đăng nhập, hết hạn sau 30 ngày
          hoặc khi bạn đăng xuất.
        </li>
        <li>
          <strong>Nhật ký đăng nhập:</strong> thời điểm, loại sự kiện (đăng nhập, sai mật khẩu, đổi mật khẩu…) và địa
          chỉ IP. Dùng để chặn dò mật khẩu và để bạn tự xem trong phần cài đặt tài khoản. Tự xoá sau 90 ngày.
        </li>
        <li>
          <strong>Những mục bạn lưu vào lịch sử:</strong> ảnh đã giấu tin, file khoá, ảnh thu nhỏ của ảnh đã giấu tin,
          tên mục, kích thước ảnh, các thông số giấu và mã băm SHA-256 để làm bằng chứng thời gian. Ảnh gốc không
          được lưu.
        </li>
      </ul>
      <p>
        Nếu bạn đặt mật khẩu nội dung, file khoá cũng được niêm phong trong trình duyệt, nên máy chủ chỉ giữ một khối
        dữ liệu đã mã hoá. Nếu bạn chọn "Không mã hoá", nội dung giấu và file khoá (có kèm ảnh thu nhỏ đen trắng của ảnh
        gốc để căn chỉnh) không được bảo vệ, ai có quyền đọc kho lưu trữ đều xem được.
      </p>

      <h3>Tra bằng chứng thời gian là công khai</h3>
      <p>
        Bất kỳ ai có đúng file ảnh đã giấu tin hoặc file khoá mà bạn đã lưu đều tra được tên tài khoản của bạn, tên
        mục và thời điểm lưu. Đây là cách bằng chứng hoạt động. Nếu không muốn, đừng lưu mục đó vào tài khoản, hoặc đặt
        tên tài khoản và tên mục không lộ danh tính.
      </p>

      <h3>Bên thứ ba</h3>
      <p>Web chạy trên các dịch vụ dưới đây. Họ chỉ xử lý dữ liệu để vận hành web, không phải để chúng tôi chia sẻ.</p>
      <ul>
        <li>
          <strong>Vercel</strong> (phục vụ giao diện) và <strong>Render</strong> (máy chủ xử lý): như mọi máy chủ web,
          họ ghi nhật ký kỹ thuật gồm địa chỉ IP, đường dẫn yêu cầu và thời điểm, theo chính sách của họ.
        </li>
        <li>
          <strong>Supabase:</strong> nơi đặt cơ sở dữ liệu và kho lưu ảnh của tài khoản.
        </li>
        <li>
          <strong>Have I Been Pwned:</strong> khi đăng ký hoặc đổi mật khẩu, máy chủ gửi 5 ký tự đầu của mã băm SHA-1
          để kiểm tra mật khẩu đã từng bị lộ chưa. Mật khẩu và tên đăng nhập không được gửi đi.
        </li>
      </ul>

      <h3>Trên trình duyệt của bạn</h3>
      <p>
        Web chỉ ghi một tuỳ chọn vào bộ nhớ trình duyệt: có tự lưu vào tài khoản hay không. Ngoài cookie đăng nhập ở
        trên, không có cookie nào khác.
      </p>

      <h3>Xoá dữ liệu</h3>
      <p>
        Xoá một mục hay toàn bộ lịch sử sẽ xoá cả ảnh và file khoá khỏi kho lưu trữ. Xoá tài khoản (trong cài đặt tài
        khoản, cần nhập mật khẩu) sẽ xoá tài khoản, mọi phiên đăng nhập, mọi mục đã lưu và nhật ký đăng nhập gắn với tài
        khoản. Những lần đăng nhập sai không gắn được với tài khoản nào vẫn được giữ đến khi tự xoá sau 90 ngày. Bản sao
        lưu của nhà cung cấp, nếu có, sẽ hết hạn theo chu kỳ của họ.
      </p>

      <h3>Giới hạn</h3>
      <p>
        Chúng tôi làm hết sức để bảo vệ dữ liệu, nhưng không hệ thống nào an toàn tuyệt đối. Hãy luôn đặt mật khẩu nội
        dung cho thông tin quan trọng: khi đó, kể cả nếu máy chủ bị xâm nhập, nội dung của bạn vẫn không đọc được.
      </p>

      <h3>Liên hệ</h3>
      <p>
        Mọi câu hỏi hoặc yêu cầu về dữ liệu của bạn, vui lòng liên hệ qua điện thoại:{" "}
        <a href="tel:0867758620">0867 758 620</a>.
      </p>
    </article>
  );
}
