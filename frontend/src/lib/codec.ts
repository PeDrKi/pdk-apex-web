// Cầu nối giữa giao diện và API: đóng gói/mã hoá nội dung trong trình duyệt trước
// khi gửi, và giải mã kết quả thô nhận về. Máy chủ chỉ thấy dữ liệu đã đóng gói.
import { api, type EmbedOptions, type EmbedResult, type ExtractParams, type ExtractResult } from "../api";
import { decodeLogo, type EncodedLogo, type LogoMode } from "./logo";
import {
  canEncryptLocally,
  decodePayload,
  encodePayload,
  FORMAT,
  packFile,
  unpackFile,
  type PayloadKind,
} from "./payload";

export type Content =
  | { kind: "text"; text: string }
  /** Logo đã được dựng sẵn trong trình duyệt (sau khi người dùng chỉnh sửa). */
  | { kind: "logo"; encoded: EncodedLogo; mode: LogoMode }
  | { kind: "file"; file: File };

export interface HideParams extends Omit<EmbedOptions, "kind"> {
  content: Content;
  password: string;
}

export interface HideResult {
  result: EmbedResult;
  logo: { url: string; width: number; height: number } | null;
  /** true = mật khẩu/nội dung không rời trình duyệt ở dạng gốc. */
  local: boolean;
}

export async function hide(p: HideParams): Promise<HideResult> {
  const { content, password, ...opts } = p;
  const base = { ...opts, kind: content.kind };

  if (password && !canEncryptLocally()) {
    const result = await api.embedServer({
      ...base,
      password,
      message: content.kind === "text" ? content.text : "",
      // Gửi đúng logo đã chỉnh (ảnh xem trước, nét tối trên nền trắng) để máy chủ không dựng lại khác đi.
      logo:
        content.kind === "logo"
          ? new File([b64ToBytes(content.encoded.previewUrl.split(",")[1]) as BlobPart], "logo.png", { type: "image/png" })
          : null,
      logoMode: content.kind === "logo" ? content.mode : "binary",
      logoInvert: content.kind === "logo" ? "yes" : "auto",
      logoMaxSide: 0,
      file: content.kind === "file" ? content.file : null,
    });
    const logo = result.logo_preview_base64
      ? {
          url: `data:image/png;base64,${result.logo_preview_base64}`,
          width: result.logo_width ?? 0,
          height: result.logo_height ?? 0,
        }
      : null;
    return { result, logo, local: false };
  }

  let body: Uint8Array;
  let logo: HideResult["logo"] = null;
  let logoHeader: number[] | undefined;
  if (content.kind === "text") {
    body = new TextEncoder().encode(content.text);
  } else if (content.kind === "file") {
    body = packFile(content.file.name, new Uint8Array(await content.file.arrayBuffer()));
  } else {
    const enc = content.encoded;
    body = enc.body;
    logoHeader = enc.header;
    logo = { url: enc.previewUrl, width: enc.width, height: enc.height };
  }
  const payload = await encodePayload(body, content.kind, password);
  const result = await api.embedPacked({ ...base, payload, encrypted: !!password, logoHeader });
  return { result, logo, local: true };
}

export interface Revealed {
  kind: PayloadKind;
  integrityOk: boolean | null;
  encrypted: boolean;
  text?: string;
  logo?: { url: string; width: number; height: number };
  file?: { name: string; data: Uint8Array };
}

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** Kết quả đã được máy chủ giải mã (đường dự phòng). */
function fromServer(r: ExtractResult): Revealed {
  const base = { kind: r.kind, integrityOk: r.integrity_ok, encrypted: r.encrypted };
  if (r.kind === "logo" && r.logo_png_base64)
    return {
      ...base,
      logo: { url: `data:image/png;base64,${r.logo_png_base64}`, width: r.logo_width ?? 0, height: r.logo_height ?? 0 },
    };
  if (r.kind === "file" && r.file_base64)
    return { ...base, file: { name: r.file_name || "file.bin", data: b64ToBytes(r.file_base64) } };
  return { ...base, text: r.message };
}

/** Giải mã kết quả thô (raw) ngay trong trình duyệt. */
export async function reveal(r: ExtractResult, password: string): Promise<Revealed> {
  if (!r.payload_base64) return fromServer(r);
  const data = b64ToBytes(r.payload_base64);
  if (r.payload_format !== FORMAT) {
    // Khoá tạo bằng CLI apexmark: bit thô là UTF-8, không có mã kiểm tra.
    return { kind: "text", integrityOk: null, encrypted: false, text: new TextDecoder().decode(data) };
  }
  const dec = await decodePayload(data, password, { kind: r.kind, encrypted: r.encrypted });
  const base = { kind: dec.kind, integrityOk: dec.integrityOk, encrypted: dec.encrypted };
  if (dec.kind === "logo") return { ...base, logo: decodeLogo(dec.body, r.logo_header) };
  if (dec.kind === "file") return { ...base, file: unpackFile(dec.body) };
  return { ...base, text: new TextDecoder().decode(dec.body) };
}

/** Không có Web Crypto thì phải nhờ máy chủ giải mã nội dung có mật khẩu. */
export const needsServerDecrypt = (r: ExtractResult) => r.encrypted && !canEncryptLocally();

export async function extractAndReveal(
  p: Omit<ExtractParams, "raw">,
): Promise<{ raw: ExtractResult; revealed: Revealed }> {
  const raw = await api.extract({ ...p, password: "", raw: true });
  if (needsServerDecrypt(raw)) {
    const full = await api.extract({ ...p, raw: false });
    return { raw: full, revealed: fromServer(full) };
  }
  return { raw, revealed: await reveal(raw, p.password) };
}
