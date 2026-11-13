import { type FormEvent, useEffect, useRef, useState } from "react";
import { api, type User } from "../api";
import { passwordStrength } from "../utils";
import { Alert } from "./Alert";

interface Props {
  mode: "login" | "register";
  registrationOpen: boolean;
  onMode: (m: "login" | "register") => void;
  onClose: () => void;
  onDone: (u: User) => void;
}

export function AuthDialog({ mode, registrationOpen, onMode, onClose, onDone }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const first = useRef<HTMLInputElement>(null);
  const register = mode === "register";

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => setError(null), [mode]);

  const mismatch = register && confirm !== "" && confirm !== password;
  const ready = username.trim().length >= 3 && password.length >= (register ? 8 : 1) && (!register || confirm === password);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      onDone(await (register ? api.register : api.login)(username.trim(), password));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="modal panel" role="dialog" aria-modal="true" aria-labelledby="auth-title" onSubmit={submit}>
        <div className="modal-head">
          <h2 id="auth-title">{register ? "Đăng ký tài khoản" : "Đăng nhập"}</h2>
          <button type="button" className="link-btn" onClick={onClose} aria-label="Đóng">Đóng ✕</button>
        </div>
        <p className="muted small">
          {register
            ? "Có tài khoản thì ảnh đã giấu tin và file khoá được lưu lại để bạn lấy lại ở lần sau."
            : "Đăng nhập để xem lại và lưu lịch sử giấu tin của bạn."}
        </p>

        <label className="field">
          <span className="field-label">Tên đăng nhập</span>
          <input
            ref={first}
            type="text"
            value={username}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            maxLength={32}
            onChange={(e) => setUsername(e.target.value)}
          />
          {register && <span className="muted small">3 đến 32 ký tự: chữ không dấu, số và các dấu . _ -</span>}
        </label>

        <label className="field">
          <span className="field-label">Mật khẩu</span>
          <input
            type="password"
            value={password}
            autoComplete={register ? "new-password" : "current-password"}
            maxLength={256}
            onChange={(e) => setPassword(e.target.value)}
          />
          {register && password && (
            <div className="strength" data-level={passwordStrength(password)}>
              <span className="strength-bars" aria-hidden="true"><i /><i /><i /><i /></span>
              <span className="muted">
                {password.length < 8 ? "Cần ít nhất 8 ký tự" : ["", "Yếu, dễ bị dò", "Trung bình", "Khá", "Mạnh"][passwordStrength(password)]}
              </span>
            </div>
          )}
        </label>

        {register && (
          <label className="field">
            <span className="field-label">Nhập lại mật khẩu</span>
            <input
              type="password"
              value={confirm}
              autoComplete="new-password"
              maxLength={256}
              className={mismatch ? "is-invalid" : ""}
              onChange={(e) => setConfirm(e.target.value)}
            />
            {mismatch && <span className="small text-danger">Hai mật khẩu chưa khớp.</span>}
          </label>
        )}

        {register && (
          <Alert kind="warn">
            Trang không thu email nên <strong>không có chức năng lấy lại mật khẩu</strong>. Hãy ghi nhớ hoặc lưu mật khẩu
            vào trình quản lý mật khẩu.
          </Alert>
        )}
        {error && <Alert kind="error">{error}</Alert>}

        <div className="actions">
          <button className="btn btn-primary" disabled={!ready || busy}>
            {busy ? <span className="spinner" aria-hidden="true" /> : null}
            {register ? "Tạo tài khoản" : "Đăng nhập"}
          </button>
        </div>
        {registrationOpen ? (
          <button type="button" className="link-btn" onClick={() => onMode(register ? "login" : "register")}>
            {register ? "Đã có tài khoản? Đăng nhập" : "Chưa có tài khoản? Đăng ký"}
          </button>
        ) : (
          <span className="muted small">Trang này hiện không mở đăng ký tài khoản mới.</span>
        )}
      </form>
    </div>
  );
}
