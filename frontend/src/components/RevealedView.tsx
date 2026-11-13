import { useState } from "react";
import type { Revealed } from "../lib/codec";
import { downloadBlob, formatBytes } from "../utils";

/** Hiển thị nội dung đã đọc ra: chữ, logo hoặc file. */
export function RevealedView({ value, caption }: { value: Revealed; caption?: string }) {
  const [copied, setCopied] = useState(false);

  if (value.logo) {
    const logo = value.logo;
    return (
      <>
        <div className="logo-result">
          <img src={logo.url} alt="Logo đọc được" className="pixelated" />
          <p className="muted small">
            {caption ?? "Logo đọc được"} · {logo.width} × {logo.height} px
          </p>
        </div>
        <div className="actions">
          <a className="btn" href={logo.url} download="logo_doc_duoc.png">
            Tải logo (.png)
          </a>
        </div>
      </>
    );
  }

  if (value.file) {
    const file = value.file;
    // Bỏ mọi thành phần đường dẫn trong tên file nhúng trong ảnh.
    const safe = file.name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_").replace(/^\.+/, "") || "file.bin";
    return (
      <>
        <div className="file-result">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zm0 0v5h5" />
          </svg>
          <div>
            <strong>{safe}</strong>
            <span className="muted small">{caption ?? "File đọc được"} · {formatBytes(file.data.length)}</span>
          </div>
        </div>
        <div className="actions">
          <button type="button" className="btn" onClick={() => downloadBlob(new Blob([file.data as BlobPart]), safe)}>
            Tải file về
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      <pre className="message">{value.text}</pre>
      <div className="actions">
        <button
          type="button"
          className="btn"
          onClick={async () => {
            await navigator.clipboard.writeText(value.text ?? "");
            setCopied(true);
          }}
        >
          {copied ? "Đã sao chép" : "Sao chép"}
        </button>
      </div>
    </>
  );
}
