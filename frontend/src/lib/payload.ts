// Định dạng "apexweb-v1" — bản TypeScript của backend/app/payload.py.
// Mã hoá/giải mã chạy NGAY TRONG TRÌNH DUYỆT (Web Crypto): mật khẩu và nội dung
// gốc không bao giờ được gửi lên máy chủ.
//
//   flags(1) [salt(16) nonce(12)] body crc32(4, big-endian)
//   flags: bit0 = đã mã hoá, bit1 = logo, bit2 = file
import { crc32 } from "./crc32";

export type PayloadKind = "text" | "logo" | "file";

export const FORMAT = "apexweb-v1";
const FLAG_ENCRYPTED = 0x01;
const KIND_FLAG: Record<PayloadKind, number> = { text: 0, logo: 0x02, file: 0x04 };
const SALT_LEN = 16;
const NONCE_LEN = 12;
const TAG_LEN = 16;
const KDF_ITERATIONS = 600_000;

export const PLAIN_OVERHEAD = 1 + 4;
export const ENCRYPTED_OVERHEAD = PLAIN_OVERHEAD + SALT_LEN + NONCE_LEN + TAG_LEN;
export const overhead = (encrypted: boolean) => (encrypted ? ENCRYPTED_OVERHEAD : PLAIN_OVERHEAD);

/** Web Crypto chỉ có trên HTTPS hoặc localhost. */
export const canEncryptLocally = () => typeof crypto !== "undefined" && !!crypto.subtle;

export class WrongPasswordError extends Error {}
export class PayloadError extends Error {}

function concat(...parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

export async function deriveKey(password: string, salt: Uint8Array): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt: salt as BufferSource, iterations: KDF_ITERATIONS },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

export async function encodePayload(body: Uint8Array, kind: PayloadKind, password: string): Promise<Uint8Array> {
  let head: Uint8Array;
  if (password) {
    const salt = crypto.getRandomValues(new Uint8Array(SALT_LEN));
    const nonce = crypto.getRandomValues(new Uint8Array(NONCE_LEN));
    const key = await deriveKey(password, salt);
    const ct = new Uint8Array(
      await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce as BufferSource }, key, body as BufferSource),
    );
    head = concat(new Uint8Array([FLAG_ENCRYPTED | KIND_FLAG[kind]]), salt, nonce, ct);
  } else {
    head = concat(new Uint8Array([KIND_FLAG[kind]]), body);
  }
  const crc = new Uint8Array(4);
  new DataView(crc.buffer).setUint32(0, crc32(head));
  return concat(head, crc);
}

export interface DecodedPayload {
  body: Uint8Array;
  integrityOk: boolean;
  encrypted: boolean;
  kind: PayloadKind;
}

/** hint: giá trị lưu trong file khoá, đáng tin hơn byte flags (có thể bị lật bit). */
export async function decodePayload(
  data: Uint8Array,
  password: string,
  hint: { kind?: PayloadKind; encrypted?: boolean } = {},
): Promise<DecodedPayload> {
  if (data.length < PLAIN_OVERHEAD) throw new PayloadError("Dữ liệu trích xuất quá ngắn.");
  const head = data.subarray(0, data.length - 4);
  const crc = new DataView(data.buffer, data.byteOffset + data.length - 4, 4).getUint32(0);
  const integrityOk = crc32(head) === crc;
  const flags = head[0];
  const encrypted = hint.encrypted ?? !!(flags & FLAG_ENCRYPTED);
  const kind: PayloadKind = hint.kind ?? (flags & 0x02 ? "logo" : flags & 0x04 ? "file" : "text");

  if (!encrypted) return { body: head.subarray(1), integrityOk, encrypted, kind };

  if (!password) throw new WrongPasswordError("Nội dung đã được mã hoá — cần nhập mật khẩu.");
  if (head.length < 1 + SALT_LEN + NONCE_LEN + TAG_LEN) throw new PayloadError("Dữ liệu mã hoá bị hỏng (quá ngắn).");
  const salt = head.subarray(1, 1 + SALT_LEN);
  const nonce = head.subarray(1 + SALT_LEN, 1 + SALT_LEN + NONCE_LEN);
  const ct = head.subarray(1 + SALT_LEN + NONCE_LEN);
  try {
    const key = await deriveKey(password, salt);
    const body = new Uint8Array(
      await crypto.subtle.decrypt({ name: "AES-GCM", iv: nonce as BufferSource }, key, ct as BufferSource),
    );
    return { body, integrityOk, encrypted, kind };
  } catch {
    if (!integrityOk)
      throw new PayloadError("Ảnh đã bị biến đổi quá mạnh, dữ liệu mã hoá bị hỏng nên không giải mã được.");
    throw new WrongPasswordError("Sai mật khẩu.");
  }
}

export function packFile(name: string, data: Uint8Array): Uint8Array {
  let raw = new TextEncoder().encode(name);
  while (raw.length > 255) {
    name = name.slice(0, -1);
    raw = new TextEncoder().encode(name);
  }
  return concat(new Uint8Array([raw.length]), raw, data);
}

export function unpackFile(body: Uint8Array): { name: string; data: Uint8Array } {
  if (!body.length || body.length < 1 + body[0]) throw new PayloadError("Dữ liệu file bị hỏng.");
  const n = body[0];
  return { name: new TextDecoder().decode(body.subarray(1, 1 + n)), data: body.subarray(1 + n) };
}
