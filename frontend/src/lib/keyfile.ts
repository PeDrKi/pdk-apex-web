// File khoá được bọc bằng mật khẩu ("apexkey"), làm NGAY TRONG TRÌNH DUYỆT.
// File khoá .npz chứa vị trí nhúng và ảnh thu nhỏ của ảnh gốc; khi người dùng đặt mật khẩu,
// ta mã hoá cả file bằng AES-256-GCM để người nhặt được file khoá không xem được các thứ đó.
//
//   "APEXKEY1"(8) kind(1) redundancy(2, big-endian) salt(16) nonce(12) ciphertext+tag
//   11 byte đầu là dữ liệu kèm theo (AAD): máy chủ đọc được để hiện trong lịch sử, nhưng sửa là hỏng.
import { deriveKey, WrongPasswordError, type PayloadKind } from "./payload";

const MAGIC = new TextEncoder().encode("APEXKEY1");
const HEAD = MAGIC.length + 3;
const SALT_LEN = 16;
const NONCE_LEN = 12;
const KINDS: PayloadKind[] = ["text", "logo", "file"];

/** Đuôi file khoá đã bọc mật khẩu. */
export const SEALED_EXT = ".apexkey";

export function isSealed(data: Uint8Array): boolean {
  return data.length > HEAD + SALT_LEN + NONCE_LEN && MAGIC.every((b, i) => data[i] === b);
}

export async function sealKeys(
  npz: Uint8Array,
  password: string,
  meta: { kind: PayloadKind; redundancy: number },
): Promise<Uint8Array> {
  const head = new Uint8Array(HEAD);
  head.set(MAGIC);
  head[8] = Math.max(0, KINDS.indexOf(meta.kind));
  new DataView(head.buffer).setUint16(9, Math.min(65535, Math.max(1, meta.redundancy)));
  const salt = crypto.getRandomValues(new Uint8Array(SALT_LEN));
  const nonce = crypto.getRandomValues(new Uint8Array(NONCE_LEN));
  const key = await deriveKey(password, salt);
  const ct = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: nonce as BufferSource, additionalData: head as BufferSource },
      key,
      npz as BufferSource,
    ),
  );
  const out = new Uint8Array(HEAD + SALT_LEN + NONCE_LEN + ct.length);
  out.set(head);
  out.set(salt, HEAD);
  out.set(nonce, HEAD + SALT_LEN);
  out.set(ct, HEAD + SALT_LEN + NONCE_LEN);
  return out;
}

export async function unsealKeys(data: Uint8Array, password: string): Promise<Uint8Array> {
  if (!password) throw new WrongPasswordError("File khoá này được bảo vệ bằng mật khẩu. Hãy nhập mật khẩu.");
  const head = data.subarray(0, HEAD);
  const salt = data.subarray(HEAD, HEAD + SALT_LEN);
  const nonce = data.subarray(HEAD + SALT_LEN, HEAD + SALT_LEN + NONCE_LEN);
  try {
    const key = await deriveKey(password, salt);
    return new Uint8Array(
      await crypto.subtle.decrypt(
        { name: "AES-GCM", iv: nonce as BufferSource, additionalData: head as BufferSource },
        key,
        data.subarray(HEAD + SALT_LEN + NONCE_LEN) as BufferSource,
      ),
    );
  } catch {
    throw new WrongPasswordError("Sai mật khẩu, hoặc file khoá đã bị sửa.");
  }
}

/** Trả về file khoá .npz dùng được cho máy chủ; mở bọc nếu file đang được bảo vệ bằng mật khẩu. */
export async function openKeysFile(file: File, password: string): Promise<File> {
  const data = new Uint8Array(await file.arrayBuffer());
  if (!isSealed(data)) return file;
  if (typeof crypto === "undefined" || !crypto.subtle)
    throw new Error("File khoá được bảo vệ bằng mật khẩu chỉ mở được trên HTTPS.");
  return new File([(await unsealKeys(data, password)) as BlobPart], "khoa.npz");
}
