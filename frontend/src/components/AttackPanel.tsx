import { useEffect, useMemo, useState } from "react";
import {
  api,
  type AttackInfo,
  type AttackResult,
  type AttackStatus,
  type AttackStep,
  type BatteryResult,
  type Session,
} from "../api";
import { needsServerDecrypt, reveal, type Revealed } from "../lib/codec";
import { openKeysFile } from "../lib/keyfile";
import { isZip, unpackBundle } from "../lib/zip";
import { base64ToBlob, downloadBlob, stem } from "../utils";
import { Alert } from "./Alert";
import { Dropzone } from "./Dropzone";
import { ImageEditor, stepLabel } from "./ImageEditor";
import { RevealedView } from "./RevealedView";

const LEVELS = ["Nhẹ", "Vừa", "Nặng"];
const STATUS_TEXT: Record<AttackStatus, string> = {
  intact: "Nguyên vẹn",
  partial: "Đọc được, sai vài bit",
  broken: "Hỏng",
};

function StatusTag({ status }: { status: AttackStatus }) {
  return <span className={`tag tag-${status}`}>{STATUS_TEXT[status]}</span>;
}

function pct(ber: number | null) {
  return ber === null ? "—" : `${(ber * 100).toFixed(ber > 0 && ber < 0.001 ? 3 : 2)}%`;
}

