import { type FormEvent, useEffect, useMemo, useState } from "react";
import { api, type CapacityResult, type PayloadKind, type Session } from "../api";
import { hide, type Content, type HideResult } from "../lib/codec";
import { DEFAULT_EDIT, encodeLogo, loadLogo, type EncodedLogo, type LogoEdit, type LogoInvert, type LogoMode } from "../lib/logo";
import { canEncryptLocally, overhead } from "../lib/payload";
import type { NewEntry } from "../lib/history";
import { DEFAULT_PRESET, PRESETS, PSNR_WARN, type PresetId } from "../lib/presets";
import { writeZip } from "../lib/zip";
import { base64ToBlob, downloadBlob, formatBytes, nf, passwordStrength, randomPassword, stem, utf8Length } from "../utils";
import { Alert } from "./Alert";
import { CapacityCard, maxBytesAt } from "./CapacityCard";
import { LogoEditor } from "./LogoEditor";
import { Dropzone } from "./Dropzone";

interface Props {
  maxRedundancy: number;
  /** Báo kết quả lên để ghi vào lịch sử (phiên hoặc tài khoản). */
  onResult: (e: NewEntry) => void;
  /** Đã đăng nhập và bật tự lưu: máy chủ lưu luôn kết quả. */
  saveToAccount: boolean;
  onSend: (target: "attack" | "compare", s: Session) => void;
}

const DETECT = { low: "THẤP", medium: "TRUNG BÌNH", high: "CAO" } as const;

const KINDS: { id: PayloadKind; label: string }[] = [
  { id: "text", label: "Chữ" },
  { id: "logo", label: "Logo" },
  { id: "file", label: "File" },
];

const LOGO_SIZES = [
  { side: 32, label: "Nhỏ · 32 px (bền nhất)" },
  { side: 48, label: "Vừa · 48 px (khuyên dùng)" },
  { side: 64, label: "Lớn · 64 px" },
  { side: 96, label: "Rất lớn · 96 px" },
  { side: 0, label: "Tối đa ảnh chứa được (kém bền nhất)" },
];

