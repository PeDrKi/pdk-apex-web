export function AboutPanel() {
  return (
    <article className="panel prose">
      <h2>APEX giấu tin như thế nào?</h2>
      <p>
        Ảnh được chia thành các khối 4×4 điểm ảnh. Nội dung của bạn (chữ hoặc logo) được đổi thành dãy bit, mỗi bit
        được giấu bằng cách dịch nhẹ độ sáng trung bình của một khối (lượng tử hoá QIM thích ứng). Thay đổi rất nhỏ nên
        mắt thường khó nhận ra.
      </p>
      <ol>
        <li>
          <strong>Chọn vị trí bằng tối ưu đàn kiến (ACO):</strong> ưu tiên các khối nhiều chi tiết, nơi thay đổi khó
          bị nhận ra và khó bị nén xoá mất.
        </li>
        <li>
          <strong>Xáo trộn hỗn loạn:</strong> thứ tự bit được xáo bằng ánh xạ logistic trước khi nhúng.
        </li>
        <li>
          <strong>Dự phòng:</strong> mỗi bit được lặp vào nhiều khối, lúc đọc sẽ bỏ phiếu đa số.
        </li>
        <li>
          <strong>Hiệu chỉnh N-GDC:</strong> bù lại sự lệch phân bố độ sáng do nén, chỉnh màu.
        </li>
        <li>
          <strong>Căn chỉnh hình học:</strong> khoá lưu kèm ảnh thu nhỏ để dựng lại khung ảnh khi bị cắt, co giãn
          hoặc xoay.
        </li>
      </ol>

      <h3>Mô hình bảo mật</h3>
      <ul>
        <li>
          <strong>File khoá</strong> <code>.npz</code> ghi vị trí các khối đã nhúng. Không có nó thì không đọc lại được
          nội dung. Hãy gửi ảnh và file khoá qua hai kênh khác nhau.
        </li>
        <li>
          <strong>Mật khẩu</strong> (nên dùng): nội dung được mã hoá <code>AES-256-GCM</code>, khoá dẫn xuất bằng{" "}
          <code>PBKDF2-HMAC-SHA256</code> 600.000 vòng với salt ngẫu nhiên. Người có cả ảnh lẫn file khoá vẫn không
          đọc được nếu thiếu mật khẩu, và mọi sửa đổi đều bị phát hiện.
        </li>
        <li>
          <strong>Không mật khẩu:</strong> nội dung chỉ được giấu chứ không được mã hoá. <code>CRC32</code> chỉ phát
          hiện lỗi ngẫu nhiên, không chống giả mạo.
        </li>
        <li>
          <strong>Mã hoá tại trình duyệt:</strong> khi có mật khẩu, nội dung được mã hoá bằng Web Crypto ngay trên máy
          bạn trước khi gửi đi. Máy chủ chỉ nhận dữ liệu đã mã hoá và không bao giờ thấy mật khẩu. Tính năng này cần
          trang chạy qua <code>HTTPS</code> (hoặc localhost).
        </li>
        <li>
          <strong>Máy chủ không lưu gì:</strong> ảnh và khoá chỉ nằm trong bộ nhớ lúc xử lý.
        </li>
        <li>
          Ảnh xuất ra là PNG mới, đã <strong>loại bỏ EXIF</strong> (vị trí GPS, thông tin máy ảnh) của ảnh gốc.
        </li>
      </ul>

      <h3>Giới hạn cần biết</h3>
      <ul>
        <li>Giấu tin không thay thế mã hoá: công cụ phân tích chuyên sâu có thể nghi ngờ ảnh có chứa dữ liệu.</li>
        <li>File khoá chứa ảnh thu nhỏ của ảnh gốc (nếu bật căn chỉnh), nên đừng công khai file khoá.</li>
        <li>Nén JPEG chất lượng thấp, chụp màn hình hay chỉnh sửa mạnh có thể làm hỏng nội dung.</li>
      </ul>

      <h3>Mẹo để nội dung bền hơn</h3>
      <ul>
        <li>Dùng mức “Bền vững” và ảnh càng lớn càng tốt.</li>
        <li>Giữ ảnh ở định dạng PNG khi chia sẻ.</li>
        <li>Nội dung càng ngắn thì càng có nhiều chỗ để dự phòng.</li>
      </ul>
    </article>
  );
}
