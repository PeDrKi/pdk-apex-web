import { type FormEvent, useEffect, useState } from "react";
import { extractAndReveal, type Revealed } from "../lib/codec";
import { PayloadError, WrongPasswordError } from "../lib/payload";
import { isZip, unpackBundle } from "../lib/zip";
import { ApiError, type ExtractResult } from "../api";
import { Alert } from "./Alert";
import { Dropzone } from "./Dropzone";
import { RevealedView } from "./RevealedView";

interface Props {
  syncAvailable: boolean;
  /** Ảnh + khoá được mở từ tab Lịch sử. */
  preset: { image: File; keys: File } | null;
}

export function ExtractPanel({ syncAvailable, preset }: Props) {
  const [image, setImage] = useState<File | null>(null);
  const [keys, setKeys] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [needPw, setNeedPw] = useState(false);
  const [resync, setResync] = useState(true);
  const [rotate, setRotate] = useState(0);
  const [aggregate, setAggregate] = useState<"mean" | "kmeans">("mean");
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [out, setOut] = useState<{ raw: ExtractResult; revealed: Revealed } | null>(null);

  useEffect(() => {
    if (!preset) return;
    setImage(preset.image);
    setKeys(preset.keys);
    setPassword("");
    setNeedPw(false);
    setOut(null);
    setError(null);
  }, [preset]);

  // Thả gói .zip (ảnh + khoá) vào ô nào cũng được: tự tách ra hai file.
  async function take(f: File | null, slot: "image" | "keys") {
    setOut(null);
    setError(null);
    if (f && isZip(f)) {
      try {
        const b = await unpackBundle(f);
        if (!b.image && !b.keys) throw new Error("Gói zip không chứa ảnh hay file khoá.");
        if (b.image) setImage(b.image);
        if (b.keys) setKeys(b.keys);
      } catch (e) {
        setError((e as Error).message);
      }
      return;
    }
    if (slot === "image") setImage(f);
    else {
      setKeys(f);
      setNeedPw(false);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!image || !keys) return;
    setBusy(true);
    setError(null);
    setOut(null);
    try {
      setOut(await extractAndReveal({ image, keys, password, resync, rotateRange: rotate, aggregate }));
    } catch (err) {
      if (err instanceof WrongPasswordError || (err instanceof ApiError && err.status === 401)) setNeedPw(true);
      setError(err instanceof PayloadError || err instanceof Error ? err.message : "Không đọc được nội dung.");
    } finally {
      setBusy(false);
    }
  }

  const r = out?.revealed;

  return (
    <form className="panel" onSubmit={submit}>
      <div className="grid-2">
        <Dropzone
          label="1. Ảnh đã giấu tin"
          hint="Ảnh PNG, hoặc thả luôn gói .zip (ảnh + khoá)"
          accept="image/*,.zip"
          file={image}
          onFile={(f) => take(f, "image")}
          preview
        />
        <Dropzone
          label="2. File khoá"
          hint="File .npz tải về lúc giấu tin, hoặc gói .zip"
          accept=".npz,.zip,application/octet-stream"
          file={keys}
          onFile={(f) => take(f, "keys")}
        />
      </div>

      <div className="field">
        <label className="field-label" htmlFor="xpw">Mật khẩu {needPw ? "" : "(nếu có)"}</label>
        <input
          id="xpw"
          type="password"
          value={password}
          autoComplete="off"
          className={needPw && !password ? "is-invalid" : ""}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>

      <button type="button" className="link-btn" onClick={() => setAdvanced((v) => !v)}>
        {advanced ? "Ẩn tuỳ chọn nâng cao" : "Tuỳ chọn nâng cao"}
      </button>
      {advanced && (
        <div className="advanced">
          <label className="check">
            <input type="checkbox" checked={resync} disabled={!syncAvailable} onChange={(e) => setResync(e.target.checked)} />
            Tự căn chỉnh ảnh bị cắt, dịch, co giãn trước khi đọc
            {!syncAvailable && " (máy chủ chưa cài OpenCV)"}
          </label>
          <label className="field">
            <span className="field-label">Dò góc xoay: ±{rotate}°</span>
            <input type="range" min={0} max={20} value={rotate} disabled={!resync || !syncAvailable} onChange={(e) => setRotate(Number(e.target.value))} />
            <span className="muted small">Chỉ bật khi ảnh bị xoay. Dò càng rộng càng chậm.</span>
          </label>
          <label className="field">
            <span className="field-label">Cách gộp phiếu dự phòng</span>
            <select value={aggregate} onChange={(e) => setAggregate(e.target.value as "mean" | "kmeans")}>
              <option value="mean">Đa số (mặc định)</option>
              <option value="kmeans">K-means (thử khi ảnh bị chỉnh sáng/tương phản mạnh)</option>
            </select>
          </label>
        </div>
      )}

      {error && <Alert kind="error">{error}</Alert>}

      <div className="actions">
        <button className="btn btn-primary" disabled={!image || !keys || busy}>
          {busy ? <span className="spinner" aria-hidden="true" /> : null}
          {busy ? "Đang đọc…" : "Đọc nội dung đã giấu"}
        </button>
      </div>

      {out && r && (
        <section className="result" aria-live="polite">
          <h2>{r.kind === "logo" ? "Logo tìm được" : r.kind === "file" ? "File tìm được" : "Thông điệp tìm được"}</h2>
          <RevealedView value={r} />
          {r.integrityOk === true && (
            <Alert kind="ok">Nội dung nguyên vẹn (kiểm tra CRC32 khớp).{r.encrypted && " Đã giải mã bằng mật khẩu."}</Alert>
          )}
          {r.integrityOk === false && (
            <Alert kind="warn">
              Ảnh đã bị biến đổi nên một vài bit có thể sai: hãy kiểm tra lại nội dung. Thử bật căn chỉnh, dò góc xoay
              hoặc đổi cách gộp phiếu trong tuỳ chọn nâng cao.
            </Alert>
          )}
          {r.integrityOk === null && (
            <Alert kind="warn">Khoá này được tạo bằng công cụ dòng lệnh nên không có mã kiểm tra toàn vẹn.</Alert>
          )}
          <p className="muted small">
            {out.raw.used_resync ? "Có dùng căn chỉnh hình học · " : ""}
            {out.raw.n_bits} bit · {out.raw.elapsed_ms} ms
          </p>
        </section>
      )}
    </form>
  );
}
