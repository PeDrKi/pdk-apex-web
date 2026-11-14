// Client gọi backend FastAPI. VITE_API_BASE trống = cùng domain (dev dùng proxy của Vite).
const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export interface Health {
  status: string;
  apexmark_version: string;
  sync_available: boolean;
  bc7_available: boolean;
  max_upload_mb: number;
  max_redundancy: number;
  detect_enabled?: boolean;
}

export interface CapacityResult {
  width: number;
  height: number;
  capacity_bits: number;
  redundancy: number;
  usable_bits: number;
  max_message_bytes: number;
  max_message_bytes_encrypted: number;
}

export interface EmbedResult {
  stego_png_base64: string;
  keys_npz_base64: string;
  width: number;
  height: number;
  n_bits: number;
  capacity_bits: number;
  usage_ratio: number;
  psnr_db: number | null;
  encrypted: boolean;
  redundancy: number;
  elapsed_ms: number;
  kind: PayloadKind;
  logo_preview_base64: string | null;
  logo_width: number | null;
  logo_height: number | null;
  /** Mã mục lịch sử nếu máy chủ đã lưu luôn kết quả vào tài khoản. */
  saved_id: string | null;
  save_error: string | null;
  /** Ước lượng khả năng bị phát hiện bởi người biết thuật toán. */
  detect_level?: "low" | "medium" | "high" | null;
  detect_score?: number | null;
  detect_baseline?: number | null;
  detect_noise?: number | null;
}

export type PayloadKind = "text" | "logo" | "file";
export type LogoMode = "binary" | "gray";

export interface ExtractResult {
  kind: PayloadKind;
  message: string;
  logo_png_base64: string | null;
  logo_width: number | null;
  logo_height: number | null;
  file_base64: string | null;
  file_name: string | null;
  payload_base64: string | null;
  payload_format: string | null;
  logo_header: number[] | null;
  integrity_ok: boolean | null;
  encrypted: boolean;
  used_resync: boolean;
  n_bits: number;
  elapsed_ms: number;
}

export interface EmbedOptions {
  image: File;
  kind: PayloadKind;
  redundancy: number;
  autoRedundancy: boolean;
  delta: number;
  storeThumbnail: boolean;
  useAco: boolean;
  /** Đã đăng nhập: nhờ máy chủ lưu luôn kết quả vào lịch sử (khỏi tải ảnh lên lần nữa). */
  save?: { name: string };
}

/** Trình duyệt đã tự đóng gói (và mã hoá) nội dung: máy chủ chỉ nhúng. */
export interface EmbedPackedParams extends EmbedOptions {
  payload: Uint8Array;
  encrypted: boolean;
  logoHeader?: number[];
}

/** Dự phòng khi trình duyệt không có Web Crypto (HTTP không phải localhost): máy chủ mã hoá. */
export interface EmbedServerParams extends EmbedOptions {
  message: string;
  logo: File | null;
  logoMode: LogoMode;
  logoInvert: "auto" | "yes" | "no";
  logoMaxSide: number;
  file: File | null;
  password: string;
}

export interface ExtractParams {
  image: File;
  keys: File;
  password: string;
  resync: boolean;
  rotateRange: number;
  aggregate: "mean" | "kmeans";
  raw: boolean;
}

export interface AttackInfo {
  id: string;
  name: string;
  group: string;
  param: "level" | "quality" | "none";
  geometric: boolean;
  hint: string;
}

export interface AttackStep {
  id: string;
  value: number;
}

export type AttackStatus = "intact" | "partial" | "broken";

export interface AttackResult {
  attacked_png_base64: string;
  width: number;
  height: number;
  steps: string[];
  ber: number | null;
  status: AttackStatus | null;
  extract: ExtractResult | null;
  extract_error: string | null;
  elapsed_ms: number;
}

export interface BatteryRow {
  id: string;
  name: string;
  group: string;
  geometric: boolean;
  ber: number | null;
  status: AttackStatus;
  error: string | null;
}

export interface BatteryResult {
  level: number;
  n_bits: number;
  encrypted: boolean;
  rows: BatteryRow[];
  intact: number;
  partial: number;
  broken: number;
  elapsed_ms: number;
}

