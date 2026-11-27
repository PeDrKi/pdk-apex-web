import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AttackInfo, type AttackStep } from "../api";

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const MAX_W = 760;
const MAX_H = 520;
const MAX_PIXELS = 4_200_000;
export const MAX_STEPS = 1;
const LEVELS = ["Nhẹ", "Vừa", "Nặng"];

export function stepLabel(s: AttackStep, byId: Map<string, AttackInfo>): string {
  const p = s.params;
  if (p && s.id === "crop_custom") return `Cắt lấy vùng ${Math.round(p.w * 100)}%×${Math.round(p.h * 100)}% từ (${Math.round(p.x * 100)}%, ${Math.round(p.y * 100)}%)`;
  if (p && s.id === "erase_custom") return `Xoá vùng ${Math.round(p.w * 100)}%×${Math.round(p.h * 100)}% tại (${Math.round(p.x * 100)}%, ${Math.round(p.y * 100)}%)`;
  if (p && s.id === "resize_custom") return `Đổi kích thước ${p.w}×${p.h}`;
  return byId.get(s.id)?.name ?? s.id;
}

/**
 * Trình chỉnh ảnh trên canvas: kéo chọn vùng để cắt lấy / xoá, đổi kích thước, và thêm mọi phép tấn công khác
 * (nén, nhiễu, lọc, màu sắc, hình học). Kết quả của cả chuỗi  do máy chủ tính và hiện ở ô xem trước.
 */
