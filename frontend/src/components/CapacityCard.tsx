import type { CapacityResult } from "../api";
import { LOGO_HEADER_LEN, LOGO_MAX_SIDE } from "../lib/logo";
import { overhead } from "../lib/payload";
import { PRESETS } from "../lib/presets";
import { formatBytes, nf } from "../utils";

interface Props {
  cap: CapacityResult;
  redundancy: number;
  encrypted: boolean;
}

/** Số byte nội dung giấu được khi mỗi bit lặp `redundancy` lần. */
export function maxBytesAt(capacityBits: number, redundancy: number, encrypted: boolean): number {
  return Math.max(0, Math.floor(Math.floor(capacityBits / redundancy) / 8) - overhead(encrypted));
}

function logoSide(bytes: number, bitsPerPx: number): string {
  const px = Math.max(0, Math.floor(((bytes - LOGO_HEADER_LEN) * 8) / bitsPerPx));
  const side = Math.min(LOGO_MAX_SIDE, Math.floor(Math.sqrt(px)));
  return side >= 8 ? `${side} × ${side}` : "không đủ";
}

/** Bảng cho người dùng biết ảnh này giấu được bao nhiêu ở từng mức bền vững. */
export function CapacityCard({ cap, redundancy, encrypted }: Props) {
  // Các mức có cùng độ dự phòng thì chứa được như nhau: gộp thành một dòng.
  const rows: { name: string; redundancy: number }[] = [];
  for (const p of PRESETS) {
    const same = rows.find((r) => r.redundancy === p.redundancy);
    const short = p.name.replace(" (mặc định)", "");
    if (same) same.name += `, ${short}`;
    else rows.push({ name: short, redundancy: p.redundancy });
  }
  if (!rows.some((r) => r.redundancy === redundancy)) rows.push({ name: "Tuỳ chỉnh", redundancy });
  rows.sort((a, b) => a.redundancy - b.redundancy);
  const now = maxBytesAt(cap.capacity_bits, redundancy, encrypted);

  return (
    <div className="capacity">
      <div className="capacity-head">
        <span className="field-label">Sức chứa của ảnh này</span>
        <span className="muted small">
          {nf.format(cap.width)} × {nf.format(cap.height)} px · {nf.format(cap.capacity_bits)} khối 4×4
        </span>
      </div>
      <p className="capacity-now">
        <strong>{formatBytes(now)}</strong>
        <span className="muted small">
          {" "}ở mức đang chọn (lặp ×{redundancy}) · khoảng {nf.format(now)} ký tự không dấu hoặc {nf.format(Math.floor(now / 1.4))} ký tự tiếng Việt có dấu
        </span>
      </p>
      <div className="table-wrap">
        <table className="capacity-table">
          <thead>
            <tr>
              <th>Mức</th>
              <th>Chữ / file</th>
              <th>Logo đen trắng (px)</th>
              <th>Logo xám (px)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const b = maxBytesAt(cap.capacity_bits, r.redundancy, encrypted);
              return (
                <tr key={r.redundancy} className={r.redundancy === redundancy ? "is-current" : ""}>
                  <td>
                    {r.name} <span className="muted">×{r.redundancy}</span>
                  </td>
                  <td>{formatBytes(b)}</td>
                  <td>{logoSide(b, 1)}</td>
                  <td>{logoSide(b, 8)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Mỗi khối 4×4 điểm ảnh giấu được 1 bit, nên ảnh càng lớn càng giấu được nhiều. Mức bền vững càng cao thì mỗi bit
        được lặp lại càng nhiều lần, sức chứa giảm tương ứng.
        {encrypted ? " Đã trừ 28 byte dùng cho mã hoá bằng mật khẩu." : " Đặt mật khẩu sẽ tốn thêm 28 byte."}
      </p>
    </div>
  );
}
