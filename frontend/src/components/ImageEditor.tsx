import { useCallback, useEffect, useRef, useState } from "react";
import type { AttackStep } from "../api";

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const MAX_W = 860;
const MAX_H = 560;
const MAX_PIXELS = 4_200_000;

/**
 * Trình chỉnh ảnh trên canvas, mở trong một khung riêng: kéo để chọn vùng cắt (kéo bên trong vùng để di chuyển),
 * nhập kích thước mới, xem trước kết quả, rồi thêm thành bước tấn công (cắt trước, đổi kích thước sau).
 */
export function ImageEditor({
  src,
  slotsLeft,
  onClose,
  onApply,
}: {
  src: string;
  slotsLeft: number;
  onClose: () => void;
  onApply: (steps: AttackStep[]) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const preview = useRef<HTMLCanvasElement>(null);
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [rect, setRect] = useState<Rect | null>(null);
  const drag = useRef<{ mode: "new" | "move"; x: number; y: number; r: Rect | null } | null>(null);
  const [resizeOn, setResizeOn] = useState(false);
  const [rw, setRw] = useState(0);
  const [rh, setRh] = useState(0);
  const [lock, setLock] = useState(true);

  useEffect(() => {
    const im = new Image();
    im.onload = () => setImg(im);
    im.src = src;
  }, [src]);

  // Kích thước gốc của phần sẽ đổi kích thước (vùng cắt nếu có, không thì cả ảnh).
  const base = img
    ? rect
      ? { w: Math.max(1, Math.round(rect.w * img.naturalWidth)), h: Math.max(1, Math.round(rect.h * img.naturalHeight)) }
      : { w: img.naturalWidth, h: img.naturalHeight }
    : null;

  useEffect(() => {
    if (base && !resizeOn) {
      setRw(base.w);
      setRh(base.h);
    }
  }, [base?.w, base?.h, resizeOn]); // eslint-disable-line react-hooks/exhaustive-deps

  const scale = img ? Math.min(MAX_W / img.naturalWidth, MAX_H / img.naturalHeight, 1) : 1;
  const cw = img ? Math.round(img.naturalWidth * scale) : 0;
  const ch = img ? Math.round(img.naturalHeight * scale) : 0;

  const draw = useCallback(() => {
    const c = canvas.current;
    if (!c || !img) return;
    const g = c.getContext("2d")!;
    g.clearRect(0, 0, cw, ch);
    g.drawImage(img, 0, 0, cw, ch);
    if (rect) {
      const x = rect.x * cw, y = rect.y * ch, w = rect.w * cw, h = rect.h * ch;
      g.fillStyle = "rgba(0,0,0,0.55)";
      g.fillRect(0, 0, cw, y);
      g.fillRect(0, y + h, cw, ch - y - h);
      g.fillRect(0, y, x, h);
      g.fillRect(x + w, y, cw - x - w, h);
      g.strokeStyle = "#00e5a0";
      g.lineWidth = 2;
      g.strokeRect(x + 1, y + 1, w - 2, h - 2);
      g.setLineDash([4, 4]);
      g.lineWidth = 1;
      g.beginPath();
      for (const t of [1 / 3, 2 / 3]) {
        g.moveTo(x + w * t, y);
        g.lineTo(x + w * t, y + h);
        g.moveTo(x, y + h * t);
        g.lineTo(x + w, y + h * t);
      }
      g.stroke();
      g.setLineDash([]);
    }
    // Xem trước: cắt rồi đổi kích thước.
    const p = preview.current;
    if (p && base) {
      const ow = resizeOn ? rw : base.w;
      const oh = resizeOn ? rh : base.h;
      if (ow > 0 && oh > 0) {
        const s = Math.min(260 / ow, 200 / oh, 1);
        p.width = Math.max(1, Math.round(ow * s));
        p.height = Math.max(1, Math.round(oh * s));
        const pg = p.getContext("2d")!;
        pg.imageSmoothingEnabled = true;
        const sx = rect ? rect.x * img.naturalWidth : 0;
        const sy = rect ? rect.y * img.naturalHeight : 0;
        pg.drawImage(img, sx, sy, base.w, base.h, 0, 0, p.width, p.height);
      }
    }
  }, [img, rect, cw, ch, base?.w, base?.h, resizeOn, rw, rh]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(draw, [draw]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  function point(e: React.PointerEvent) {
    const r = canvas.current!.getBoundingClientRect();
    return { x: clamp((e.clientX - r.left) / r.width, 0, 1), y: clamp((e.clientY - r.top) / r.height, 0, 1) };
  }

  function down(e: React.PointerEvent) {
    canvas.current!.setPointerCapture(e.pointerId);
    const p = point(e);
    const inside = rect && p.x >= rect.x && p.x <= rect.x + rect.w && p.y >= rect.y && p.y <= rect.y + rect.h;
    drag.current = { mode: inside ? "move" : "new", x: p.x, y: p.y, r: rect };
    if (!inside) setRect({ x: p.x, y: p.y, w: 0, h: 0 });
  }

  function move(e: React.PointerEvent) {
    const d = drag.current;
    if (!d) return;
    const p = point(e);
    if (d.mode === "move" && d.r) {
      setRect({ ...d.r, x: clamp(d.r.x + p.x - d.x, 0, 1 - d.r.w), y: clamp(d.r.y + p.y - d.y, 0, 1 - d.r.h) });
    } else {
      setRect({ x: Math.min(d.x, p.x), y: Math.min(d.y, p.y), w: Math.abs(p.x - d.x), h: Math.abs(p.y - d.y) });
    }
  }

  function up() {
    drag.current = null;
    setRect((r) => (r && (r.w < 0.02 || r.h < 0.02) ? null : r));
  }

  function setW(v: number) {
    setRw(v);
    if (lock && base) setRh(Math.max(8, Math.round((v * base.h) / base.w)));
  }

  function setH(v: number) {
    setRh(v);
    if (lock && base) setRw(Math.max(8, Math.round((v * base.w) / base.h)));
  }

  function pctSize(p: number) {
    if (!base) return;
    setResizeOn(true);
    setRw(Math.max(8, Math.round((base.w * p) / 100)));
    setRh(Math.max(8, Math.round((base.h * p) / 100)));
  }

  const sizeOk = !resizeOn || (rw >= 8 && rh >= 8 && rw <= 4000 && rh <= 4000 && rw * rh <= MAX_PIXELS);
  const planned: AttackStep[] = [];
  if (rect) planned.push({ id: "crop_custom", value: 0, params: { ...rect } });
  if (resizeOn && base && (rw !== base.w || rh !== base.h)) planned.push({ id: "resize_custom", value: 0, params: { w: rw, h: rh } });
  const tooMany = planned.length > slotsLeft;

  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-label="Trình chỉnh ảnh" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal editor-modal">
        <header className="editor-head">
          <h3>Trình chỉnh ảnh</h3>
          <button type="button" className="link-btn" onClick={onClose}>Đóng</button>
        </header>
        <div className="editor-body">
          <div className="editor-canvas-wrap">
            {img ? (
              <canvas
                ref={canvas}
                width={cw}
                height={ch}
                className="editor-canvas"
                onPointerDown={down}
                onPointerMove={move}
                onPointerUp={up}
                onPointerCancel={up}
              />
            ) : (
              <span className="spinner" aria-hidden="true" />
            )}
            <p className="muted small">Kéo trên ảnh để chọn vùng cắt, kéo bên trong vùng để di chuyển.</p>
          </div>
          <aside className="editor-side">
            <section>
              <span className="field-label">Cắt</span>
              <p className="mono small">
                {rect && img
                  ? `${base!.w}×${base!.h} px từ (${Math.round(rect.x * img.naturalWidth)}, ${Math.round(rect.y * img.naturalHeight)})`
                  : img
                    ? `Chưa chọn vùng (ảnh ${img.naturalWidth}×${img.naturalHeight})`
                    : ""}
              </p>
              {rect && (
                <button type="button" className="link-btn" onClick={() => setRect(null)}>Bỏ vùng chọn</button>
              )}
            </section>
            <section>
              <label className="editor-lock">
                <input type="checkbox" checked={resizeOn} onChange={(e) => setResizeOn(e.target.checked)} /> Đổi kích thước
              </label>
              <div className="editor-row">
                <label className="editor-num">
                  Rộng
                  <input type="number" min={8} max={4000} value={rw || ""} disabled={!resizeOn} onChange={(e) => setW(Number(e.target.value))} />
                </label>
                <label className="editor-num">
                  Cao
                  <input type="number" min={8} max={4000} value={rh || ""} disabled={!resizeOn} onChange={(e) => setH(Number(e.target.value))} />
                </label>
              </div>
              <div className="editor-row">
                <label className="editor-lock">
                  <input type="checkbox" checked={lock} onChange={(e) => setLock(e.target.checked)} /> Giữ tỉ lệ
                </label>
                {[75, 50, 25].map((p) => (
                  <button key={p} type="button" className="chip" onClick={() => pctSize(p)}>{p}%</button>
                ))}
              </div>
              {!sizeOk && <p className="small c-danger">Mỗi cạnh từ 8 đến 4000 px, tối đa khoảng 4 triệu điểm ảnh.</p>}
            </section>
            <section>
              <span className="field-label">Xem trước kết quả</span>
              <canvas ref={preview} className="editor-preview" />
              {base && <p className="mono small">{resizeOn ? rw : base.w}×{resizeOn ? rh : base.h} px</p>}
            </section>
            {tooMany && (
              <p className="small c-warn">Chuỗi chỉ còn {slotsLeft} chỗ trống (tối đa 2 phép). Hãy bỏ bớt một thao tác hoặc một phép trong chuỗi.</p>
            )}
            <div className="actions">
              <button
                type="button"
                className="btn btn-primary"
                disabled={!planned.length || tooMany || !sizeOk}
                onClick={() => {
                  onApply(planned);
                  onClose();
                }}
              >
                Thêm {planned.length || ""} bước vào chuỗi
              </button>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
