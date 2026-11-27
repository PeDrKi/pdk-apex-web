import { useCallback, useEffect, useRef, useState } from "react";

/** Vẽ từng điểm ảnh của logo đen trắng: 1 = nét logo (đen), 0 = nền (trắng). Kéo chuột để vẽ liên tục. */
export function PixelEditor({
  width,
  height,
  ink,
  onApply,
  onClose,
}: {
  width: number;
  height: number;
  ink: Uint8Array;
  onApply: (ink: Uint8Array) => void;
  onClose: () => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [cur, setCur] = useState<Uint8Array>(() => ink.slice());
  const [tool, setTool] = useState<1 | 0>(1);
  const history = useRef<Uint8Array[]>([]);
  const [undoable, setUndoable] = useState(false);
  const painting = useRef(false);
  const cell = Math.max(4, Math.min(24, Math.floor(600 / Math.max(width, height))));
  const cw = width * cell;
  const ch = height * cell;

  const draw = useCallback(() => {
    const c = canvas.current;
    if (!c) return;
    const g = c.getContext("2d")!;
    g.fillStyle = "#fff";
    g.fillRect(0, 0, cw, ch);
    g.fillStyle = "#000";
    for (let y = 0; y < height; y++)
      for (let x = 0; x < width; x++) if (cur[y * width + x]) g.fillRect(x * cell, y * cell, cell, cell);
    if (cell >= 8) {
      g.strokeStyle = "rgba(0,229,160,0.35)";
      g.lineWidth = 1;
      g.beginPath();
      for (let x = 0; x <= width; x++) {
        g.moveTo(x * cell + 0.5, 0);
        g.lineTo(x * cell + 0.5, ch);
      }
      for (let y = 0; y <= height; y++) {
        g.moveTo(0, y * cell + 0.5);
        g.lineTo(cw, y * cell + 0.5);
      }
      g.stroke();
    }
  }, [cur, cell, cw, ch, width, height]);

  useEffect(draw, [draw]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  function push() {
    history.current.push(cur.slice());
    if (history.current.length > 60) history.current.shift();
    setUndoable(true);
  }

  function undo() {
    const last = history.current.pop();
    if (last) setCur(last);
    setUndoable(history.current.length > 0);
  }

  function apply(fn: (a: Uint8Array) => void) {
    push();
    const next = cur.slice();
    fn(next);
    setCur(next);
  }

  function paint(e: React.PointerEvent, start: boolean) {
    const r = canvas.current!.getBoundingClientRect();
    const x = Math.floor(((e.clientX - r.left) / r.width) * width);
    const y = Math.floor(((e.clientY - r.top) / r.height) * height);
    if (x < 0 || y < 0 || x >= width || y >= height) return;
    if (start) push();
    setCur((prev) => {
      if (prev[y * width + x] === tool) return prev;
      const next = prev.slice();
      next[y * width + x] = tool;
      return next;
    });
  }

  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-label="Sửa từng điểm ảnh của logo" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal editor-modal">
        <header className="editor-head">
          <h3>Sửa từng điểm ảnh của logo ({width} × {height} px)</h3>
          <button type="button" className="link-btn" onClick={onClose}>Đóng</button>
        </header>
        <div className="editor-body">
          <div className="editor-canvas-wrap">
            <canvas
              ref={canvas}
              width={cw}
              height={ch}
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
            <p className="muted small">Bấm hoặc kéo chuột để vẽ. Điểm đen là nét logo, điểm trắng là nền.</p>
          </div>
          <aside className="editor-side">
            <section>
              <span className="field-label">Công cụ</span>
              <div className="editor-row">
                <label className="editor-lock">
                  <input type="radio" name="ptool" checked={tool === 1} onChange={() => setTool(1)} /> Vẽ nét (đen)
                </label>
                <label className="editor-lock">
                  <input type="radio" name="ptool" checked={tool === 0} onChange={() => setTool(0)} /> Tẩy (trắng)
                </label>
              </div>
              <div className="editor-row">
                <button type="button" className="btn btn-sm" disabled={!undoable} onClick={undo}>Hoàn tác</button>
                <button type="button" className="btn btn-sm" onClick={() => apply((a) => a.forEach((v, i) => (a[i] = v ? 0 : 1)))}>Đảo đen trắng</button>
                <button type="button" className="btn btn-sm" onClick={() => apply((a) => a.fill(0))}>Xoá hết</button>
                <button type="button" className="btn btn-sm" onClick={() => apply((a) => a.set(ink))}>Về như ban đầu</button>
              </div>
            </section>
            <section className="editor-result">
              <span className="field-label">Kích thước thật</span>
              <canvas
                width={width}
                height={height}
                className="pixelated"
                style={{ width: width * 2, height: height * 2, background: "#fff", border: "1px solid #1f3a33" }}
                ref={(c) => {
                  if (!c) return;
                  const g = c.getContext("2d")!;
                  const img = g.createImageData(width, height);
                  for (let i = 0; i < width * height; i++) {
                    const v = cur[i] ? 0 : 255;
                    img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = v;
                    img.data[i * 4 + 3] = 255;
                  }
                  g.putImageData(img, 0, 0);
                }}
              />
            </section>
            <div className="actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  onApply(cur);
                  onClose();
                }}
              >
                Áp dụng
              </button>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