export interface CompareResult {
  heatmap_png_base64: string;
  overlay_png_base64: string;
  width: number;
  height: number;
  changed_pixels: number;
  changed_ratio: number;
  changed_blocks: number;
  total_blocks: number;
  max_diff: number;
  mean_diff: number;
  psnr_db: number | null;
}

/** Ảnh gốc, ảnh đã giấu và khoá của lần giấu tin gần nhất, để chuyển sang tab khác. */
export interface Session {
  original: File;
  stego: File;
  keys: File;
  password: string;
}

export interface User {
  username: string;
  created_at: number;
  has_recovery?: boolean;
  has_2fa?: boolean;
  /** Chỉ có ngay sau khi đăng ký, khôi phục hoặc tạo mã mới. */
  recovery_code?: string | null;
}

export interface AuthEvent {
  ts: number;
  event: string;
  label: string;
  ip: string;
}

export interface Me {
  user: User | null;
  registration_open: boolean;
}

/** Một mục đã lưu trong tài khoản (ảnh đã giấu tin + file khoá nằm trên máy chủ). */
export interface HistoryItem {
  id: string;
  created_at: number;
  name: string;
  kind: PayloadKind;
  encrypted: boolean;
  width: number;
  height: number;
  psnr: number | null;
  redundancy: number;
  stego_bytes: number;
  keys_bytes: number;
  stego_sha256?: string | null;
  keys_sha256?: string | null;
}

export interface ProofResult {
  found: boolean;
  matched: "stego" | "keys" | null;
  registered_at: number | null;
  owner: string | null;
  name: string | null;
}