export function EmbedPanel({ maxRedundancy, onSend, onResult, saveToAccount }: Props) {
  const [image, setImage] = useState<File | null>(null);
  const [kind, setKind] = useState<PayloadKind>("text");
  const [message, setMessage] = useState("");
  const [logo, setLogo] = useState<File | null>(null);
  const [logoMode, setLogoMode] = useState<LogoMode>("binary");
  const [logoInvert, setLogoInvert] = useState<LogoInvert>("auto");
  const [logoSide, setLogoSide] = useState(48);
  const [logoEdit, setLogoEdit] = useState<LogoEdit>(DEFAULT_EDIT);
  const [logoBmp, setLogoBmp] = useState<ImageBitmap | null>(null);
  const [logoLoadError, setLogoLoadError] = useState<string | null>(null);
  const [secretFile, setSecretFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [encOpen, setEncOpen] = useState(false); // mục Mã hoá (nâng cao): đóng sẵn, không đặt mật khẩu thì không mã hoá
  const [preset, setPreset] = useState<PresetId>(DEFAULT_PRESET.id);
  const [redundancy, setRedundancy] = useState<number>(DEFAULT_PRESET.redundancy);
  const [delta, setDelta] = useState<number>(DEFAULT_PRESET.delta);
  const [autoRedundancy, setAutoRedundancy] = useState<boolean>(DEFAULT_PRESET.auto);
  const [storeThumbnail, setStoreThumbnail] = useState(true);
  const [useAco, setUseAco] = useState(true);
  const [advanced, setAdvanced] = useState(false);

  const [cap, setCap] = useState<CapacityResult | null>(null);
  const [capError, setCapError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [out, setOut] = useState<HideResult | null>(null);

  // Số khối của ảnh chỉ phụ thuộc ảnh: hỏi máy chủ một lần, đổi mức bền vững thì tự tính lại.
  useEffect(() => {
    setCap(null);
    setCapError(null);
    if (!image) return;
    const ctl = new AbortController();
    const t = setTimeout(() => {
      api.capacity(image, 1, ctl.signal).then(setCap).catch((e) => {
        if (!ctl.signal.aborted) setCapError(e.message);
      });
    }, 250);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  }, [image]);

  useEffect(() => setOut(null), [image, kind]);

  // Giải mã file logo một lần; mọi chỉnh sửa sau đó chạy trên bitmap này.
  useEffect(() => {
    setLogoBmp(null);
    setLogoLoadError(null);
    setLogoEdit(DEFAULT_EDIT);
    setLogoInvert("auto");
    if (!logo) return;
    let alive = true;
    let bmp: ImageBitmap | null = null;
    loadLogo(logo).then(
      (b) => {
        bmp = b;
        if (alive) setLogoBmp(b);
        else b.close();
      },
      (e) => alive && setLogoLoadError(e.message),
    );
    return () => {
      alive = false;
      bmp?.close();
    };
  }, [logo]);

  const maxBytes = cap ? maxBytesAt(cap.capacity_bits, redundancy, !!password) : null;

  // Logo đúng như sẽ được giấu, dựng lại mỗi khi người dùng chỉnh.
  const logoEnc = useMemo<{ enc: EncodedLogo | null; error: string | null }>(() => {
    if (kind !== "logo" || !logoBmp || maxBytes === null) return { enc: null, error: null };
    try {
      return { enc: encodeLogo(logoBmp, maxBytes, logoMode, logoInvert, logoSide, logoEdit), error: null };
    } catch (e) {
      return { enc: null, error: (e as Error).message };
    }
  }, [kind, logoBmp, maxBytes, logoMode, logoInvert, logoSide, logoEdit]);
  const logoBytes = logoEnc.enc ? logoEnc.enc.body.length : 0;
  const logoRepeat =
    cap && logoEnc.enc
      ? autoRedundancy
        ? Math.max(redundancy, Math.min(maxRedundancy, Math.floor(cap.capacity_bits / ((logoBytes + overhead(!!password)) * 8))))
        : redundancy
      : null;
  const used =
    kind === "text"
      ? utf8Length(message)
      : kind === "file" && secretFile
        ? secretFile.size + 1 + Math.min(255, utf8Length(secretFile.name))
        : kind === "logo"
          ? logoBytes
          : 0;
  const over = kind !== "logo" && maxBytes !== null && used > maxBytes;
  const pct = maxBytes ? Math.min(100, (used / Math.max(1, maxBytes)) * 100) : 0;
  const hasContent = kind === "text" ? !!message : kind === "logo" ? !!logoEnc.enc : !!secretFile;
  const ready = !!image && !!cap && hasContent && !over;
  const local = canEncryptLocally();

  const result = out?.result ?? null;
  const originalUrl = useMemo(() => (image ? URL.createObjectURL(image) : null), [image]);
  const stegoBlob = useMemo(() => (result ? base64ToBlob(result.stego_png_base64, "image/png") : null), [result]);
  const stegoUrl = useMemo(() => (stegoBlob ? URL.createObjectURL(stegoBlob) : null), [stegoBlob]);
  useEffect(() => () => void (originalUrl && URL.revokeObjectURL(originalUrl)), [originalUrl]);
  useEffect(() => () => void (stegoUrl && URL.revokeObjectURL(stegoUrl)), [stegoUrl]);

  function choosePreset(id: PresetId) {
    setPreset(id);
    const p = PRESETS.find((x) => x.id === id);
    if (p) {
      setRedundancy(p.redundancy);
      setDelta(p.delta);
      setAutoRedundancy(p.auto);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || !image || !cap) return;
    const content: Content =
      kind === "text"
        ? { kind, text: message }
        : kind === "logo"
          ? { kind, encoded: logoEnc.enc!, mode: logoMode }
          : { kind, file: secretFile! };
    setBusy(true);
    setError(null);
    setOut(null);
    try {
      const done = await hide({
        image,
        content,
        password,
        redundancy,
        autoRedundancy,
        delta,
        storeThumbnail,
        useAco,
        save: saveToAccount ? { name: stem(image.name) } : undefined,
      });
      setOut(done);
      const r = done.result;
      onResult({
        name: stem(image.name),
        stego: base64ToBlob(r.stego_png_base64, "image/png"),
        keys: new Blob([done.keys as BlobPart]),
        kind: r.kind,
        encrypted: r.encrypted,
        width: r.width,
        height: r.height,
        psnr: r.psnr_db,
        redundancy: r.redundancy,
        savedId: r.saved_id,
        saveError: r.save_error,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const base = image ? stem(image.name) : "anh";
  const stegoName = `${base}_apex.png`;
  const keysName = `${base}_khoa${out?.keysExt ?? ".npz"}`;

  async function downloadZip() {
    if (!result || !stegoBlob) return;
    downloadBlob(
      writeZip([
        { name: stegoName, data: new Uint8Array(await stegoBlob.arrayBuffer()) },
        { name: keysName, data: out!.keys },
      ]),
      `${base}_apex.zip`,
    );
  }

  function send(target: "attack" | "compare") {
    if (!image || !result || !stegoBlob) return;
    onSend(target, {
      original: image,
      stego: new File([stegoBlob], stegoName, { type: "image/png" }),
      keys: new File([out!.plainKeys as BlobPart], `${base}_khoa.npz`),
      password,
    });
  }

  const noun = kind === "logo" ? "logo" : kind === "file" ? "file" : "tin";

  return (
    <form className="panel" onSubmit={submit}>
      <div className="grid-2">
        <div className="stack">
          <Dropzone label="1. Ảnh gốc" hint="PNG, JPEG, WEBP, BMP…" accept="image/*" file={image} onFile={setImage} preview />
          {cap && <CapacityCard cap={cap} redundancy={redundancy} encrypted={!!password} />}
          {image && !cap && !capError && <p className="muted small">Đang tính sức chứa của ảnh…</p>}
          {capError && <Alert kind="error">{capError}</Alert>}
        </div>

        <div className="stack">
          <div className="segmented" role="radiogroup" aria-label="Nội dung cần giấu">
            {KINDS.map((k) => (
              <button key={k.id} type="button" role="radio" aria-checked={kind === k.id} className={kind === k.id ? "is-active" : ""} onClick={() => setKind(k.id)}>
                Giấu {k.label.toLowerCase()}
              </button>
            ))}
          </div>

          {kind === "text" && (
            <div className="field">
              <label className="field-label" htmlFor="msg">2. Thông điệp cần giấu</label>
              <textarea id="msg" rows={5} value={message} placeholder="Ví dụ: © PDK 2026 — Bản quyền thuộc về…" onChange={(e) => setMessage(e.target.value)} />
            </div>
          )}

          {kind === "logo" && (
            <>
              <Dropzone
                label="2. Logo cần giấu"
                hint="PNG nền trong suốt hoặc nền trắng là tốt nhất"
                accept="image/*"
                file={logo}
                onFile={(f) => {
                  setLogo(f);
                  setOut(null);
                }}
              />
              {logoLoadError && <Alert kind="error">{logoLoadError}</Alert>}
              <label className="field">
                <span className="field-label">Kích thước logo</span>
                <select value={logoSide} onChange={(e) => setLogoSide(Number(e.target.value))}>
                  {LOGO_SIZES.map((s) => (
                    <option key={s.side} value={s.side}>{s.label}</option>
                  ))}
                </select>
                <span className="muted small">
                  Logo càng nhỏ thì càng được lặp lại nhiều lần trong ảnh, nên càng khó bị phá.
                </span>
              </label>
              <label className="field">
                <span className="field-label">Kiểu logo</span>
                <select value={logoMode} onChange={(e) => setLogoMode(e.target.value as LogoMode)}>
                  <option value="binary">Đen trắng (khuyên dùng)</option>
                  <option value="gray">Ảnh xám 256 mức (tốn gấp 8 lần chỗ)</option>
                </select>
              </label>
              {logoBmp && (
                <LogoEditor
                  bmp={logoBmp}
                  mode={logoMode}
                  edit={logoEdit}
                  onEdit={setLogoEdit}
                  invert={logoInvert}
                  onInvert={setLogoInvert}
                  encoded={logoEnc.enc}
                  maxBody={maxBytes}
                  maxSide={logoSide}
                  note={
                    logoEnc.enc && maxBytes !== null
                      ? `Logo chiếm ${formatBytes(logoBytes)} trên tối đa ${formatBytes(maxBytes)}${logoRepeat ? `, sẽ được lặp ×${logoRepeat} trong ảnh` : ""}.`
                      : !image
                        ? "Chọn ảnh gốc ở bên trái để xem logo sau khi thu nhỏ."
                        : undefined
                  }
                />
              )}
              {logoEnc.error && <Alert kind="error">{logoEnc.error}</Alert>}
            </>
          )}

          {kind === "file" && (
            <Dropzone
              label="2. File cần giấu"
              hint="File nhỏ bất kỳ: JSON, TXT, mã serial…"
              accept="*/*"
              file={secretFile}
              onFile={(f) => {
                setSecretFile(f);
                setOut(null);
              }}
            />
          )}

          {kind !== "logo" && (
            <div className="field">
              <div className="meter" aria-hidden="true">
                <div className={`meter-bar${over ? " is-over" : ""}`} style={{ width: `${pct}%` }} />
              </div>
              <div className={`small ${over ? "text-danger" : "muted"}`}>
                {kind === "file" ? formatBytes(used) : `${nf.format(used)} byte`}
                {maxBytes !== null
                  ? ` / tối đa ${kind === "file" ? formatBytes(maxBytes) : `${nf.format(maxBytes)} byte`}`
                  : image
                    ? " · đang tính dung lượng…"
                    : " · chọn ảnh để xem dung lượng"}
                {over && " · quá lớn, hãy giảm mức bền vững hoặc dùng ảnh lớn hơn"}
              </div>
            </div>
          )}

          <div className="field">
            <button type="button" className="link-btn" aria-expanded={encOpen} onClick={() => setEncOpen((v) => !v)}>
              {encOpen ? "Ẩn mục mã hoá" : password ? "Mã hoá bằng mật khẩu: đang bật" : "Mã hoá bằng mật khẩu (nâng cao, không bắt buộc)"}
            </button>
            {encOpen && (
              <div className="advanced">
                <span className="field-label">Mã hoá bằng mật khẩu</span>
                <span className="muted small">Không bắt buộc. Để trống thì nội dung được giấu mà không mã hoá.</span>
                <label className="field-label" htmlFor="pw">Mật khẩu mã hoá</label>
            <div className="input-group">
              <input id="pw" type={showPw ? "text" : "password"} value={password} autoComplete="new-password" placeholder="Mật khẩu để mã hoá nội dung và file khoá" onChange={(e) => setPassword(e.target.value)} />
              <button type="button" className="btn btn-ghost" onClick={() => setShowPw((v) => !v)}>
                {showPw ? "Ẩn" : "Hiện"}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                title="Tạo mật khẩu ngẫu nhiên 20 ký tự"
                onClick={() => {
                  setPassword(randomPassword());
                  setShowPw(true);
                }}
              >
                Tạo
              </button>
            </div>
            {password ? (
              <>
                <div className="strength" data-level={passwordStrength(password)}>
                  <span className="strength-bars" aria-hidden="true"><i /><i /><i /><i /></span>
                  <span className="muted">{["", "Yếu, dễ bị dò", "Trung bình", "Khá", "Mạnh"][passwordStrength(password)]}</span>
                </div>
                <span className="muted small">
                  {local
                    ? "Nội dung và file khoá được mã hoá AES-256 ngay trong trình duyệt. Mật khẩu không được gửi lên máy chủ. Quên mật khẩu thì không ai khôi phục được."
                    : "Trang đang chạy qua HTTP nên trình duyệt không mã hoá được: mật khẩu sẽ được gửi lên máy chủ để mã hoá. Hãy dùng HTTPS."}
                </span>
              </>
            ) : (
              <span className="small muted">
                Nhập mật khẩu, hoặc bấm Tạo để có mật khẩu ngẫu nhiên. Nội dung và file khoá sẽ được mã hoá AES-256.
              </span>
            )}
              </div>
            )}
          </div>
        </div>
      </div>

      <fieldset className="field">
        <legend className="field-label">3. Mức độ bền vững</legend>
        <div className="presets">
          {PRESETS.map((p) => (
            <label key={p.id} className={`preset${preset === p.id ? " is-active" : ""}`}>
              <input type="radio" name="preset" checked={preset === p.id} onChange={() => choosePreset(p.id)} />
              <strong>{p.name}</strong>
              <span>{p.desc}</span>
            </label>
          ))}
        </div>
        <label className="check">
          <input type="checkbox" checked={autoRedundancy} onChange={(e) => setAutoRedundancy(e.target.checked)} />
          Dùng hết chỗ trống của ảnh để lặp lại nội dung (bền hơn nhiều, nhưng dễ bị phát hiện hơn)
        </label>
        <button type="button" className="link-btn" onClick={() => setAdvanced((v) => !v)}>
          {advanced ? "Ẩn tuỳ chọn nâng cao" : "Tuỳ chọn nâng cao"}
        </button>
        {advanced && (
          <div className="advanced">
            <label className="field">
              <span className="field-label">Độ dự phòng tối thiểu: {redundancy}</span>
              <input
                type="range"
                min={1}
                max={maxRedundancy}
                value={redundancy}
                onChange={(e) => {
                  setPreset("custom");
                  setRedundancy(Number(e.target.value));
                }}
              />
              <span className="muted small">Mỗi bit được lặp vào ít nhất bấy nhiêu khối. Cao hơn = bền hơn, giấu được ít hơn.</span>
            </label>
            <label className="field">
              <span className="field-label">Cường độ nhúng (delta): {delta}</span>
              <input
                type="range"
                min={4}
                max={48}
                value={delta}
                onChange={(e) => {
                  setPreset("custom");
                  setDelta(Number(e.target.value));
                }}
              />
              <span className="muted small">Cao hơn = bền hơn nhưng ảnh thay đổi nhiều hơn (PSNR giảm).</span>
            </label>
            <label className="check">
              <input type="checkbox" checked={storeThumbnail} onChange={(e) => setStoreThumbnail(e.target.checked)} />
              Lưu ảnh thu nhỏ trong khoá (để đọc được cả khi ảnh bị cắt, co giãn, xoay)
            </label>
            <label className="check">
              <input type="checkbox" checked={useAco} onChange={(e) => setUseAco(e.target.checked)} />
              Dùng tối ưu đàn kiến (ACO) để chọn vị trí nhúng
            </label>
          </div>
        )}
      </fieldset>

      {error && <Alert kind="error">{error}</Alert>}

      <div className="actions">
        <button className="btn btn-primary" disabled={!ready || busy}>
          {busy ? <span className="spinner" aria-hidden="true" /> : null}
          {busy ? "Đang giấu…" : `Giấu ${noun} vào ảnh`}
        </button>
      </div>

      {out && result && stegoBlob && (
        <section className="result" aria-live="polite">
          <h2>Đã giấu {noun} thành công</h2>
          <div className="compare">
            <figure>
              {originalUrl && <img src={originalUrl} alt="Ảnh gốc" />}
              <figcaption>Ảnh gốc</figcaption>
            </figure>
            <figure>
              {stegoUrl && <img src={stegoUrl} alt="Ảnh đã giấu tin" />}
              <figcaption>Ảnh đã giấu tin</figcaption>
            </figure>
          </div>
          {out.logo && (
            <div className="logo-result">
              <img src={out.logo.url} alt="Logo sẽ đọc ra" className="pixelated" />
              <p className="muted small">
                Logo khi đọc ra sẽ trông như thế này ({out.logo.width} × {out.logo.height} px).
              </p>
            </div>
          )}
          <dl className="stats">
            <div>
              <dt>PSNR</dt>
              <dd>{result.psnr_db === null ? "∞" : `${result.psnr_db.toFixed(1)} dB`}</dd>
            </div>
            <div>
              <dt>Lặp lại</dt>
              <dd>×{result.redundancy}</dd>
            </div>
            <div>
              <dt>Đã dùng</dt>
              <dd>{(result.usage_ratio * 100).toFixed(1)}%</dd>
            </div>
            {result.detect_level && (
              <div>
                <dt>Khả năng bị phát hiện</dt>
                <dd className={result.detect_level === "low" ? "" : "text-danger"}>{DETECT[result.detect_level]}</dd>
              </div>
            )}
            <div>
              <dt>Mã hoá</dt>
              <dd>{result.encrypted ? (out.local ? "AES · TẠI MÁY" : "AES-256") : "KHÔNG"}</dd>
            </div>
          </dl>
          <div className="actions">
            <button type="button" className="btn btn-primary" onClick={downloadZip}>
              Tải ảnh + khoá (.zip)
            </button>
            <button type="button" className="btn" onClick={() => downloadBlob(stegoBlob, stegoName)}>
              Chỉ ảnh (.png)
            </button>
            <button type="button" className="btn" onClick={() => downloadBlob(new Blob([out.keys as BlobPart]), keysName)}>
              Chỉ khoá ({out.keysExt} · {formatBytes(out.keys.length)})
            </button>
          </div>
          <div className="actions">
            <button type="button" className="btn" onClick={() => send("compare")}>
              Xem điểm ảnh đã thay đổi
            </button>
            <button type="button" className="btn" onClick={() => send("attack")}>
              Thử tấn công ảnh này
            </button>
          </div>
          {result.psnr_db !== null && result.psnr_db < PSNR_WARN && (
            <Alert kind="warn">
              PSNR {result.psnr_db.toFixed(1)} dB là thấp (dưới {PSNR_WARN} dB): nhiễu có thể nhìn thấy bằng mắt và ảnh dễ
              bị công cụ phân tích phát hiện là có giấu tin. Nếu cần kín đáo hơn, hãy chọn mức bền vững thấp hơn, bỏ
              tuỳ chọn "Dùng hết chỗ trống", hoặc giảm cường độ nhúng.
            </Alert>
          )}
          {result.detect_level && result.detect_score != null && (
            <Alert kind={result.detect_level === "low" ? "ok" : "warn"}>
              <strong>Khả năng bị phát hiện: {DETECT[result.detect_level].toLowerCase()}.</strong>{" "}
              {result.detect_level === "low"
                ? "Bộ dò biết thuật toán APEX không phân biệt được ảnh này với ảnh thường."
                : result.detect_level === "medium"
                  ? "Bộ dò biết thuật toán APEX nhận ra dấu vết yếu trong ảnh này."
                  : "Bộ dò biết thuật toán APEX nhận ra rõ ảnh này có giấu tin."}{" "}
              Dấu vết đo được {(result.detect_score * 100).toFixed(1)}% (ảnh gốc {((result.detect_baseline ?? 0) * 100).toFixed(1)}%,
              ngưỡng nhiễu {((result.detect_noise ?? 0) * 100).toFixed(1)}%).
              {result.detect_level !== "low" &&
                " Muốn kín hơn: chọn mức Nhẹ, bỏ \"Dùng hết chỗ trống\", rút ngắn nội dung hoặc dùng ảnh lớn hơn."}
            </Alert>
          )}
          {out.keysSealed && (
            <Alert kind="ok">
              File khoá <code>{out.keysExt}</code> đã được mã hoá bằng mật khẩu của bạn. Khi đọc tin cần cả ảnh, file
              khoá và mật khẩu.
            </Alert>
          )}
          <Alert kind="warn">
            Hãy giữ <strong>file khoá</strong> cẩn thận: thiếu nó thì không đọc lại được nội dung đã giấu. Khi gửi cho
            người khác, nên gửi ảnh và khoá qua hai kênh riêng. Nên chia sẻ ảnh ở dạng PNG.
          </Alert>
        </section>
      )}
    </form>
  );
}
