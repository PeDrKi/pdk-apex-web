// Chuyển logo <-> bytes ngay trong trình duyệt — bản TypeScript của backend/app/logo.py.
// Body: mode(1) | cao(2, BE) | rộng(2, BE) | điểm ảnh
//   mode 0 = đen trắng, 1 bit/điểm ảnh (bit cao trước), 1 = nét logo
//   mode 1 = 256 mức xám
export type LogoMode = "binary" | "gray";
export type LogoInvert = "auto" | "yes" | "no";

export const LOGO_HEADER_LEN = 5;
export const LOGO_MAX_SIDE = 512;

/** Các chỉnh sửa người dùng áp lên logo trước khi giấu. */
export interface LogoEdit {
  /** Phần cắt bỏ ở mỗi cạnh, tính theo tỉ lệ 0..0.45 của ảnh sau khi xoay/lật. */
  crop: { l: number; t: number; r: number; b: number };
  rotate: 0 | 90 | 180 | 270;
  flipH: boolean;
  /** Tự cắt phần viền trống quanh nét logo. */
  autoTrim: boolean;
  /** Ngưỡng đen trắng 1..254; null = tự động (Otsu). */
  threshold: number | null;
  /** Làm nét dày lên (>0) hoặc mảnh đi (<0), tính bằng điểm ảnh của logo đã thu nhỏ. */
  thicken: number;
  /** -100..100, chỉ dùng cho logo xám. */
  brightness: number;
  contrast: number;
  /** Đảo sáng tối, chỉ dùng cho logo xám. */
  negate: boolean;
}

export const DEFAULT_EDIT: LogoEdit = {
  crop: { l: 0, t: 0, r: 0, b: 0 },
  rotate: 0,
  flipH: false,
  autoTrim: false,
  threshold: null,
  thicken: 0,
  brightness: 0,
  contrast: 0,
  negate: false,
};

export interface EncodedLogo {
  body: Uint8Array;
  header: [number, number, number];
  width: number;
  height: number;
  previewUrl: string;
  /** Ngưỡng đen trắng đã dùng (null với logo xám). */
  threshold: number | null;
}

function fitSize(h0: number, w0: number, maxBody: number, mode: LogoMode, maxSide: number): [number, number] {
  const bpp = mode === "binary" ? 1 : 8;
  const budget = Math.max(0, Math.floor(((maxBody - LOGO_HEADER_LEN) * 8) / bpp));
  const side = maxSide > 0 ? Math.min(LOGO_MAX_SIDE, maxSide) : LOGO_MAX_SIDE;
  const scale = Math.min(1, Math.sqrt(budget / (h0 * w0)), side / Math.max(h0, w0));
  let h = Math.max(1, Math.floor(h0 * scale + 1e-9));
  let w = Math.max(1, Math.floor(w0 * scale + 1e-9));
  while (h * w > budget && (h > 1 || w > 1)) {
    h = Math.max(1, h - 1);
    w = Math.max(1, w - 1);
  }
  return [h, w];
}

const SRC_LIMIT = 1024;

function toGray(rgba: Uint8ClampedArray, n: number): Uint8Array {
  const g = new Uint8Array(n);
  for (let i = 0; i < n; i++)
    g[i] = Math.round(0.299 * rgba[i * 4] + 0.587 * rgba[i * 4 + 1] + 0.114 * rgba[i * 4 + 2]);
  return g;
}

/** Ảnh nguồn sau khi xoay/lật, vẽ trên nền trắng (vùng trong suốt được coi là nền trắng). */
function orient(bmp: ImageBitmap, edit: LogoEdit, limit = SRC_LIMIT, fill = true): HTMLCanvasElement {
  const s = Math.min(1, limit / Math.max(bmp.width, bmp.height));
  const bw = Math.max(1, Math.round(bmp.width * s));
  const bh = Math.max(1, Math.round(bmp.height * s));
  const swap = edit.rotate % 180 !== 0;
  const c = document.createElement("canvas");
  c.width = swap ? bh : bw;
  c.height = swap ? bw : bh;
  const ctx = c.getContext("2d", { willReadFrequently: true })!;
  if (fill) {
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, c.width, c.height);
  }
  ctx.imageSmoothingQuality = "high";
  ctx.translate(c.width / 2, c.height / 2);
  if (edit.flipH) ctx.scale(-1, 1); // lật theo chiều ngang của màn hình, sau khi xoay
  ctx.rotate((edit.rotate * Math.PI) / 180);
  ctx.drawImage(bmp, -bw / 2, -bh / 2, bw, bh);
  return c;
}

