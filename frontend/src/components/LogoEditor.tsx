import { useMemo } from "react";
import { DEFAULT_EDIT, orientedUrl, type EncodedLogo, type LogoEdit, type LogoInvert, type LogoMode } from "../lib/logo";

interface Props {
  bmp: ImageBitmap;
  mode: LogoMode;
  edit: LogoEdit;
  onEdit: (e: LogoEdit) => void;
  invert: LogoInvert;
  onInvert: (v: LogoInvert) => void;
  /** Kết quả dựng với các chỉnh sửa hiện tại; null nếu dựng lỗi. */
  encoded: EncodedLogo | null;
  note?: string;
}

const CROPS: { key: keyof LogoEdit["crop"]; label: string }[] = [
  { key: "l", label: "Cắt trái" },
  { key: "r", label: "Cắt phải" },
  { key: "t", label: "Cắt trên" },
  { key: "b", label: "Cắt dưới" },
];

const THICK = ["Mảnh hơn 2", "Mảnh hơn 1", "Giữ nguyên", "Dày hơn 1", "Dày hơn 2", "Dày hơn 3"];

/** Chỉnh logo trước khi giấu: xoay, lật, cắt, ngưỡng đen trắng, độ dày nét. Xem trước đúng từng điểm ảnh. */
export function LogoEditor({ bmp, mode, edit, onEdit, invert, onInvert, encoded, note }: Props) {
  const srcUrl = useMemo(() => orientedUrl(bmp, edit), [bmp, edit.rotate, edit.flipH]);
  const set = (patch: Partial<LogoEdit>) => onEdit({ ...edit, ...patch });
  const { l, t, r, b } = edit.crop;
  const changed = JSON.stringify(edit) !== JSON.stringify(DEFAULT_EDIT) || invert !== "auto";

  // Xoay thì khung cắt xoay theo để vùng đã chọn không đổi.
  function rotate(dir: 1 | -1) {
    const crop = dir === 1 ? { l: b, t: l, r: t, b: r } : { l: t, t: r, r: b, b: l };
    const turn = edit.flipH ? -dir : dir; // ảnh đang lật thì góc gốc quay ngược lại
    set({ rotate: ((edit.rotate + turn * 90 + 360) % 360) as LogoEdit["rotate"], crop });
  }

  return (
    <div className="logo-editor">
      <div className="logo-editor-head">
        <span className="field-label">Chỉnh logo trước khi giấu</span>
        {changed && (
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              onEdit(DEFAULT_EDIT);
              onInvert("auto");
            }}
          >
            Đặt lại
          </button>
        )}
      </div>

      <div className="logo-editor-views">
        <figure>
          <div className="crop-stage">
            <img src={srcUrl} alt="Logo gốc" />
            <div
              className="crop-box"
              style={{ left: `${l * 100}%`, top: `${t * 100}%`, right: `${r * 100}%`, bottom: `${b * 100}%` }}
            />
          </div>
          <figcaption>Logo gốc · khung xanh là phần được giữ</figcaption>
        </figure>
        <figure>
          <div className="logo-out">
            {encoded ? <img src={encoded.previewUrl} alt="Logo sẽ được giấu" className="pixelated" /> : <span className="muted small">—</span>}
          </div>
          <figcaption>
            {encoded ? `Sẽ giấu đúng như thế này · ${encoded.width} × ${encoded.height} px` : "Chưa dựng được logo"}
          </figcaption>
        </figure>
      </div>
      {note && <p className="muted small">{note}</p>}

      <div className="actions">
        <button type="button" className="btn btn-sm" onClick={() => rotate(-1)}>⟲ Xoay trái</button>
        <button type="button" className="btn btn-sm" onClick={() => rotate(1)}>⟳ Xoay phải</button>
        <button
          type="button"
          className={`btn btn-sm${edit.flipH ? " is-on" : ""}`}
          aria-pressed={edit.flipH}
          onClick={() => set({ flipH: !edit.flipH, crop: { l: r, t, r: l, b } })}
        >
          ⇋ Lật ngang
        </button>
      </div>

      <label className="check">
        <input type="checkbox" checked={edit.autoTrim} onChange={(e) => set({ autoTrim: e.target.checked })} />
        Tự cắt viền trống quanh logo (logo to và rõ hơn trong cùng kích thước)
      </label>

      <div className="slider-grid">
        {CROPS.map((c) => (
          <label key={c.key} className="field">
            <span className="field-label">{c.label}: {Math.round(edit.crop[c.key] * 100)}%</span>
            <input
              type="range"
              min={0}
              max={45}
              value={Math.round(edit.crop[c.key] * 100)}
              onChange={(e) => set({ crop: { ...edit.crop, [c.key]: Number(e.target.value) / 100 } })}
            />
          </label>
        ))}
      </div>

      {mode === "binary" ? (
        <>
          <div className="field">
            <span className="field-label">
              Ngưỡng đen trắng: {edit.threshold ?? `tự động${encoded?.threshold != null ? ` (${encoded.threshold})` : ""}`}
            </span>
            <input
              type="range"
              min={1}
              max={254}
              aria-label="Ngưỡng đen trắng"
              value={edit.threshold ?? encoded?.threshold ?? 127}
              onChange={(e) => set({ threshold: Number(e.target.value) })}
            />
            <label className="check">
              <input type="checkbox" checked={edit.threshold === null} onChange={(e) => set({ threshold: e.target.checked ? null : (encoded?.threshold ?? 127) })} />
              Tự chọn ngưỡng
            </label>
            <span className="muted small">Kéo ngưỡng nếu logo bị mất nét nhạt hoặc dính cả phần nền.</span>
          </div>
          <label className="field">
            <span className="field-label">Độ dày nét: {THICK[edit.thicken + 2]}</span>
            <input type="range" min={-2} max={3} value={edit.thicken} onChange={(e) => set({ thicken: Number(e.target.value) })} />
            <span className="muted small">Nét dày hơn sẽ dễ nhận ra hơn khi ảnh bị tấn công làm hỏng vài điểm.</span>
          </label>
          <label className="field">
            <span className="field-label">Phần nào là nét logo</span>
            <select value={invert} onChange={(e) => onInvert(e.target.value as LogoInvert)}>
              <option value="auto">Tự động (phần chiếm ít diện tích hơn)</option>
              <option value="yes">Phần tối</option>
              <option value="no">Phần sáng</option>
            </select>
          </label>
        </>
      ) : (
        <>
        <label className="check">
          <input type="checkbox" checked={edit.negate} onChange={(e) => set({ negate: e.target.checked })} />
          Đảo sáng tối (dùng khi logo nét sáng trên nền trong suốt)
        </label>
        <div className="slider-grid">
          <label className="field">
            <span className="field-label">Độ sáng: {edit.brightness}</span>
            <input type="range" min={-100} max={100} value={edit.brightness} onChange={(e) => set({ brightness: Number(e.target.value) })} />
          </label>
          <label className="field">
            <span className="field-label">Tương phản: {edit.contrast}</span>
            <input type="range" min={-100} max={100} value={edit.contrast} onChange={(e) => set({ contrast: Number(e.target.value) })} />
          </label>
        </div>
        </>
      )}
    </div>
  );
}
