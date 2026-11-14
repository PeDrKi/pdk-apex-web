import { useState } from "react";
import { api, type ProofResult } from "../api";
import { Alert } from "./Alert";
import { Dropzone } from "./Dropzone";

const dateFmt = new Intl.DateTimeFormat("vi-VN", { dateStyle: "long", timeStyle: "medium" });

async function sha256Hex(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Tra dấu thời gian: file được băm ngay tại trình duyệt, chỉ mã băm được gửi đi. */
export function ProofCheck() {
  const [file, setFile] = useState<File | null>(null);
  const [hash, setHash] = useState<string | null>(null);
  const [res, setRes] = useState<ProofResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function check(f: File | null) {
    setFile(f);
    setRes(null);
    setHash(null);
    setError(null);
    if (!f) return;
    setBusy(true);
    try {
      if (!crypto?.subtle) throw new Error("Tính mã băm cần trang chạy qua HTTPS.");
      const h = await sha256Hex(f);
      setHash(h);
      setRes(await api.proof(h));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <h3 className="field-label">Kiểm tra dấu thời gian</h3>
      <p className="muted small">
        Mỗi mục lưu vào tài khoản được ghi lại mã băm SHA-256 của ảnh đã giấu tin và của file khoá, kèm thời điểm lưu.
        Thả một trong hai file vào đây để xem nó đã được ai lưu, từ lúc nào. File không rời máy bạn, chỉ mã băm được
        gửi đi.
      </p>
      <Dropzone label="Ảnh đã giấu tin hoặc file khoá" hint="Phải là đúng file gốc, chưa bị sửa hay nén lại" accept="*/*" file={file} onFile={check} />
      {busy && <p className="muted small">Đang tính mã băm…</p>}
      {error && <Alert kind="error">{error}</Alert>}
      {res?.found && (
        <Alert kind="ok">
          Đã được tài khoản <strong>@{res.owner}</strong> lưu lần đầu{" "}
          <strong>{dateFmt.format(new Date((res.registered_at ?? 0) * 1000))}</strong> với tên “{res.name}” (
          {res.matched === "keys" ? "khớp file khoá" : "khớp ảnh đã giấu tin"}).
        </Alert>
      )}
      {res && !res.found && (
        <Alert kind="warn">
          Chưa có tài khoản nào lưu đúng file này. Nếu ảnh đã bị nén hay chỉnh sửa thì mã băm sẽ khác: khi đó hãy kiểm
          tra bằng <strong>file khoá</strong>, rồi dùng tab Đọc tin để chứng minh khoá đó đọc được nội dung từ ảnh.
        </Alert>
      )}
      {hash && <p className="muted small" style={{ wordBreak: "break-all" }}>SHA-256: {hash}</p>}
      <p className="muted small">
        Lưu ý: thời điểm do chính máy chủ này ghi nhận, không phải dấu thời gian của một tổ chức chứng thực độc lập. Xoá
        mục khỏi lịch sử thì dấu thời gian của nó cũng mất.
      </p>
    </div>
  );
}
