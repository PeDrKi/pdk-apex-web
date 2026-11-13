// ZIP tối giản: ghi kiểu "stored" (không nén, vì PNG/NPZ vốn đã nén), đọc được
// cả stored lẫn deflate (zip do Windows/macOS tạo lại).
import { crc32 } from "./crc32";

export interface ZipEntry {
  name: string;
  data: Uint8Array;
}

export function writeZip(entries: ZipEntry[]): Blob {
  const enc = new TextEncoder();
  const parts: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;
  for (const e of entries) {
    const name = enc.encode(e.name);
    const crc = crc32(e.data);
    const local = new Uint8Array(30 + name.length);
    const lv = new DataView(local.buffer);
    lv.setUint32(0, 0x04034b50, true);
    lv.setUint16(4, 20, true);
    lv.setUint16(6, 0x0800, true); // tên file UTF-8
    lv.setUint16(12, 0x21, true); // ngày DOS hợp lệ: 1980-01-01
    lv.setUint32(14, crc, true);
    lv.setUint32(18, e.data.length, true);
    lv.setUint32(22, e.data.length, true);
    lv.setUint16(26, name.length, true);
    local.set(name, 30);

    const cen = new Uint8Array(46 + name.length);
    const cv = new DataView(cen.buffer);
    cv.setUint32(0, 0x02014b50, true);
    cv.setUint16(4, 20, true);
    cv.setUint16(6, 20, true);
    cv.setUint16(8, 0x0800, true);
    cv.setUint16(14, 0x21, true);
    cv.setUint32(16, crc, true);
    cv.setUint32(20, e.data.length, true);
    cv.setUint32(24, e.data.length, true);
    cv.setUint16(28, name.length, true);
    cv.setUint32(42, offset, true);
    cen.set(name, 46);

    parts.push(local, e.data);
    central.push(cen);
    offset += local.length + e.data.length;
  }
  const cenSize = central.reduce((n, c) => n + c.length, 0);
  const end = new Uint8Array(22);
  const ev = new DataView(end.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(8, entries.length, true);
  ev.setUint16(10, entries.length, true);
  ev.setUint32(12, cenSize, true);
  ev.setUint32(16, offset, true);
  return new Blob([...parts, ...central, end] as BlobPart[], { type: "application/zip" });
}

async function inflateRaw(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([data as BlobPart]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export async function readZip(buf: ArrayBuffer, maxTotal = 200 * 1024 * 1024): Promise<ZipEntry[]> {
  const u8 = new Uint8Array(buf);
  const dv = new DataView(buf);
  let eocd = -1;
  for (let i = u8.length - 22; i >= Math.max(0, u8.length - 22 - 65535); i--) {
    if (dv.getUint32(i, true) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error("File zip không hợp lệ.");
  const count = dv.getUint16(eocd + 10, true);
  let p = dv.getUint32(eocd + 16, true);
  const out: ZipEntry[] = [];
  let total = 0;
  for (let n = 0; n < count && n < 500; n++) {
    if (dv.getUint32(p, true) !== 0x02014b50) throw new Error("File zip không hợp lệ.");
    const method = dv.getUint16(p + 10, true);
    const compSize = dv.getUint32(p + 20, true);
    const size = dv.getUint32(p + 24, true);
    const nameLen = dv.getUint16(p + 28, true);
    const extraLen = dv.getUint16(p + 30, true);
    const commentLen = dv.getUint16(p + 32, true);
    const local = dv.getUint32(p + 42, true);
    const name = new TextDecoder().decode(u8.subarray(p + 46, p + 46 + nameLen));
    p += 46 + nameLen + extraLen + commentLen;
    if (name.endsWith("/")) continue;
    total += size;
    if (total > maxTotal) throw new Error("File zip quá lớn.");
    const start = local + 30 + dv.getUint16(local + 26, true) + dv.getUint16(local + 28, true);
    const raw = u8.subarray(start, start + compSize);
    if (method === 0) out.push({ name, data: raw.slice() });
    else if (method === 8) out.push({ name, data: await inflateRaw(raw) });
    else throw new Error("File zip dùng kiểu nén không hỗ trợ.");
  }
  return out;
}

const IMAGE_EXT = /\.(png|jpe?g|webp|bmp|tiff?|gif)$/i;

/** Tách gói zip (tải về từ bước giấu tin) thành ảnh + file khoá. */
export async function unpackBundle(file: File): Promise<{ image: File | null; keys: File | null }> {
  const entries = await readZip(await file.arrayBuffer());
  const base = (n: string) => n.split("/").pop() || n;
  const img = entries.find((e) => IMAGE_EXT.test(e.name));
  const key = entries.find((e) => /\.npz$/i.test(e.name));
  return {
    image: img ? new File([img.data as BlobPart], base(img.name), { type: "image/png" }) : null,
    keys: key ? new File([key.data as BlobPart], base(key.name)) : null,
  };
}

export const isZip = (f: File) => /\.zip$/i.test(f.name);
