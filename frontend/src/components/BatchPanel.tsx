import { useRef, useState } from "react";
import { ApiError } from "../api";
import { hide } from "../lib/codec";
import type { NewEntry } from "../lib/history";
import { canEncryptLocally } from "../lib/payload";
import { DEFAULT_PRESET, PRESETS } from "../lib/presets";
import { writeZip, type ZipEntry } from "../lib/zip";
import { base64ToBytes, downloadBlob, formatBytes, stem } from "../utils";
import { Alert } from "./Alert";

const MAX_FILES = 50;

type RowState = "wait" | "run" | "ok" | "fail";
interface Row {
  file: File;
  message: string;
  state: RowState;
  note: string;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Gọi lại khi máy chủ báo quá nhiều yêu cầu (429). */
async function withRetry<T>(fn: () => Promise<T>, onWait: (s: number) => void): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn();
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 429 || attempt >= 5) throw e;
      for (let s = 20; s > 0; s--) {
        onWait(s);
        await sleep(1000);
      }
    }
  }
}

interface Props {
  onResult: (e: NewEntry) => void | Promise<void>;
  saveToAccount: boolean;
}

export function BatchPanel({ onResult, saveToAccount }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [template, setTemplate] = useState("© PDK 2026 · {ten} · #{stt}");
  const [perLine, setPerLine] = useState(false);
  const [password, setPassword] = useState("");
  const [noEncrypt, setNoEncrypt] = useState(false);
  const [presetId, setPresetId] = useState<(typeof PRESETS)[number]["id"]>(DEFAULT_PRESET.id);
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zip, setZip] = useState<Blob | null>(null);
  const stop = useRef(false);

  const lines = template.split("\n").filter((l) => l.trim());

  function messageFor(f: File, i: number): string {
    const src = perLine ? (lines[i] ?? "") : template;
    return src.replaceAll("{ten}", stem(f.name)).replaceAll("{stt}", String(i + 1).padStart(3, "0"));
  }

  function pick(list: FileList | null) {
    if (!list) return;
    const imgs = [...list].filter((f) => f.type.startsWith("image/")).slice(0, MAX_FILES);
    setFiles(imgs);
    setRows([]);
    setZip(null);
    setError(list.length > MAX_FILES ? `Chỉ lấy ${MAX_FILES} ảnh đầu tiên.` : null);
  }

  async function run() {
    const preset = PRESETS.find((p) => p.id === presetId)!;
    const work: Row[] = files.map((f, i) => ({ file: f, message: messageFor(f, i), state: "wait", note: "" }));
    if (work.some((r) => !r.message)) {
      setError("Có ảnh chưa có nội dung. Ở chế độ mỗi dòng một ảnh, số dòng phải bằng số ảnh.");
      return;
    }
    setError(null);
    setZip(null);
    setRows(work);
    setBusy(true);
    stop.current = false;
    const entries: ZipEntry[] = [];
    const log = ["file,noi_dung,so_bit,lap_lai,psnr_db"];
    const names = new Set<string>();
    const save = saveToAccount; // chốt lựa chọn lúc bắt đầu chạy
    const update = (i: number, patch: Partial<Row>) =>
      setRows((prev) => prev.map((r, j) => (j === i ? { ...r, ...patch } : r)));

    for (let i = 0; i < work.length && !stop.current; i++) {
      const { file, message } = work[i];
      update(i, { state: "run", note: "" });
      try {
        const wait = (s: number) => update(i, { note: `Máy chủ đang bận, thử lại sau ${s} giây` });
        const done = await withRetry(
          () =>
            hide({
              image: file,
              content: { kind: "text", text: message },
              password,
              redundancy: preset.redundancy,
              save: save ? { name: stem(file.name) } : undefined,
              autoRedundancy: preset.auto,
              delta: preset.delta,
              storeThumbnail: true,
              useAco: true,
            }),
          wait,
        );
        const { result } = done;
        let base = stem(file.name);
        for (let n = 2; names.has(base); n++) base = `${stem(file.name)}_${n}`;
        names.add(base);
        const stegoBytes = base64ToBytes(result.stego_png_base64);
        const keysBytes = done.keys;
        entries.push({ name: `${base}_apex.png`, data: stegoBytes }, { name: `khoa/${base}_khoa${done.keysExt}`, data: keysBytes });
        // Chờ lưu xong mới sang ảnh kế tiếp để không dồn yêu cầu lên máy chủ.
        await onResult({
          name: base,
          stego: new Blob([stegoBytes as BlobPart], { type: "image/png" }),
          keys: new Blob([keysBytes as BlobPart]),
          kind: result.kind,
          encrypted: result.encrypted,
          width: result.width,
          height: result.height,
          psnr: result.psnr_db,
          redundancy: result.redundancy,
          savedId: result.saved_id,
          saveError: result.save_error,
        });
        const shown = password ? "(đã mã hoá)" : message.replaceAll('"', '""');
        log.push(`"${base}_apex.png","${shown}",${result.n_bits},${result.redundancy},${result.psnr_db ?? ""}`);
        update(i, { state: "ok", note: `×${result.redundancy} · ${result.psnr_db?.toFixed(1) ?? "∞"} dB` });
      } catch (e) {
        update(i, { state: "fail", note: (e as Error).message });
      }
    }
    if (entries.length) {
      entries.push({ name: "danh_sach.csv", data: new TextEncoder().encode("﻿" + log.join("\r\n")) });
      setZip(writeZip(entries));
    }
    setBusy(false);
  }

  const done = rows.filter((r) => r.state === "ok").length;
  const failed = rows.filter((r) => r.state === "fail").length;

  return (
    <div className="panel">
      <p className="muted lead">
        Giấu tin vào nhiều ảnh một lượt, mỗi ảnh một nội dung riêng. Hợp để đánh dấu cả bộ thẻ bài hay bộ ảnh game.
      </p>

      <div className="field">
        <span className="field-label">1. Chọn ảnh (tối đa {MAX_FILES})</span>
        <div
          className={`dropzone dropzone-slim${files.length ? " has-file" : ""}`}
          role="button"
          tabIndex={0}
          onClick={() => input.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            pick(e.dataTransfer.files);
          }}
        >
          {files.length ? (
            <div className="dropzone-file">
              <strong>{files.length} ảnh đã chọn</strong>
              <span>{formatBytes(files.reduce((n, f) => n + f.size, 0))}</span>
            </div>
          ) : (
            <div className="dropzone-text">
              <strong>Kéo thả nhiều ảnh hoặc bấm để chọn</strong>
              <span>PNG, JPEG, WEBP…</span>
            </div>
          )}
          <input ref={input} type="file" accept="image/*" multiple hidden onChange={(e) => pick(e.target.files)} />
        </div>
      </div>

      <div className="grid-2">
        <div className="field">
          <label className="field-label" htmlFor="tpl">2. Nội dung</label>
          <textarea id="tpl" rows={4} value={template} onChange={(e) => setTemplate(e.target.value)} />
          <span className="muted small">
            <code>{"{ten}"}</code> = tên file ảnh, <code>{"{stt}"}</code> = số thứ tự (001, 002…).
          </span>
          <label className="check">
            <input type="checkbox" checked={perLine} onChange={(e) => setPerLine(e.target.checked)} />
            Mỗi dòng là nội dung của một ảnh, theo thứ tự ({lines.length} dòng / {files.length} ảnh)
          </label>
        </div>
        <div className="stack">
          <label className="field">
            <span className="field-label">3. Mức độ bền vững</span>
            <select value={presetId} onChange={(e) => setPresetId(e.target.value as typeof presetId)}>
              {PRESETS.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </label>
          <div className="field">
            <label className="field-label" htmlFor="bpw">Mật khẩu chung (mã hoá cả nội dung và file khoá)</label>
            <input id="bpw" type="password" value={password} autoComplete="new-password" disabled={noEncrypt} onChange={(e) => setPassword(e.target.value)} />
            <label className="check">
              <input
                type="checkbox"
                checked={noEncrypt}
                onChange={(e) => {
                  setNoEncrypt(e.target.checked);
                  if (e.target.checked) setPassword("");
                }}
              />
              Không mã hoá (không khuyên dùng)
            </label>
            {noEncrypt && (
              <span className="small text-danger">
                Ai có ảnh và file khoá đều đọc được nội dung.
              </span>
            )}
            {password && !canEncryptLocally() && (
              <span className="muted small">Trang đang chạy qua HTTP nên mật khẩu sẽ được gửi lên máy chủ để mã hoá.</span>
            )}
          </div>
        </div>
      </div>

      {files.length > 0 && !rows.length && (
        <p className="muted small mono">Ví dụ ảnh đầu tiên: {messageFor(files[0], 0) || "(trống)"}</p>
      )}

      {error && <Alert kind="error">{error}</Alert>}

      <div className="actions">
        <button type="button" className="btn btn-primary" disabled={!files.length || !template.trim() || busy || (!password && !noEncrypt)} onClick={run}>
          {busy && <span className="spinner" aria-hidden="true" />}
          {busy ? `Đang giấu ${done + failed + 1}/${rows.length}…` : `Giấu tin vào ${files.length || ""} ảnh`}
        </button>
        {busy && (
          <button type="button" className="btn" onClick={() => (stop.current = true)}>
            Dừng
          </button>
        )}
        {zip && !busy && (
          <button type="button" className="btn btn-primary" onClick={() => downloadBlob(zip, "apex_hang_loat.zip")}>
            Tải tất cả (.zip · {formatBytes(zip.size)})
          </button>
        )}
      </div>

      {rows.length > 0 && (
        <section className="result" aria-live="polite">
          <h2>
            {done}/{rows.length} ảnh xong{failed ? ` · ${failed} lỗi` : ""}
          </h2>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Ảnh</th>
                  <th>Nội dung</th>
                  <th>Kết quả</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td className="mono">{r.file.name}</td>
                    <td className="cell-clip">{r.message}</td>
                    <td>
                      {r.state === "ok" && <span className="tag tag-intact">Xong</span>}
                      {r.state === "fail" && <span className="tag tag-broken">Lỗi</span>}
                      {r.state === "run" && <span className="tag tag-partial">Đang chạy</span>}
                      {r.state === "wait" && <span className="muted">Chờ</span>}
                      {r.note && <span className="muted small"> {r.note}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {zip && !busy && (
            <p className="muted small">
              Gói zip gồm các ảnh đã giấu tin, thư mục <code>khoa/</code> chứa file khoá của từng ảnh, và{" "}
              <code>danh_sach.csv</code> ghi nội dung đã giấu.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