export function ImageEditor({
  src,
  file,
  catalog,
  initial,
  onClose,
  onApply,
}: {
  src: string;
  file: File;
  catalog: AttackInfo[];
  initial: AttackStep[];
  onClose: () => void;
  onApply: (steps: AttackStep[]) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ mode: "new" | "move"; x: number; y: number; r: Rect | null } | null>(null);
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [rect, setRect] = useState<Rect | null>(null);
  const [rw, setRw] = useState(0);
  const [rh, setRh] = useState(0);
  const [lock, setLock] = useState(true);
  const [draft, setDraft] = useState<AttackStep[]>(initial);
  const [result, setResult] = useState<{ url: string; w: number; h: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const byId = new Map(catalog.map((a) => [a.id, a]));
  const groups = [...catalog.filter((a) => a.group !== "Nén").reduce((m, a) => m.set(a.group, [...(m.get(a.group) ?? []), a]), new Map<string, AttackInfo[]>())];

  useEffect(() => {
    const im = new Image();
    im.onload = () => {
      setImg(im);
      setRw(im.naturalWidth);
      setRh(im.naturalHeight);
    };
    im.src = src;
  }, [src]);

  // Xem trước kết quả của cả chuỗi do máy chủ tính (cùng thuật toán với lúc tấn công thật).
  useEffect(() => {
    if (!draft.length) {
      setResult(null);
      setErr(null);
      return;
    }
    let dead = false;
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        const r = await api.attack(file, draft, null, "", true);
        if (!dead) {
          setResult({ url: `data:image/png;base64,${r.attacked_png_base64}`, w: r.width, h: r.height });
          setErr(null);
        }
      } catch (e) {
        if (!dead) setErr((e as Error).message);
      } finally {
        if (!dead) setBusy(false);
      }
    }, 500);
    return () => {
      dead = true;
      clearTimeout(t);
    };
  }, [draft, file]);

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
    }
  }, [img, rect, cw, ch]);

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
    if (lock && img) setRh(Math.max(8, Math.round((v * img.naturalHeight) / img.naturalWidth)));
  }

  function setH(v: number) {
    setRh(v);
    if (lock && img) setRw(Math.max(8, Math.round((v * img.naturalWidth) / img.naturalHeight)));
  }

  function pctSize(p: number) {
    if (!img) return;
    setRw(Math.max(8, Math.round((img.naturalWidth * p) / 100)));
    setRh(Math.max(8, Math.round((img.naturalHeight * p) / 100)));
  }

  // Chỉ dùng một phép: chọn phép khác thì thay phép đang chọn.
  function add(st: AttackStep) {
    setDraft([st]);
  }

  function update(i: number, value: number) {
    setDraft((d) => d.map((s, j) => (j === i ? { ...s, value } : s)));
  }

  const sizeOk = rw >= 8 && rh >= 8 && rw <= 4000 && rh <= 4000 && rw * rh <= MAX_PIXELS;

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
              <canvas ref={canvas} width={cw} height={ch} className="editor-canvas" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} />
            ) : (
              <span className="spinner" aria-hidden="true" />
            )}
            <p className="muted small">Kéo trên ảnh để chọn vùng, kéo bên trong vùng để di chuyển.</p>
            <div className="editor-row">
              <button type="button" className="btn" disabled={!rect } onClick={() => rect && add({ id: "crop_custom", value: 0, params: { ...rect } })}>
                + Cắt lấy vùng chọn
              </button>
              <button type="button" className="btn" disabled={!rect } onClick={() => rect && add({ id: "erase_custom", value: 0, params: { ...rect } })}>
                + Xoá vùng chọn
              </button>
              {rect && <button type="button" className="link-btn" onClick={() => setRect(null)}>Bỏ vùng chọn</button>}
            </div>
            <div className="editor-row">
              <label className="editor-num">
                Rộng
                <input type="number" min={8} max={4000} value={rw || ""} onChange={(e) => setW(Number(e.target.value))} />
              </label>
              <label className="editor-num">
                Cao
                <input type="number" min={8} max={4000} value={rh || ""} onChange={(e) => setH(Number(e.target.value))} />
              </label>
              <label className="editor-lock">
                <input type="checkbox" checked={lock} onChange={(e) => setLock(e.target.checked)} /> Giữ tỉ lệ
              </label>
              {[75, 50, 25].map((p) => (
                <button key={p} type="button" className="chip" onClick={() => pctSize(p)}>{p}%</button>
              ))}
              <button type="button" className="btn" disabled={!sizeOk } onClick={() => add({ id: "resize_custom", value: 0, params: { w: rw, h: rh } })}>
                + Đổi kích thước
              </button>
            </div>
            {!sizeOk && <p className="small c-danger">Mỗi cạnh từ 8 đến 4000 px, tối đa khoảng 4 triệu điểm ảnh.</p>}
            <section className="editor-result">
              <span className="field-label">Xem trước kết quả {busy && <span className="spinner" aria-hidden="true" />}</span>
              {result ? (
                <>
                  <img className="editor-preview" src={result.url} alt="Ảnh sau khi áp dụng chuỗi" />
                  <p className="mono small">{result.w}×{result.h} px</p>
                </>
              ) : (
                <p className="muted small">Thêm một phép để xem ảnh sau khi tấn công.</p>
              )}
              {err && <p className="small c-danger">{err}</p>}
            </section>
          </div>

          <aside className="editor-side">
            <section>
              <span className="field-label">Chọn một phép tấn công</span>
              {groups.map(([g, list]) => (
                <div key={g} className="attack-group">
                  <span className="attack-group-name">{g}</span>
                  <div className="chips">
                    {list.map((a) => (
                      <button
                        key={a.id}
                        type="button"
                        className={a.id === "bc7" ? "chip chip-bc7" : "chip"}
                       
                        title={a.geometric ? "Phép hình học: làm lệch lưới điểm ảnh" : a.hint}
                        onClick={() => add({ id: a.id, value: a.param === "quality" ? 50 : 2 })}
                      >
                        + {a.name}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </section>

            <section>
              <span className="field-label">Phép sẽ áp dụng</span>
              {!draft.length && <p className="muted small">Chưa có phép nào.</p>}
              <ol className="chain">
                {draft.map((s, i) => {
                  const a = byId.get(s.id);
                  return (
                    <li key={i}>
                      <span className="chain-n">{String(i + 1).padStart(2, "0")}</span>
                      <strong>{stepLabel(s, byId)}</strong>
                      {a?.param === "level" && (
                        <span className="segmented small-seg">
                          {LEVELS.map((l, k) => (
                            <button key={l} type="button" className={s.value === k + 1 ? "is-active" : ""} onClick={() => update(i, k + 1)}>{l}</button>
                          ))}
                        </span>
                      )}
                      {a?.param === "quality" && (
                        <label className="chain-q">
                          <input type="range" min={5} max={95} step={5} value={s.value} onChange={(e) => update(i, Number(e.target.value))} />
                          <span className="mono">Q{s.value}</span>
                        </label>
                      )}
                      <button type="button" className="link-btn chain-x" onClick={() => setDraft(draft.filter((_, j) => j !== i))}>Bỏ</button>
                    </li>
                  );
                })}
              </ol>
            </section>


            <div className="actions">
              <button
                type="button"
                className="btn btn-primary"
                disabled={!draft.length}
                onClick={() => {
                  onApply(draft);
                  onClose();
                }}
              >
                Áp dụng
              </button>
              <button type="button" className="btn" onClick={() => setDraft([])} disabled={!draft.length}>Xoá hết</button>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
