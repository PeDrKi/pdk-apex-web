export function AboutPanel({ showDetect = false }: { showDetect?: boolean }) {
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

      <h3>Bền vững, không phải tàng hình</h3>
      <p>
        APEX được thiết kế để nội dung <strong>sống sót</strong> khi ảnh bị nén, cắt, co giãn, giống một thuỷ vân
        (watermark) ẩn. Nó không được thiết kế để qua mặt công cụ phân tích: cách nhúng theo khối để lại dấu vết
        thống kê, và mức bền vững càng cao thì ảnh càng đổi nhiều. Chỉ số PSNR sau khi giấu cho biết điều đó: từ 40 dB
        trở lên mắt thường khó thấy, dưới 38 dB web sẽ cảnh báo. Nếu việc bị phát hiện là có giấu tin gây nguy hiểm cho
        bạn, đừng dựa vào công cụ này.
      </p>
      {showDetect && (<p>
        Sau mỗi lần giấu tin, web tự chạy một <strong>bộ dò</strong> đóng vai người biết rõ thuật toán APEX nhưng không
        có file khoá. Bộ dò đo xem bao nhiêu khối 4×4 nằm đúng trên lưới lượng tử, rồi so với ảnh gốc. Kết quả phụ thuộc
        chủ yếu vào <strong>số khối bị đụng tới</strong>, tức độ dài nội dung nhân với độ dự phòng, chia cho kích thước
        ảnh. Giảm cường độ nhúng làm ảnh khó thấy bằng mắt hơn nhưng không qua mặt được bộ dò. Mức Nhẹ (dự phòng 1,
        không dùng hết chỗ trống) là mức khó phát hiện nhất. Đây là một bộ dò cụ thể, công cụ khác có thể nhạy hơn.
      </p>)}

      <h3>Mô hình bảo mật</h3>
      <ul>
        <li>
          <strong>File khoá</strong> ghi vị trí các khối đã nhúng và một ảnh thu nhỏ 256 px thang xám của ảnh đã giấu tin (để căn chỉnh khi ảnh bị cắt, xoay). Không có nó
          thì không đọc lại được nội dung. Khi bạn đặt mật khẩu, cả file khoá được mã hoá tại trình duyệt (đuôi{" "}
          <code>.apexkey</code>); không đặt mật khẩu thì nó là file <code>.npz</code> ai cũng mở được. Hãy gửi ảnh và
          file khoá qua hai kênh khác nhau.
        </li>
        <li>
          <strong>Mật khẩu</strong> (nên dùng): nội dung được mã hoá <code>AES-256-GCM</code>, khoá dẫn xuất bằng{" "}
          <code>PBKDF2-HMAC-SHA256</code> 600.000 vòng với salt ngẫu nhiên. Người có cả ảnh lẫn file khoá vẫn không
          đọc được nếu thiếu mật khẩu, và mọi sửa đổi đều bị phát hiện.
        </li>
        <li>
          <strong>Không mã hoá:</strong> ai có ảnh và file khoá đều đọc được nội dung, và máy chủ cũng thấy nội dung.
          Nội dung chỉ được giấu chứ không được mã hoá. <code>CRC32</code> chỉ phát hiện lỗi ngẫu nhiên, không chống
          giả mạo.
        </li>
        <li>
          <strong>Mã hoá tại trình duyệt:</strong> khi có mật khẩu, nội dung được mã hoá bằng Web Crypto ngay trên máy
          bạn trước khi gửi đi. Máy chủ chỉ nhận dữ liệu đã mã hoá và không bao giờ thấy mật khẩu. Tính năng này cần
          trang chạy qua <code>HTTPS</code> (hoặc localhost).
        </li>
        <li>
          <strong>Máy chủ thấy gì:</strong> việc nhúng chạy trên máy chủ nên máy chủ nhìn thấy ảnh gốc trong lúc xử
          lý, nhưng không ghi lại. Với khách, không có gì được lưu. Với tài khoản, máy chủ lưu ảnh đã giấu tin và file
          khoá (đã mã hoá nếu có mật khẩu).
        </li>
        <li>
          <strong>Dấu thời gian:</strong> mỗi mục lưu vào tài khoản được ghi mã băm SHA-256 và thời điểm lưu, tra lại
          được ở tab Lịch sử. Đây là ghi nhận của máy chủ này, chưa phải chứng thực của bên thứ ba.
        </li>
        <li>
          Ảnh xuất ra là PNG mới, đã <strong>loại bỏ EXIF</strong> (vị trí GPS, thông tin máy ảnh) của ảnh gốc.
        </li>
      </ul>

      <h3>Giới hạn cần biết</h3>
      <ul>
        <li>Giấu tin không thay thế mã hoá: công cụ phân tích chuyên sâu có thể nghi ngờ ảnh có chứa dữ liệu.</li>
        <li>File khoá không mật khẩu ai cũng mở được, ai có cả ảnh và file khoá đều đọc được nội dung, nên đừng công khai nó.</li>
        <li>Quên mật khẩu thì không ai khôi phục được nội dung lẫn file khoá.</li>
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