export function AttackPanel({ session }: { session: Session | null }) {
  const [catalog, setCatalog] = useState<AttackInfo[]>([]);
  const [image, setImage] = useState<File | null>(null);
  const [keys, setKeys] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [steps, setSteps] = useState<AttackStep[]>([]);
  const [level, setLevel] = useState(2);
  const [busy, setBusy] = useState<"attack" | "battery" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AttackResult | null>(null);
  const [battery, setBattery] = useState<BatteryResult | null>(null);
  const [revealed, setRevealed] = useState<Revealed | null>(null);
  const [revealError, setRevealError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  async function take(f: File | null, slot: "image" | "keys") {
    setResult(null);
    setBattery(null);
    setError(null);
    if (f && isZip(f)) {
      try {
        const b = await unpackBundle(f);
        if (b.image) setImage(b.image);
        if (b.keys) setKeys(b.keys);
      } catch (e) {
        setError((e as Error).message);
      }
      return;
    }
    if (slot === "image") setImage(f);
    else setKeys(f);
  }

  useEffect(() => {
    api.attacks().then(setCatalog).catch(() => setError("Không tải được danh sách phép tấn công."));
  }, []);

  // Nhận ảnh + khoá từ tab Giấu tin.
  useEffect(() => {
    if (!session) return;
    setImage(session.stego);
    setKeys(session.keys);
    setPassword(session.password);
    setResult(null);
    setBattery(null);
  }, [session]);

  const groups = useMemo(() => {
    const m = new Map<string, AttackInfo[]>();
    for (const a of catalog) if (a.id !== "bc7") m.set(a.group, [...(m.get(a.group) ?? []), a]);
    return [...m.entries()];
  }, [catalog]);
  const bc7 = useMemo(() => catalog.find((a) => a.id === "bc7"), [catalog]);
  const byId = useMemo(() => new Map(catalog.map((a) => [a.id, a])), [catalog]);

  const originalUrl = useMemo(() => (image ? URL.createObjectURL(image) : null), [image]);
  useEffect(() => () => void (originalUrl && URL.revokeObjectURL(originalUrl)), [originalUrl]);

  function addStep(a: AttackInfo) {
    setSteps([{ id: a.id, value: a.param === "quality" ? 50 : 2 }]);
  }

  function updateStep(i: number, value: number) {
    setSteps(steps.map((s, j) => (j === i ? { ...s, value } : s)));
  }

  async function run(kind: "attack" | "battery", only?: AttackStep[]) {
    if (!image) return;
    const plan = only ?? steps;
    setBusy(kind);
    setError(null);
    try {
      if (kind === "attack") {
        setResult(null);
        setRevealed(null);
        setRevealError(null);
        // Nhận dữ liệu thô rồi giải mã tại trình duyệt: mật khẩu không gửi lên máy chủ.
        const k = keys && (await openKeysFile(keys, password));
        let res = await api.attack(image, plan, k, "", true);
        if (res.extract && needsServerDecrypt(res.extract)) res = await api.attack(image, plan, k, password, false);
        setResult(res);
        if (res.extract) {
          try {
            setRevealed(await reveal(res.extract, password));
          } catch (e) {
            setRevealError((e as Error).message);
          }
        }
      } else if (keys) {
        setBattery(null);
        setBattery(await api.battery(image, await openKeysFile(keys, password), level));
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const ex = result?.extract;

  return (
    <div className="panel">
      <p className="muted lead">
        Mô phỏng việc ảnh bị nén, chỉnh sửa hay cắt xén, rồi kiểm tra xem nội dung đã giấu còn đọc lại được không.
      </p>

      <div className="grid-2">
        <Dropzone
          label="1. Ảnh đã giấu tin"
          hint="Ảnh PNG, hoặc gói .zip (ảnh + khoá)"
          accept="image/*,.zip"
          file={image}
          onFile={(f) => take(f, "image")}
          preview
        />
        <div className="stack">
          <Dropzone
            label="2. File khoá"
            hint="Cần có để thử đọc lại sau khi tấn công"
            accept=".npz,.apexkey,.zip,application/octet-stream"
            file={keys}
            onFile={(f) => take(f, "keys")}
          />
          <div className="field">
            <label className="field-label" htmlFor="apw">Mật khẩu (nếu có)</label>
            <input id="apw" type="password" value={password} autoComplete="off" onChange={(e) => setPassword(e.target.value)} />
          </div>
        </div>
      </div>

      {bc7 && (
        <div className="bc7-card">
          <div>
            <span className="bc7-badge">NỔI BẬT</span>
            <h3>Nén BC7 thật</h3>
            <p className="muted small">
              BC7 là chuẩn nén texture của card đồ hoạ (game, ứng dụng 3D), cắt ảnh thành khối 4×4 rồi mã hoá lại nên
              dễ xoá mất tin giấu. Đây là bộ mã hoá BC7 thật, cũng là phép thử khó nhất mà APEX được thiết kế để chống chịu.
            </p>
          </div>
          <div className="bc7-actions">
            <button type="button" className="btn btn-primary" disabled={!image || !keys || !!busy} onClick={() => run("attack", [{ id: "bc7", value: 0 }])}>
              {busy === "attack" ? "Đang chạy…" : "Thử ngay BC7"}
            </button>
            <button type="button" className="btn" onClick={() => addStep(bc7)}>
              Chọn BC7
            </button>
          </div>
        </div>
      )}

      {originalUrl && (
        <div className="editor-open">
          <div>
            <span className="field-label">Chỉnh ảnh như trình chỉnh sửa</span>
            <p className="muted small">Mở ảnh trên canvas để chọn vùng cắt hoặc xoá, đổi kích thước, thêm nhiễu, lọc, màu sắc, hình học, nén BC7, rồi xem trước kết quả.</p>
          </div>
          <button type="button" className="btn" onClick={() => setEditing(true)}>
            Mở trình chỉnh ảnh
          </button>
        </div>
      )}
      {editing && originalUrl && image && (
        <ImageEditor
          src={originalUrl}
          file={image}
          catalog={catalog}
          initial={steps}
          onClose={() => setEditing(false)}
          onApply={setSteps}
        />
      )}

      <fieldset className="field">
        <legend className="field-label">3. Chọn phép tấn công (chọn một phép)</legend>
        <div className="attack-groups">
          {groups.map(([g, list]) => (
            <div key={g} className="attack-group">
              <span className="attack-group-name">{g}</span>
              <div className="chips">
                {list.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    className="chip"
                    title={a.geometric ? "Phép hình học: làm lệch lưới điểm ảnh" : a.hint}
                    onClick={() => addStep(a)}
                  >
                    + {a.name}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </fieldset>

      {steps.length > 0 && (
        <ol className="chain">
          {steps.map((s, i) => {
            const a = byId.get(s.id);
            const custom = s.params ? stepLabel(s, byId) : null;
            if (!a && !custom) return null;
            return (
              <li key={i}>
                <span className="chain-n">{String(i + 1).padStart(2, "0")}</span>
                <strong>{custom ?? a!.name}</strong>
                {a?.param === "level" && (
                  <span className="segmented small-seg">
                    {LEVELS.map((l, k) => (
                      <button
                        key={l}
                        type="button"
                        className={s.value === k + 1 ? "is-active" : ""}
                        onClick={() => updateStep(i, k + 1)}
                      >
                        {l}
                      </button>
                    ))}
                  </span>
                )}
                {a?.param === "quality" && (
                  <label className="chain-q">
                    <input
                      type="range"
                      min={5}
                      max={95}
                      step={5}
                      value={s.value}
                      onChange={(e) => updateStep(i, Number(e.target.value))}
                    />
                    <span className="mono">Q{s.value}</span>
                  </label>
                )}
                <button
                  type="button"
                  className="link-btn chain-x"
                  aria-label={`Bỏ ${custom ?? a!.name}`}
                  onClick={() => setSteps(steps.filter((_, j) => j !== i))}
                >
                  Bỏ
                </button>
              </li>
            );
          })}
        </ol>
      )}

      {error && <Alert kind="error">{error}</Alert>}

      <div className="actions">
        <button type="button" className="btn btn-primary" disabled={!image || !steps.length || !!busy} onClick={() => run("attack")}>
          {busy === "attack" && <span className="spinner" aria-hidden="true" />}
          {busy === "attack" ? "Đang tấn công…" : keys ? "Tấn công và đọc lại" : "Tấn công ảnh"}
        </button>
        <span className="battery-ctl">
          <select value={level} onChange={(e) => setLevel(Number(e.target.value))} aria-label="Mức độ quét">
            {LEVELS.map((l, k) => (
              <option key={l} value={k + 1}>Mức {l.toLowerCase()}</option>
            ))}
          </select>
          <button type="button" className="btn" disabled={!image || !keys || !!busy} onClick={() => run("battery")}>
            {busy === "battery" && <span className="spinner" aria-hidden="true" />}
            {busy === "battery" ? "Đang quét…" : "Quét tất cả phép"}
          </button>
        </span>
      </div>

      {result && (
        <section className="result" aria-live="polite">
          <h2>Kết quả tấn công</h2>
          <p className="muted small mono">{result.steps.join("  →  ")}</p>
          <div className="compare">
            <figure>
              {originalUrl && <img src={originalUrl} alt="Trước khi tấn công" />}
              <figcaption>Trước khi tấn công</figcaption>
            </figure>
            <figure>
              <img src={`data:image/png;base64,${result.attacked_png_base64}`} alt="Sau khi tấn công" />
              <figcaption>Sau khi tấn công · {result.width}×{result.height}</figcaption>
            </figure>
          </div>

          {result.status && (
            <dl className="stats stats-3">
              <div>
                <dt>Kết luận</dt>
                <dd><StatusTag status={result.status} /></dd>
              </div>
              <div>
                <dt>Tỉ lệ bit sai</dt>
                <dd>{pct(result.ber)}</dd>
              </div>
              <div>
                <dt>Căn chỉnh hình học</dt>
                <dd>{ex?.used_resync ? "CÓ DÙNG" : "KHÔNG"}</dd>
              </div>
            </dl>
          )}

          {revealed && (
            <>
              <span className="field-label">Nội dung đọc lại được sau khi tấn công</span>
              <RevealedView value={revealed} caption="Đọc lại được sau khi tấn công" />
            </>
          )}
          {revealError && <Alert kind="error">{revealError}</Alert>}
          {result.extract_error && <Alert kind="error">{result.extract_error}</Alert>}
          {!keys && <Alert kind="warn">Chưa có file khoá nên chỉ tạo ảnh bị tấn công, chưa thử đọc lại.</Alert>}

          <div className="actions">
            <button
              type="button"
              className="btn"
              onClick={() =>
                downloadBlob(
                  base64ToBlob(result.attacked_png_base64, "image/png"),
                  `${image ? stem(image.name) : "anh"}_bi_tan_cong.png`,
                )
              }
            >
              Tải ảnh đã bị tấn công
            </button>
          </div>
        </section>
      )}

      {battery && (
        <section className="result" aria-live="polite">
          <h2>Quét {battery.rows.length} phép tấn công</h2>
          <dl className="stats stats-3">
            <div>
              <dt>Nguyên vẹn</dt>
              <dd>{battery.intact}</dd>
            </div>
            <div>
              <dt>Sai vài bit</dt>
              <dd className="c-warn">{battery.partial}</dd>
            </div>
            <div>
              <dt>Hỏng</dt>
              <dd className="c-danger">{battery.broken}</dd>
            </div>
          </dl>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Phép tấn công</th>
                  <th>Nhóm</th>
                  <th className="num">Bit sai</th>
                  <th>Kết quả</th>
                </tr>
              </thead>
              <tbody>
                {battery.rows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.name}</td>
                    <td className="muted">{r.group}</td>
                    <td className="num mono">{pct(r.ber)}</td>
                    <td><StatusTag status={r.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            {battery.encrypted
              ? "Nội dung có mật khẩu: chỉ cần sai 1 bit là không giải mã được, nên không có mức “sai vài bit”."
              : "“Sai vài bit” nghĩa là tỉ lệ bit sai không quá 5%: chữ có thể lệch vài ký tự, logo có vài chấm nhiễu."}{" "}
            · {battery.n_bits} bit · {(battery.elapsed_ms / 1000).toFixed(1)} giây
          </p>
        </section>
      )}
    </div>
  );
}
