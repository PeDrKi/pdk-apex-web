// Lịch sử giấu tin. Khách: chỉ nằm trong bộ nhớ của tab, đóng trang là mất.
// Đã đăng nhập: lưu trên máy chủ (xem backend/app/accounts.py).
import type { PayloadKind } from "../api";

/** Kết quả một lần giấu tin, do tab Giấu tin / Hàng loạt báo lên. */
export interface NewEntry {
  name: string;
  stego: Blob;
  keys: Blob;
  kind: PayloadKind;
  encrypted: boolean;
  width: number;
  height: number;
  psnr: number | null;
  redundancy: number;
  /** Máy chủ đã lưu mục này vào tài khoản ngay lúc giấu tin. */
  savedId?: string | null;
  /** Máy chủ được nhờ lưu nhưng không lưu được (ví dụ hết dung lượng). */
  saveError?: string | null;
}

/** Mục chỉ có trong phiên hiện tại (chưa lưu vào tài khoản). */
export interface LocalEntry extends NewEntry {
  id: string;
  createdAt: number;
  thumbUrl: string;
  /** Lý do tự lưu vào tài khoản thất bại, nếu có. */
  saveError?: string;
}

/** Giới hạn số mục giữ trong bộ nhớ để tab không phình quá lớn. */
export const MAX_LOCAL = 100;

export function toLocal(e: NewEntry, saveError?: string): LocalEntry {
  return {
    ...e,
    id: crypto.getRandomValues(new Uint32Array(2)).join("-"),
    createdAt: Date.now(),
    thumbUrl: URL.createObjectURL(e.stego),
    saveError,
  };
}

const AUTOSAVE_KEY = "apex.autosave";

export function loadAutoSave(): boolean {
  try {
    return localStorage.getItem(AUTOSAVE_KEY) !== "0";
  } catch {
    return true;
  }
}

export function storeAutoSave(on: boolean) {
  try {
    localStorage.setItem(AUTOSAVE_KEY, on ? "1" : "0");
  } catch {
    /* không lưu được tuỳ chọn thì thôi */
  }
}
