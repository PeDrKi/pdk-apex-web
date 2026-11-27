import { useEffect, useMemo, useState } from "react";
import { api, type CompareResult, type Session } from "../api";
import { formatBytes, nf } from "../utils";
import { Alert } from "./Alert";
import { Dropzone } from "./Dropzone";

type View = "slide" | "heat" | "overlay";
const VIEWS: { id: View; label: string }[] = [
  { id: "overlay", label: "Vị trí thay đổi" },
  { id: "heat", label: "Bản đồ nhiệt" },
  { id: "slide", label: "Trượt trước/sau" },
];

const sign = (d: number) => (d >= 0 ? "+" : "−");

export function ComparePanel({ session }: { session: Session | null }) {
  const [original, setOriginal] = useState<File | null>(null);
  const [stego, setStego] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [view, setView] = useState<View>("overlay");
  const [zoom, setZoom] = useState(1);
  const [split, setSplit] = useState(50);

  async function run(a: File, b: File) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.compare(a, b));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // Nhận ảnh từ tab Giấu tin và so sánh luôn.
  useEffect(() => {
    if (!session) return;
    setOriginal(session.original);
    setStego(session.stego);
    void run(session.original, session.stego);
  }, [session]);

  const aUrl = useMemo(() => (original ? URL.createObjectURL(original) : null), [original]);
  const bUrl = useMemo(() => (stego ? URL.createObjectURL(stego) : null), [stego]);
  useEffect(() => () => void (aUrl && URL.revokeObjectURL(aUrl)), [aUrl]);
  useEffect(() => () => void (bUrl && URL.revokeObjectURL(bUrl)), [bUrl]);

  const w = result ? result.width * zoom : 0;
  const fit = zoom === 1;

  return (
    <div className="panel">
      <p className="muted lead">
        Đặt ảnh gốc cạnh ảnh đã giấu tin để thấy chính xác những điểm ảnh nào đã bị thay đổi và thay đổi bao nhiêu.
      </p>
      <div className="grid-2">
        <Dropzone
          label="1. Ảnh gốc"
          hint="Ảnh trước khi giấu tin"
          accept="image/*"
          file={original}
          onFile={(f) => {
            setOriginal(f);
            setResult(null);
          }}
          preview
        />
        <Dropzone
          label="2. Ảnh đã giấu tin"
          hint="Ảnh PNG tải về sau khi giấu tin"
          accept="image/*"
          file={stego}
          onFile={(f) => {
            setStego(f);
            setResult(null);
          }}
          preview
        />
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      <div className="actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={!original || !stego || busy}
          onClick={() => original && stego && run(original, stego)}
        >
          {busy && <span className="spinner" aria-hidden="true" />}
          {busy ? "Đang so sánh…" : "So sánh hai ảnh"}
        </button>
      </div>

      {result && (
        <section className="result" aria-live="polite">
          <h2>Kết quả so sánh</h2>
          <dl className="stats">
            <div>
              <dt>Điểm ảnh thay đổi</dt>
              <dd>{(result.changed_ratio * 100).toFixed(2)}%</dd>
            </div>
            <div>
              <dt>Khối 4×4 thay đổi</dt>
              <dd>{nf.format(result.changed_blocks)}</dd>
            </div>
            <div>
              <dt>Lệch lớn nhất</dt>
              <dd>{result.max_diff} / 255</dd>
            </div>
            <div>
              <dt>PSNR</dt>
              <dd>{result.psnr_db === null ? "∞" : `${result.psnr_db.toFixed(1)} dB`}</dd>
            </div>
          </dl>

          <dl className="stats stats-3">
            <div>
              <dt>Dung lượng ảnh gốc (PNG)</dt>
              <dd>{formatBytes(result.original_png_bytes)}</dd>
            </div>
            <div>
              <dt>Dung lượng ảnh đã giấu (PNG)</dt>
              <dd>{formatBytes(result.stego_png_bytes)}</dd>
            </div>
            <div>
              <dt>Chênh lệch</dt>
              <dd>
                {sign(result.stego_png_bytes - result.original_png_bytes)}
                {formatBytes(Math.abs(result.stego_png_bytes - result.original_png_bytes))} (
                {sign(result.stego_png_bytes - result.original_png_bytes)}
                {(Math.abs(result.stego_png_bytes - result.original_png_bytes) / Math.max(1, result.original_png_bytes) * 100).toFixed(1)}%)
              </dd>
            </div>
          </dl>
          <p className="muted small">
            Cả hai ảnh đều tính ở dạng PNG để so cùng điều kiện.
            {original && stego && original.size !== result.original_png_bytes && (
              <> File gốc tải lên là {formatBytes(original.size)} ({original.type || "không rõ định dạng"}); file đã giấu là {formatBytes(stego.size)}.</>
            )}
          </p>

          {result.changed_pixels === 0 ? (
            <Alert kind="warn">Hai ảnh giống hệt nhau, không có điểm ảnh nào khác biệt.</Alert>
          ) : (
            <p className="muted small">
              {nf.format(result.changed_pixels)} trên {nf.format(result.width * result.height)} điểm ảnh đã đổi, nằm
              trong {nf.format(result.changed_blocks)} / {nf.format(result.total_blocks)} khối. Mỗi điểm ảnh đổi trung
              bình {result.mean_diff.toFixed(1)} mức sáng trên thang 255, nên mắt thường khó thấy.
            </p>
          )}

          <div className="viewer-bar">
            <div className="segmented" role="radiogroup" aria-label="Kiểu xem">
              {VIEWS.map((v) => (
                <button key={v.id} type="button" role="radio" aria-checked={view === v.id} className={view === v.id ? "is-active" : ""} onClick={() => setView(v.id)}>
                  {v.label}
                </button>
              ))}
            </div>
            <div className="segmented" role="radiogroup" aria-label="Phóng to">
              {[1, 2, 4, 8].map((z) => (
                <button key={z} type="button" role="radio" aria-checked={zoom === z} className={zoom === z ? "is-active" : ""} onClick={() => setZoom(z)}>
                  {z === 1 ? "Vừa khung" : `×${z}`}
                </button>
              ))}
            </div>
          </div>

          <div className="viewer">
            <div className="viewer-stage" style={fit ? { width: "100%" } : { width: w }}>
              {view === "heat" && (
                <img className="pixelated" src={`data:image/png;base64,${result.heatmap_png_base64}`} alt="Bản đồ nhiệt mức thay đổi" />
              )}
              {view === "overlay" && (
                <img className="pixelated" src={`data:image/png;base64,${result.overlay_png_base64}`} alt="Vị trí các điểm ảnh thay đổi" />
              )}
              {view === "slide" && aUrl && bUrl && (
                <>
                  <img className="pixelated" src={bUrl} alt="Ảnh đã giấu tin" />
                  <img className="pixelated viewer-top" src={aUrl} alt="Ảnh gốc" style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }} />
                  <span className="viewer-line" style={{ left: `${split}%` }} />
                </>
              )}
            </div>
          </div>

          {view === "slide" && (
            <label className="field">
              <span className="field-label">Kéo để so: bên trái là ảnh gốc, bên phải là ảnh đã giấu tin</span>
              <input type="range" min={0} max={100} value={split} onChange={(e) => setSplit(Number(e.target.value))} />
            </label>
          )}
          {view === "overlay" && (
            <p className="muted small">
              Ảnh gốc được làm tối và chuyển xám. <span className="swatch swatch-pink" /> Điểm ảnh màu hồng là điểm đã
              bị thay đổi, càng đậm thì thay đổi càng nhiều.
            </p>
          )}
          {view === "heat" && (
            <p className="muted small">
              <span className="swatch swatch-heat" /> Từ xanh (đổi ít) đến vàng và trắng (đổi nhiều nhất, {result.max_diff}{" "}
              mức). Vùng đen là không đổi.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
