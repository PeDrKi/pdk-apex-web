import { useEffect, useId, useRef, useState } from "react";
import { formatBytes } from "../utils";

interface Props {
  label: string;
  hint: string;
  accept: string;
  file: File | null;
  onFile: (f: File | null) => void;
  preview?: boolean;
}

export function Dropzone({ label, hint, accept, file, onFile, preview }: Props) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!file || !preview) {
      setUrl(null);
      return;
    }
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file, preview]);

  return (
    <div className="field">
      <label htmlFor={id} className="field-label">{label}</label>
      <div
        className={`dropzone${drag ? " is-drag" : ""}${file ? " has-file" : ""}`}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          const f = e.dataTransfer.files?.[0];
          if (f) onFile(f);
        }}
        role="button"
        tabIndex={0}
      >
        {url ? (
          <img src={url} alt="" className="dropzone-preview" />
        ) : (
          <svg className="dropzone-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
          </svg>
        )}
        {file ? (
          <div className="dropzone-file">
            <strong>{file.name}</strong>
            <span>{formatBytes(file.size)}</span>
          </div>
        ) : (
          <div className="dropzone-text">
            <strong>Kéo thả hoặc bấm để chọn</strong>
            <span>{hint}</span>
          </div>
        )}
        {file && (
          <button
            type="button"
            className="link-btn"
            onClick={(e) => {
              e.stopPropagation();
              onFile(null);
              if (input.current) input.current.value = "";
            }}
          >
            Bỏ chọn
          </button>
        )}
        <input
          id={id}
          ref={input}
          type="file"
          accept={accept}
          hidden
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        />
      </div>
    </div>
  );
}
