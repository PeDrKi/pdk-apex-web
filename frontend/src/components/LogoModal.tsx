import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DEFAULT_EDIT,
  encodeLogo,
  inkOf,
  orientedUrl,
  type LogoEdit,
  type LogoInvert,
  type LogoMode,
  type ManualLogo,
} from "../lib/logo";

interface Props {
  bmp: ImageBitmap;
  mode: LogoMode;
  maxBody: number;
  maxSide: number;
  edit: LogoEdit;
  invert: LogoInvert;
  onApply: (edit: LogoEdit, invert: LogoInvert) => void;
  onClose: () => void;
}

const CROPS: { key: keyof LogoEdit["crop"]; label: string }[] = [
  { key: "l", label: "Cắt trái" },
  { key: "r", label: "Cắt phải" },
  { key: "t", label: "Cắt trên" },
  { key: "b", label: "Cắt dưới" },
];
const THICK = ["Mảnh hơn 2", "Mảnh hơn 1", "Giữ nguyên", "Dày hơn 1", "Dày hơn 2", "Dày hơn 3"];

/**
 * Sửa logo: mọi chỉnh sửa (xoay, lật, cắt, ngưỡng, độ dày nét, đảo nét) và vẽ tay từng điểm ảnh nằm chung ở đây.
 * Bấm "Áp dụng" mới ghi vào logo sẽ giấu; đóng cửa sổ thì bỏ các thay đổi.
 */