export interface HistoryList {
  items: HistoryItem[];
  used_bytes: number;
  max_bytes: number;
  max_items: number;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError(0, "Không kết nối được máy chủ. Hãy kiểm tra backend đã chạy chưa.");
  }
  if (!res.ok) {
    let msg =
      res.status === 413
        ? "Dữ liệu gửi lên quá lớn so với giới hạn của máy chủ. Hãy dùng ảnh nhỏ hơn."
        : res.status === 502 || res.status === 503 || res.status === 504
          ? "Máy chủ đang khởi động hoặc quá tải. Hãy thử lại sau ít giây."
          : `Lỗi máy chủ (${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
      else if (Array.isArray(body.detail)) msg = "Dữ liệu gửi lên không hợp lệ.";
    } catch {
      /* giữ thông báo mặc định */
    }
    throw new ApiError(res.status, msg);
  }
  return res;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return (await send(path, init)).json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: body === undefined ? undefined : { "content-type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

function embedForm(p: EmbedOptions): FormData {
  const fd = new FormData();
  fd.append("image", p.image);
  fd.append("kind", p.kind);
  fd.append("redundancy", String(p.redundancy));
  fd.append("auto_redundancy", String(p.autoRedundancy));
  fd.append("delta", String(p.delta));
  fd.append("store_thumbnail", String(p.storeThumbnail));
  fd.append("use_aco", String(p.useAco));
  if (p.save) {
    fd.append("save", "true");
    fd.append("save_name", p.save.name);
  }
  return fd;
}

export const api = {
  health: () => request<Health>("/api/health"),

  capacity(image: File, redundancy: number, signal?: AbortSignal) {
    const fd = new FormData();
    fd.append("image", image);
    fd.append("redundancy", String(redundancy));
    return request<CapacityResult>("/api/capacity", { method: "POST", body: fd, signal });
  },

  embedPacked(p: EmbedPackedParams) {
    const fd = embedForm(p);
    fd.append("payload", new Blob([p.payload as BlobPart]), "payload.bin");
    fd.append("payload_encrypted", String(p.encrypted));
    if (p.logoHeader) fd.append("logo_header", p.logoHeader.join(","));
    return request<EmbedResult>("/api/embed", { method: "POST", body: fd });
  },

  embedServer(p: EmbedServerParams) {
    const fd = embedForm(p);
    if (p.kind === "logo" && p.logo) {
      fd.append("logo", p.logo);
      fd.append("logo_mode", p.logoMode);
      fd.append("logo_invert", p.logoInvert);
      fd.append("logo_max_side", String(p.logoMaxSide));
    } else if (p.kind === "file" && p.file) {
      fd.append("file", p.file);
    } else {
      fd.append("message", p.message);
    }
    fd.append("password", p.password);
    return request<EmbedResult>("/api/embed", { method: "POST", body: fd });
  },

  attacks: () => request<AttackInfo[]>("/api/attacks"),

  attack(image: File, steps: AttackStep[], keys: File | null, password: string, raw: boolean) {
    const fd = new FormData();
    fd.append("image", image);
    fd.append("steps", JSON.stringify(steps));
    if (keys) fd.append("keys", keys);
    fd.append("password", password);
    fd.append("raw", String(raw));
    return request<AttackResult>("/api/attack", { method: "POST", body: fd });
  },

  battery(image: File, keys: File, level: number) {
    const fd = new FormData();
    fd.append("image", image);
    fd.append("keys", keys);
    fd.append("level", String(level));
    return request<BatteryResult>("/api/attack/battery", { method: "POST", body: fd });
  },

  compare(original: File, stego: File) {
    const fd = new FormData();
    fd.append("original", original);
    fd.append("stego", stego);
    return request<CompareResult>("/api/compare", { method: "POST", body: fd });
  },

  // ---- tài khoản và lịch sử (cookie phiên HttpOnly, trình duyệt tự gửi kèm) ----
  me: () => request<Me>("/api/auth/me"),
  register: (username: string, password: string) => request<User>("/api/auth/register", json("POST", { username, password })),
  /** Máy chủ trả 428 khi tài khoản bật xác thực hai lớp mà chưa gửi mã. */
  login: (username: string, password: string, code?: string) =>
    request<User>("/api/auth/login", json("POST", { username, password, code: code || null })),
  twoFaSetup: (password: string) => request<{ secret: string; uri: string }>("/api/auth/2fa/setup", json("POST", { password })),
  twoFaEnable: (code: string) => request<{ ok: boolean }>("/api/auth/2fa/enable", json("POST", { code })),
  twoFaDisable: (password: string) => request<{ ok: boolean }>("/api/auth/2fa/disable", json("POST", { password })),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", json("POST")),
  recover: (username: string, code: string, next: string) =>
    request<User>("/api/auth/recover", json("POST", { username, code, new: next })),
  newRecoveryCode: (password: string) => request<User>("/api/auth/recovery-code", json("POST", { password })),
  activity: () => request<AuthEvent[]>("/api/auth/activity"),
  changePassword: (current: string, next: string) =>
    request<{ ok: boolean }>("/api/auth/password", json("POST", { current, new: next })),
  deleteAccount: (password: string) => request<{ ok: boolean }>("/api/auth/delete", json("POST", { password })),

  history: () => request<HistoryList>("/api/history"),
  proof: (sha256: string) => request<ProofResult>(`/api/proof/${sha256}`),
  historySave(p: { stego: Blob; keys: Blob; name: string; psnr: number | null }) {
    const fd = new FormData();
    fd.append("stego", p.stego, "stego.png");
    fd.append("keys", p.keys, "keys.bin");
    fd.append("name", p.name);
    if (p.psnr !== null) fd.append("psnr", String(p.psnr));
    return request<HistoryItem>("/api/history", { method: "POST", body: fd });
  },
  historyFile: async (id: string, what: "stego" | "keys") => (await send(`/api/history/${id}/${what}`)).blob(),
  historyThumbUrl: (id: string) => `${BASE}/api/history/${id}/thumb`,
  historyDelete: (id: string) => request<{ ok: boolean }>(`/api/history/${id}`, json("DELETE")),
  historyClear: () => request<{ ok: boolean }>("/api/history", json("DELETE")),

  extract(p: ExtractParams) {
    const fd = new FormData();
    fd.append("image", p.image);
    fd.append("keys", p.keys);
    fd.append("password", p.password);
    fd.append("resync", String(p.resync));
    fd.append("rotate_range", String(p.rotateRange));
    fd.append("aggregate", p.aggregate);
    fd.append("raw", String(p.raw));
    return request<ExtractResult>("/api/extract", { method: "POST", body: fd });
  },
};