/** Ảnh nguồn (đã xoay/lật, chưa cắt) để vẽ khung cắt trong giao diện. */
export function orientedUrl(bmp: ImageBitmap, edit: LogoEdit): string {
  return orient(bmp, edit, 480, false).toDataURL("image/png"); // giữ nền trong suốt để giao diện tự đặt nền
}

function inkFlip(gray: Uint8Array, t: number, invert: LogoInvert): boolean {
  if (invert !== "auto") return invert === "yes";
  let bright = 0;
  for (const v of gray) if (v > t) bright++;
  return bright / gray.length > 0.5;
}

/** Áp xoay/lật/cắt; trả về vùng ảnh sẽ được thu nhỏ thành logo. */
function prepare(bmp: ImageBitmap, edit: LogoEdit, invert: LogoInvert): HTMLCanvasElement {
  const full = orient(bmp, edit);
  let x0 = Math.round(full.width * edit.crop.l);
  let y0 = Math.round(full.height * edit.crop.t);
  let x1 = Math.round(full.width * (1 - edit.crop.r));
  let y1 = Math.round(full.height * (1 - edit.crop.b));
  x1 = Math.max(x1, Math.min(full.width, x0 + 4));
  y1 = Math.max(y1, Math.min(full.height, y0 + 4));

  if (edit.autoTrim) {
    const w = x1 - x0;
    const h = y1 - y0;
    const gray = toGray(full.getContext("2d")!.getImageData(x0, y0, w, h).data, w * h);
    const t = edit.threshold ?? otsu(gray);
    const flip = inkFlip(gray, t, invert);
    let a = w, b = h, c = -1, d = -1;
    for (let y = 0; y < h; y++)
      for (let x = 0; x < w; x++)
        if (gray[y * w + x] > t !== flip) {
          if (x < a) a = x;
          if (x > c) c = x;
          if (y < b) b = y;
          if (y > d) d = y;
        }
    if (c >= a && d >= b) {
      const pad = Math.ceil(Math.max(c - a, d - b) * 0.04) + 1; // chừa một viền mỏng
      x1 = Math.min(x1, x0 + c + 1 + pad);
      y1 = Math.min(y1, y0 + d + 1 + pad);
      x0 = Math.max(x0, x0 + a - pad);
      y0 = Math.max(y0, y0 + b - pad);
    }
  }
  if (x0 === 0 && y0 === 0 && x1 === full.width && y1 === full.height) return full;
  const out = document.createElement("canvas");
  out.width = x1 - x0;
  out.height = y1 - y0;
  out.getContext("2d")!.drawImage(full, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
  return out;
}

/** Thu nhỏ từng bước (mỗi lần tối đa 2 lần) để nét không bị răng cưa. */
function resize(src: HTMLCanvasElement, w: number, h: number): ImageData {
  let cur = src;
  for (;;) {
    const nw = Math.max(w, Math.ceil(cur.width / 2));
    const nh = Math.max(h, Math.ceil(cur.height / 2));
    const c = document.createElement("canvas");
    c.width = nw;
    c.height = nh;
    const ctx = c.getContext("2d", { willReadFrequently: true })!;
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, nw, nh);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(cur, 0, 0, nw, nh);
    if (nw === w && nh === h) return ctx.getImageData(0, 0, w, h);
    cur = c;
  }
}

function otsu(gray: Uint8Array): number {
  const hist = new Float64Array(256);
  for (const v of gray) hist[v]++;
  let sumAll = 0;
  for (let i = 0; i < 256; i++) sumAll += i * hist[i];
  let sumB = 0;
  let wB = 0;
  let best = -1;
  let bestT = 127;
  for (let t = 0; t < 256; t++) {
    wB += hist[t];
    if (!wB) continue;
    const wF = gray.length - wB;
    if (!wF) break;
    sumB += t * hist[t];
    const d = sumB / wB - (sumAll - sumB) / wF;
    const v = wB * wF * d * d;
    if (v > best) {
      best = v;
      bestT = t;
    }
  }
  return bestT;
}

/** Nở (grow=true) hoặc co nét một điểm ảnh theo 4 hướng. */
function morph(ink: Uint8Array, w: number, h: number, grow: boolean): Uint8Array {
  const out = new Uint8Array(ink.length);
  const on = grow ? 1 : 0;
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const hit =
        ink[i] === on ||
        (x > 0 && ink[i - 1] === on) ||
        (x < w - 1 && ink[i + 1] === on) ||
        (y > 0 && ink[i - w] === on) ||
        (y < h - 1 && ink[i + w] === on);
      out[i] = hit ? on : 1 - on;
    }
  return out;
}

