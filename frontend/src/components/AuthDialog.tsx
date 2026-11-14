import { type FormEvent, useEffect, useRef, useState } from "react";
import { api, ApiError, type User } from "../api";
import { passwordStrength } from "../utils";
import { Alert } from "./Alert";

export type AuthMode = "login" | "register" | "recover";

interface Props {
  mode: AuthMode;
  registrationOpen: boolean;
  onMode: (m: AuthMode) => void;
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
  const [code, setCode] = useState("");
  const [otp, setOtp] = useState("");
  const [needOtp, setNeedOtp] = useState(false);
  const [issued, setIssued] = useState<User | null>(null);
  const [copied, setCopied] = useState(false);
  const recover = mode === "recover";
  /** Đăng ký và khôi phục đều đặt mật khẩu mới. */
  const register = mode === "register" || recover;

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    setError(null);
    setNeedOtp(false);
    setOtp("");
  }, [mode]);

  const mismatch = register && confirm !== "" && confirm !== password;
  const ready = username.trim().length >= 3 && password.length >= (register ? 8 : 1) && (!register || confirm === password) && (!recover || code.trim().length >= 20);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const u = recover
        ? await api.recover(username.trim(), code.trim(), password)
        : mode === "register"
          ? await api.register(username.trim(), password)
          : await api.login(username.trim(), password, needOtp ? otp : undefined);
      // Mã khôi phục chỉ hiện một lần: bắt người dùng xác nhận đã lưu rồi mới đóng.
      if (u.recovery_code) setIssued(u);
      else onDone(u);
    } catch (err) {
      if (err instanceof ApiError && err.status === 428) {
        setNeedOtp(true); // mật khẩu đúng, tài khoản bật xác thực hai lớp: hỏi thêm mã
        setError(null);
      } else setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (issued)
    return (
      <div className="modal-backdrop">
        <div className="modal panel" role="dialog" aria-modal="true" aria-labelledby="rc-title">
          <div className="modal-head">
            <h2 id="rc-title">Lưu mã khôi phục</h2>
          </div>
          <p className="muted small">
            Đây là cách duy nhất để lấy lại tài khoản <strong>@{issued.username}</strong> khi quên mật khẩu. Mã chỉ hiện
            một lần này. Hãy chép vào trình quản lý mật khẩu hoặc ghi ra giấy.
          </p>
          <pre className="message" style={{ textAlign: "center", fontSize: "1.1rem", userSelect: "all" }}>{issued.recovery_code}</pre>
          <div className="actions">
            <button
              type="button"
              className="btn"
              onClick={() => navigator.clipboard?.writeText(issued.recovery_code ?? "").then(() => setCopied(true), () => {})}
            >
              {copied ? "Đã chép" : "Chép mã"}
            </button>
            <button type="button" className="btn btn-primary" onClick={() => onDone({ ...issued, recovery_code: null })}>
              Tôi đã lưu mã
            </button>
          </div>
          <Alert kind="warn">Ai có mã này và tên đăng nhập đều đặt lại được mật khẩu của bạn. Đừng gửi cho ai.</Alert>
        </div>
      </div>
    );

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="modal panel" role="dialog" aria-modal="true" aria-labelledby="auth-title" onSubmit={submit}>
        <div className="modal-head">
          <h2 id="auth-title">{recover ? "Quên mật khẩu" : register ? "Đăng ký tài khoản" : "Đăng nhập"}</h2>
          <button type="button" className="link-btn" onClick={onClose} aria-label="Đóng">Đóng ✕</button>
        </div>
        <p className="muted small">
          {recover
            ? "Nhập mã khôi phục bạn nhận lúc đăng ký để đặt mật khẩu mới. Mã dùng xong sẽ được thay bằng mã mới."
            : register
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
          {mode === "register" && <span className="muted small">3 đến 32 ký tự: chữ không dấu, số và các dấu . _ -</span>}
        </label>

        {recover && (
          <label className="field">
            <span className="field-label">Mã khôi phục</span>
            <input
              type="text"
              value={code}
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              maxLength={40}
              placeholder="XXXX-XXXX-XXXX-XXXX-XXXX"
              onChange={(e) => setCode(e.target.value)}
            />
          </label>
        )}

        <label className="field">
          <span className="field-label">{recover ? "Mật khẩu mới" : "Mật khẩu"}</span>
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

        {mode === "login" && needOtp && (
          <label className="field">
            <span className="field-label">Mã xác thực hai lớp</span>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              maxLength={7}
              placeholder="6 chữ số trong ứng dụng xác thực"
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/[^0-9 ]/g, ""))}
            />
            <span className="muted small">Mất điện thoại? Dùng "Quên mật khẩu?" với mã khôi phục, 2FA sẽ được tắt.</span>
          </label>
        )}

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

        {mode === "register" && (
          <Alert kind="warn">
            Trang không thu email. Sau khi đăng ký bạn sẽ nhận một <strong>mã khôi phục</strong>, là cách duy nhất để lấy
            lại tài khoản khi quên mật khẩu.
          </Alert>
        )}
        {mode === "register" && (
          <span className="muted small">
            Tạo tài khoản nghĩa là bạn đồng ý với{" "}
            <a href="#privacy" target="_blank" rel="noopener">chính sách quyền riêng tư</a>.
          </span>
        )}
        {error && <Alert kind="error">{error}</Alert>}

        <div className="actions">
          <button className="btn btn-primary" disabled={!ready || busy}>
            {busy ? <span className="spinner" aria-hidden="true" /> : null}
            {recover ? "Đặt mật khẩu mới" : register ? "Tạo tài khoản" : "Đăng nhập"}
          </button>
        </div>
        {mode === "login" && (
          <button type="button" className="link-btn" onClick={() => onMode("recover")}>Quên mật khẩu?</button>
        )}
        {recover ? (
          <button type="button" className="link-btn" onClick={() => onMode("login")}>Quay lại đăng nhập</button>
        ) : registrationOpen ? (
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
