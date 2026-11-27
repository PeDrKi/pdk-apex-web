import { useState } from "react";
import { DEFAULT_EDIT, type EncodedLogo, type LogoEdit, type LogoInvert, type LogoMode } from "../lib/logo";
import { LogoModal } from "./LogoModal";

interface Props {
  bmp: ImageBitmap;
  mode: LogoMode;
  edit: LogoEdit;
  onEdit: (e: LogoEdit) => void;
  invert: LogoInvert;
  onInvert: (v: LogoInvert) => void;
  /** Kết quả dựng với các chỉnh sửa hiện tại; null nếu dựng lỗi. */
  encoded: EncodedLogo | null;
  /** Số byte tối đa của logo và cạnh dài tối đa, để cửa sổ Sửa logo dựng lại đúng như lúc giấu. */
  maxBody: number | null;
  maxSide: number;
  note?: string;
}

/** Xem trước logo sẽ giấu. Mọi chỉnh sửa và vẽ tay nằm trong cửa sổ "Sửa logo". */
export function LogoEditor({ bmp, mode, edit, onEdit, invert, onInvert, encoded, maxBody, maxSide, note }: Props) {
  const [open, setOpen] = useState(false);
  const changed = JSON.stringify({ ...edit, manual: undefined }) !== JSON.stringify(DEFAULT_EDIT) || invert !== "auto" || !!edit.manual;

  return (
    <div className="logo-editor">
      <div className="logo-editor-head">
        <span className="field-label">Logo sẽ được giấu</span>
        {changed && (
          <button type="button" className="link-btn" onClick={() => { onEdit(DEFAULT_EDIT); onInvert("auto"); }}>
            Đặt lại
          </button>
        )}
      </div>
      <div className="logo-out">
        {encoded ? <img src={encoded.previewUrl} alt="Logo sẽ được giấu" className="pixelated" /> : <span className="muted small">—</span>}
      </div>
      <p className="muted small">
        {encoded ? `Sẽ giấu đúng như thế này · ${encoded.width} × ${encoded.height} px${edit.manual ? " · đã vẽ tay" : ""}` : "Chưa dựng được logo"}
      </p>
      {note && <p className="muted small">{note}</p>}
      <div className="actions">
        <button type="button" className="btn btn-sm" disabled={maxBody === null} onClick={() => setOpen(true)}>
          ✎ Sửa logo
        </button>
      </div>
      {open && maxBody !== null && (
        <LogoModal
          bmp={bmp}
          mode={mode}
          maxBody={maxBody}
          maxSide={maxSide}
          edit={edit}
          invert={invert}
          onClose={() => setOpen(false)}
          onApply={(e, i) => {
            onEdit(e);
            onInvert(i);
          }}
        />
      )}
    </div>
  );
}