function toDataUrl(px: Uint8Array, w: number, h: number): string {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d")!;
  const img = ctx.createImageData(w, h);
  for (let i = 0; i < w * h; i++) {
    img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = px[i];
    img.data[i * 4 + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return c.toDataURL("image/png");
}

export async function loadLogo(file: File): Promise<ImageBitmap> {
  try {
    return await createImageBitmap(file);
  } catch {
    throw new Error("File logo không phải ảnh hợp lệ.");
  }
}

/** Dựng dữ liệu logo đúng như sẽ được giấu. Chạy đồng bộ nên dùng được cho xem trước trực tiếp. */
export function encodeLogo(
  bmp: ImageBitmap,
  maxBody: number,
  mode: LogoMode,
  invert: LogoInvert,
  maxSide: number,
  edit: LogoEdit = DEFAULT_EDIT,
): EncodedLogo {
  const src = prepare(bmp, edit, invert);
  const [h, w] = fitSize(src.height, src.width, maxBody, mode, maxSide);
  if (h * w < 64)
    throw new Error("Ảnh chứa quá nhỏ để giấu logo. Hãy dùng ảnh lớn hơn, giảm độ dự phòng hoặc chọn kiểu đen trắng.");
  const gray = toGray(resize(src, w, h).data, w * h);

  const header: [number, number, number] = [mode === "binary" ? 0 : 1, h, w];
  const head = new Uint8Array([header[0], h >> 8, h & 255, w >> 8, w & 255]);

  if (mode === "gray") {
    const k = (100 + edit.contrast) / 100;
    const add = edit.brightness * 1.27;
    if (edit.contrast || edit.brightness || edit.negate)
      for (let i = 0; i < gray.length; i++) {
        const v = edit.negate ? 255 - gray[i] : gray[i];
        gray[i] = Math.max(0, Math.min(255, Math.round((v - 128) * k * k + 128 + add)));
      }
    const body = new Uint8Array(LOGO_HEADER_LEN + gray.length);
    body.set(head);
    body.set(gray, LOGO_HEADER_LEN);
    return { body, header, width: w, height: h, previewUrl: toDataUrl(gray, w, h), threshold: null };
  }

  const t = edit.threshold ?? otsu(gray);
  const flip = inkFlip(gray, t, invert);
  let ink: Uint8Array = new Uint8Array(gray.length);
  for (let i = 0; i < gray.length; i++) ink[i] = gray[i] > t !== flip ? 1 : 0; // 1 = nét logo
  for (let n = Math.abs(edit.thicken); n > 0; n--) ink = morph(ink, w, h, edit.thicken > 0);

  const packed = new Uint8Array(Math.ceil(ink.length / 8));
  const preview = new Uint8Array(ink.length);
  for (let i = 0; i < ink.length; i++) {
    if (ink[i]) packed[i >> 3] |= 0x80 >> (i & 7);
    preview[i] = ink[i] ? 0 : 255;
  }
  const body = new Uint8Array(LOGO_HEADER_LEN + packed.length);
  body.set(head);
  body.set(packed, LOGO_HEADER_LEN);
  return { body, header, width: w, height: h, previewUrl: toDataUrl(preview, w, h), threshold: t };
}

/** header: (mode, cao, rộng) lấy từ file khoá — dùng thay header trong ảnh vì đáng tin hơn. */
export function decodeLogo(body: Uint8Array, header?: number[] | null): { url: string; width: number; height: number } {
  if (body.length < LOGO_HEADER_LEN) throw new Error("Dữ liệu logo bị hỏng.");
  const [mode, h, w] =
    header && header.length === 3 ? header : [body[0], (body[1] << 8) | body[2], (body[3] << 8) | body[4]];
  if ((mode !== 0 && mode !== 1) || h < 1 || w < 1 || h > LOGO_MAX_SIDE || w > LOGO_MAX_SIDE)
    throw new Error("Không đọc được thông tin logo: ảnh đã bị biến đổi quá mạnh hoặc sai khoá.");
  const data = body.subarray(LOGO_HEADER_LEN);
  const px = new Uint8Array(w * h).fill(255);
  for (let i = 0; i < w * h; i++) {
    if (mode === 0) {
      const byte = data[i >> 3] ?? 0;
      px[i] = byte & (0x80 >> (i & 7)) ? 0 : 255;
    } else if (i < data.length) px[i] = data[i];
  }
  return { url: toDataUrl(px, w, h), width: w, height: h };
}