export function LogoModal({ bmp, mode, maxBody, maxSide, edit: edit0, invert: invert0, onApply, onClose }: Props) {
  const [edit, setEdit] = useState<LogoEdit>(edit0);
  const [invert, setInvert] = useState<LogoInvert>(invert0);
  const [tool, setTool] = useState<1 | 0>(1);
  const history = useRef<(ManualLogo | undefined)[]>([]);
  const [undoable, setUndoable] = useState(false);
  const painting = useRef(false);
  const canvas = useRef<HTMLCanvasElement>(null);

  const result = useMemo(() => {
    try {
      return { enc: encodeLogo(bmp, maxBody, mode, invert, maxSide, edit), error: null as string | null };
    } catch (e) {
      return { enc: null, error: (e as Error).message };
    }
  }, [bmp, maxBody, mode, invert, maxSide, edit]);
  const enc = result.enc;
  const srcUrl = useMemo(() => orientedUrl(bmp, edit), [bmp, edit.rotate, edit.flipH]);
  const binary = mode === "binary";
  const ink = useMemo(() => (enc && binary ? (edit.manual?.ink ?? inkOf(enc)) : null), [enc, binary, edit.manual]);
  const w = enc?.width ?? 0;
  const h = enc?.height ?? 0;
  const cell = w && h ? Math.max(4, Math.min(24, Math.floor(520 / Math.max(w, h)))) : 8;
  const { l, t, r, b } = edit.crop;

  // Đổi thông số thì bỏ bản vẽ tay (bản vẽ tay dựng từ kết quả của các thông số trước đó).
  const setParam = (patch: Partial<LogoEdit>) => setEdit((e) => ({ ...e, manual: undefined, ...patch }));

  function rotate(dir: 1 | -1) {
    const crop = dir === 1 ? { l: b, t: l, r: t, b: r } : { l: t, t: r, r: b, b: l };
    const turn = edit.flipH ? -dir : dir;
    setParam({ rotate: ((edit.rotate + turn * 90 + 360) % 360) as LogoEdit["rotate"], crop });
  }

  const draw = useCallback(() => {
    const c = canvas.current;
    if (!c || !ink) return;
    const g = c.getContext("2d")!;
    g.fillStyle = "#fff";
    g.fillRect(0, 0, w * cell, h * cell);
    g.fillStyle = "#000";
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (ink[y * w + x]) g.fillRect(x * cell, y * cell, cell, cell);
    if (cell >= 8) {
      g.strokeStyle = "rgba(0,229,160,0.35)";
      g.lineWidth = 1;
      g.beginPath();
      for (let x = 0; x <= w; x++) {
        g.moveTo(x * cell + 0.5, 0);
        g.lineTo(x * cell + 0.5, h * cell);
      }
      for (let y = 0; y <= h; y++) {
        g.moveTo(0, y * cell + 0.5);
        g.lineTo(w * cell, y * cell + 0.5);
      }
      g.stroke();
    }
  }, [ink, w, h, cell]);
  useEffect(draw, [draw]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  function pushHistory() {
    history.current.push(edit.manual);
    if (history.current.length > 60) history.current.shift();
    setUndoable(true);
  }

  function undo() {
    if (!history.current.length) return;
    const prev = history.current.pop();
    setEdit((e) => ({ ...e, manual: prev }));
    setUndoable(history.current.length > 0);
  }

  function setInk(fn: (a: Uint8Array) => void) {
    if (!ink) return;
    pushHistory();
    const next = ink.slice();
    fn(next);
    setEdit((e) => ({ ...e, manual: { w, h, ink: next } }));
  }

  function paint(e: React.PointerEvent, start: boolean) {
    if (!ink) return;
    const rc = canvas.current!.getBoundingClientRect();
    const x = Math.floor(((e.clientX - rc.left) / rc.width) * w);
    const y = Math.floor(((e.clientY - rc.top) / rc.height) * h);
    if (x < 0 || y < 0 || x >= w || y >= h) return;
    if (start) pushHistory();
    setEdit((prev) => {
      const cur = prev.manual?.ink ?? ink;
      if (cur[y * w + x] === tool) return prev;
      const next = cur.slice();
      next[y * w + x] = tool;
      return { ...prev, manual: { w, h, ink: next } };
    });
  }

  const changed = JSON.stringify({ ...edit, manual: undefined }) !== JSON.stringify(DEFAULT_EDIT) || invert !== "auto" || !!edit.manual;

  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-label="Sửa logo" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal editor-modal">
        <header className="editor-head">
          <h3>Sửa logo{enc ? ` (${enc.width} × ${enc.height} px)` : ""}</h3>
          <button type="button" className="link-btn" onClick={onClose}>Đóng</button>
        </header>
        <div className="editor-body">
          <div className="editor-canvas-wrap">
            {binary && ink ? (
              <>
                <canvas
                  ref={canvas}
                  width={w * cell}
                  height={h * cell}
                  className="editor-canvas pixelated"
                  onPointerDown={(e) => {
                    canvas.current!.setPointerCapture(e.pointerId);
                    painting.current = true;
                    paint(e, true);
                  }}
                  onPointerMove={(e) => painting.current && paint(e, false)}
                  onPointerUp={() => (painting.current = false)}
                  onPointerCancel={() => (painting.current = false)}
                />
                <p className="muted small">Bấm hoặc kéo chuột để vẽ từng điểm ảnh. Điểm đen là nét logo, điểm trắng là nền.</p>
                <div className="editor-row">
                  <label className="editor-lock">
                    <input type="radio" name="ptool" checked={tool === 1} onChange={() => setTool(1)} /> Vẽ nét (đen)
                  </label>
                  <label className="editor-lock">
                    <input type="radio" name="ptool" checked={tool === 0} onChange={() => setTool(0)} /> Tẩy (trắng)
                  </label>
                  <button type="button" className="btn btn-sm" disabled={!undoable} onClick={undo}>Hoàn tác</button>
                  <button type="button" className="btn btn-sm" onClick={() => setInk((a) => a.forEach((v, i) => (a[i] = v ? 0 : 1)))}>Đảo đen trắng</button>
                  <button type="button" className="btn btn-sm" onClick={() => setInk((a) => a.fill(0))}>Xoá hết</button>
                  {edit.manual && (
                    <button type="button" className="link-btn" onClick={() => { pushHistory(); setEdit((e) => ({ ...e, manual: undefined })); }}>
                      Bỏ phần vẽ tay
                    </button>
                  )}
                </div>
                {edit.manual && <p className="small c-warn">Đang có phần vẽ tay: đổi các thông số bên phải sẽ bỏ phần vẽ tay.</p>}
              </>
            ) : enc ? (
              <>
                <div className="logo-out"><img src={enc.previewUrl} alt="Logo sẽ được giấu" className="pixelated" /></div>
                <p className="muted small">Logo xám 256 mức sẽ được giấu đúng như thế này. Vẽ từng điểm ảnh chỉ có ở kiểu Đen trắng.</p>
              </>
            ) : (
              <p className="small c-danger">{result.error ?? "Chưa dựng được logo."}</p>
            )}
          </div>

          <aside className="editor-side">
            <section>
              <span className="field-label">Logo gốc · khung xanh là phần được giữ</span>
              <div className="crop-stage">
                <img src={srcUrl} alt="Logo gốc" />
                <div className="crop-box" style={{ left: `${l * 100}%`, top: `${t * 100}%`, right: `${r * 100}%`, bottom: `${b * 100}%` }} />
              </div>
              <div className="editor-row">
                <button type="button" className="btn btn-sm" onClick={() => rotate(-1)}>⟲ Xoay trái</button>
                <button type="button" className="btn btn-sm" onClick={() => rotate(1)}>⟳ Xoay phải</button>
                <button
                  type="button"
                  className={`btn btn-sm${edit.flipH ? " is-on" : ""}`}
                  aria-pressed={edit.flipH}
                  onClick={() => setParam({ flipH: !edit.flipH, crop: { l: r, t, r: l, b } })}
                >
                  ⇋ Lật ngang
                </button>
              </div>
              <label className="check">
                <input type="checkbox" checked={edit.autoTrim} onChange={(e) => setParam({ autoTrim: e.target.checked })} />
                Tự cắt viền trống quanh logo
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
                      onChange={(e) => setParam({ crop: { ...edit.crop, [c.key]: Number(e.target.value) / 100 } })}
                    />
                  </label>
                ))}
              </div>
            </section>

            {binary ? (
              <section>
                <div className="field">
                  <span className="field-label">
                    Ngưỡng đen trắng: {edit.threshold ?? `tự động${enc?.threshold != null ? ` (${enc.threshold})` : ""}`}
                  </span>
                  <input
                    type="range"
                    min={1}
                    max={254}
                    aria-label="Ngưỡng đen trắng"
                    value={edit.threshold ?? enc?.threshold ?? 127}
                    onChange={(e) => setParam({ threshold: Number(e.target.value) })}
                  />
                  <label className="check">
                    <input type="checkbox" checked={edit.threshold === null} onChange={(e) => setParam({ threshold: e.target.checked ? null : (enc?.threshold ?? 127) })} />
                    Tự chọn ngưỡng
                  </label>
                </div>
                <label className="field">
                  <span className="field-label">Độ dày nét: {THICK[edit.thicken + 2]}</span>
                  <input type="range" min={-2} max={3} value={edit.thicken} onChange={(e) => setParam({ thicken: Number(e.target.value) })} />
                </label>
                <label className="field">
                  <span className="field-label">Phần nào là nét logo</span>
                  <select value={invert} onChange={(e) => { setEdit((x) => ({ ...x, manual: undefined })); setInvert(e.target.value as LogoInvert); }}>
                    <option value="auto">Tự động (phần chiếm ít diện tích hơn)</option>
                    <option value="yes">Phần tối</option>
                    <option value="no">Phần sáng</option>
                  </select>
                </label>
              </section>
            ) : (
              <section>
                <label className="check">
                  <input type="checkbox" checked={edit.negate} onChange={(e) => setParam({ negate: e.target.checked })} />
                  Đảo sáng tối (dùng khi logo nét sáng trên nền trong suốt)
                </label>
                <div className="slider-grid">
                  <label className="field">
                    <span className="field-label">Độ sáng: {edit.brightness}</span>
                    <input type="range" min={-100} max={100} value={edit.brightness} onChange={(e) => setParam({ brightness: Number(e.target.value) })} />
                  </label>
                  <label className="field">
                    <span className="field-label">Tương phản: {edit.contrast}</span>
                    <input type="range" min={-100} max={100} value={edit.contrast} onChange={(e) => setParam({ contrast: Number(e.target.value) })} />
                  </label>
                </div>
              </section>
            )}

            <div className="actions">
              <button type="button" className="btn btn-primary" disabled={!enc} onClick={() => { onApply(edit, invert); onClose(); }}>
                Áp dụng
              </button>
              {changed && (
                <button type="button" className="btn" onClick={() => { history.current = []; setUndoable(false); setEdit(DEFAULT_EDIT); setInvert("auto"); }}>
                  Đặt lại
                </button>
              )}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
