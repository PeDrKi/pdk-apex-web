import qrcode from "qrcode-generator";
import { type FormEvent, useEffect, useState } from "react";
import { api, type AuthEvent, type HistoryItem, type HistoryList, type PayloadKind, type User } from "../api";
import type { LocalEntry } from "../lib/history";
import { isSealed, SEALED_EXT } from "../lib/keyfile";
import { writeZip } from "../lib/zip";
import { downloadBlob, formatBytes } from "../utils";
import { Alert } from "./Alert";
import type { AuthMode } from "./AuthDialog";
import { ProofCheck } from "./ProofCheck";

interface Props {
  user: User | null;
  local: LocalEntry[];
  remote: HistoryList | null;
  remoteError: string | null;
  autoSave: boolean;
  onAutoSave: (on: boolean) => void;
  onLogin: (mode: AuthMode) => void;
  onSaveLocal: () => Promise<void>;
  onDeleteLocal: (id: string) => void;
  onRemoteChanged: () => Promise<void>;
  onOpenExtract: (image: File, keys: File) => void;
  onSignedOut: () => void;
}

interface Row {
  key: string;
  saved: boolean;
  name: string;
  createdAt: number;
  kind: PayloadKind;
  encrypted: boolean;
  width: number;
  height: number;
  psnr: number | null;
  redundancy: number;
  bytes: number;
  thumb: string;
  note?: string;
  files: () => Promise<{ stego: Blob; keys: Blob }>;
  remove: () => Promise<void> | void;
}

const KIND: Record<PayloadKind, string> = { text: "Chữ", logo: "Logo", file: "File" };
const dateFmt = new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short" });

function fromRemote(i: HistoryItem, changed: () => Promise<void>): Row {
  return {
    key: i.id,
    saved: true,
    name: i.name,
    createdAt: i.created_at * 1000,
    kind: i.kind,
    encrypted: i.encrypted,
    width: i.width,
    height: i.height,
    psnr: i.psnr,
    redundancy: i.redundancy,
    bytes: i.stego_bytes + i.keys_bytes,
    thumb: api.historyThumbUrl(i.id),
    files: async () => {
      const [stego, keys] = await Promise.all([api.historyFile(i.id, "stego"), api.historyFile(i.id, "keys")]);
      return { stego, keys };
    },
    remove: async () => {
      await api.historyDelete(i.id);
      await changed();
    },
  };
}

function fromLocal(e: LocalEntry, remove: (id: string) => void): Row {
  return {
    key: e.id,
    saved: false,
    name: e.name,
    createdAt: e.createdAt,
    kind: e.kind,
    encrypted: e.encrypted,
    width: e.width,
    height: e.height,
    psnr: e.psnr,
    redundancy: e.redundancy,
    bytes: e.stego.size + e.keys.size,
    thumb: e.thumbUrl,
    note: e.saveError,
    files: async () => ({ stego: e.stego, keys: e.keys }),
    remove: () => remove(e.id),
  };
}

export function HistoryPanel(p: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  const rows: Row[] = [
    ...p.local.map((e) => fromLocal(e, p.onDeleteLocal)),
    ...(p.remote?.items ?? []).map((i) => fromRemote(i, p.onRemoteChanged)),
  ];

  async function act(key: string, fn: () => Promise<void> | void) {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  /** File khoá đã bọc mật khẩu mang đuôi .apexkey; nhận biết qua mấy byte đầu. */
  const names = async (r: Row, keys: Blob) => ({
    stego: `${r.name}_apex.png`,
    keys: `${r.name}_khoa${isSealed(new Uint8Array(await keys.slice(0, 64).arrayBuffer())) ? SEALED_EXT : ".npz"}`,
  });

  async function zip(r: Row) {
    const f = await r.files();
    const n = await names(r, f.keys);
    downloadBlob(
      writeZip([
        { name: n.stego, data: new Uint8Array(await f.stego.arrayBuffer()) },
        { name: n.keys, data: new Uint8Array(await f.keys.arrayBuffer()) },
      ]),
      `${r.name}_apex.zip`,
    );
  }

  async function open(r: Row) {
    const f = await r.files();
    const n = await names(r, f.keys);
    p.onOpenExtract(new File([f.stego], n.stego, { type: "image/png" }), new File([f.keys], n.keys));
  }

  const usedPct = p.remote ? Math.min(100, (p.remote.used_bytes / Math.max(1, p.remote.max_bytes)) * 100) : 0;

  return (
    <div className="panel">
      {p.user ? (
        <div className="history-head">
          <div>
            <span className="field-label">Tài khoản</span>
            <p className="history-user">{p.user.username}</p>
          </div>
          {p.remote && (
            <div className="history-usage">
              <div className="meter" aria-hidden="true">
                <div className="meter-bar" style={{ width: `${usedPct}%` }} />
              </div>
              <span className="muted small">
                {p.remote.items.length} / {p.remote.max_items} mục · {formatBytes(p.remote.used_bytes)} / {formatBytes(p.remote.max_bytes)}
              </span>
            </div>
          )}
        </div>
      ) : (
        <Alert kind="warn">
          <strong>Bạn đang dùng với tư cách khách.</strong> Lịch sử bên dưới chỉ nằm trong tab này và sẽ mất hết khi bạn
          đóng hoặc tải lại trang. Máy chủ không lưu gì của khách.
          <div className="actions" style={{ marginTop: 10 }}>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => p.onLogin("register")}>Đăng ký để lưu lại</button>
            <button type="button" className="btn btn-sm" onClick={() => p.onLogin("login")}>Đăng nhập</button>
          </div>
        </Alert>
      )}

      {p.user && (
        <label className="check">
          <input type="checkbox" checked={p.autoSave} onChange={(e) => p.onAutoSave(e.target.checked)} />
          Tự lưu vào tài khoản mỗi lần giấu tin (ảnh đã giấu tin và file khoá; không lưu ảnh gốc và mật khẩu. File khoá chỉ được mã hoá khi bạn đặt mật khẩu)
        </label>
      )}

      {p.user && p.local.length > 0 && (
        <Alert kind="warn">
          Có {p.local.length} mục của phiên này chưa lưu vào tài khoản. Chúng sẽ mất khi bạn đóng trang.
          <div className="actions" style={{ marginTop: 10 }}>
            <button type="button" className="btn btn-primary btn-sm" disabled={busy !== null} onClick={() => act("save-all", p.onSaveLocal)}>
              {busy === "save-all" ? "Đang lưu…" : `Lưu ${p.local.length} mục vào tài khoản`}
            </button>
          </div>
        </Alert>
      )}

      {p.remoteError && <Alert kind="error">{p.remoteError}</Alert>}
      {error && <Alert kind="error">{error}</Alert>}

      {rows.length === 0 ? (
        <p className="muted">
          {p.user && !p.remote && !p.remoteError
            ? "Đang tải lịch sử…"
            : "Chưa có mục nào. Mỗi lần giấu tin ở tab Giấu tin hoặc Hàng loạt sẽ hiện ở đây."}
        </p>
      ) : (
        <ul className="history-list">
          {rows.map((r) => (
            <li key={r.key} className="history-item">
              <img src={r.thumb} alt="" loading="lazy" />
              <div className="history-body">
                <div className="history-title">
                  <strong>{r.name}</strong>
                  <span className={`tag ${r.saved ? "tag-intact" : "tag-partial"}`}>{r.saved ? "Đã lưu" : "Chỉ trong phiên"}</span>
                </div>
                <p className="muted small">
                  {dateFmt.format(r.createdAt)} · {KIND[r.kind]}
                  {r.encrypted ? " · có mật khẩu" : ""} · {r.width} × {r.height} px · lặp ×{r.redundancy}
                  {r.psnr !== null ? ` · ${r.psnr.toFixed(1)} dB` : ""} · {formatBytes(r.bytes)}
                </p>
                {r.note && <p className="small text-danger">Chưa lưu được vào tài khoản: {r.note}</p>}
                <div className="actions">
                  <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={() => act(r.key, () => zip(r))}>
                    Tải ảnh + khoá (.zip)
                  </button>
                  <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={() => act(r.key, () => open(r))}>
                    Mở ở Đọc tin
                  </button>
                  <button type="button" className="btn btn-sm btn-danger" disabled={busy !== null} onClick={() => act(r.key, r.remove)}>
                    Xoá
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {p.user && (p.remote?.items.length ?? 0) > 0 && (
        <div className="actions">
          {confirmClear ? (
            <>
              <span className="small text-danger">Xoá toàn bộ {p.remote!.items.length} mục đã lưu? Không khôi phục được.</span>
              <button
                type="button"
                className="btn btn-sm btn-danger"
                disabled={busy !== null}
                onClick={() =>
                  act("clear", async () => {
                    await api.historyClear();
                    setConfirmClear(false);
                    await p.onRemoteChanged();
                  })
                }
              >
                Xoá hết
              </button>
              <button type="button" className="btn btn-sm" onClick={() => setConfirmClear(false)}>Thôi</button>
            </>
          ) : (
            <button type="button" className="link-btn" onClick={() => setConfirmClear(true)}>Xoá toàn bộ lịch sử đã lưu</button>
          )}
        </div>
      )}

      <ProofCheck />

      {p.user && <AccountSettings onSignedOut={p.onSignedOut} hasRecovery={!!p.user.has_recovery} has2fa={!!p.user.has_2fa} />}
    </div>
  );
}

const eventFmt = new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "medium" });

function qrDataUrl(text: string): string {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  return qr.createDataURL(5, 10);
}

function AccountSettings({ onSignedOut, hasRecovery, has2fa }: { onSignedOut: () => void; hasRecovery: boolean; has2fa: boolean }) {
  const [twoFa, setTwoFa] = useState(has2fa);
  const [tfPw, setTfPw] = useState("");
  const [tfSetup, setTfSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [tfCode, setTfCode] = useState("");

  function twoFaStart(e: FormEvent) {
    e.preventDefault();
    void run(async () => {
      if (twoFa) {
        await api.twoFaDisable(tfPw);
        setTwoFa(false);
        setMsg({ kind: "ok", text: "Đã tắt xác thực hai lớp." });
      } else {
        setTfSetup(await api.twoFaSetup(tfPw));
      }
      setTfPw("");
    });
  }

  function twoFaConfirm(e: FormEvent) {
    e.preventDefault();
    void run(async () => {
      await api.twoFaEnable(tfCode);
      setTwoFa(true);
      setTfSetup(null);
      setTfCode("");
      setMsg({ kind: "ok", text: "Đã bật xác thực hai lớp. Từ lần đăng nhập sau sẽ cần mã 6 số." });
    });
  }

  const [open, setOpen] = useState(false);
  const [rcPw, setRcPw] = useState("");
  const [newCode, setNewCode] = useState<string | null>(null);
  const [hasCode, setHasCode] = useState(hasRecovery);
  const [events, setEvents] = useState<AuthEvent[] | null>(null);

  useEffect(() => {
    if (!open) return;
    api.activity().then(setEvents, () => setEvents([]));
  }, [open]);

  function recoveryCode(e: FormEvent) {
    e.preventDefault();
    void run(async () => {
      const u = await api.newRecoveryCode(rcPw);
      setRcPw("");
      setNewCode(u.recovery_code ?? null);
      setHasCode(true);
    });
  }

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [delPw, setDelPw] = useState("");
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  function changePw(e: FormEvent) {
    e.preventDefault();
    void run(async () => {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setMsg({ kind: "ok", text: "Đã đổi mật khẩu. Các thiết bị khác đã bị đăng xuất." });
    });
  }

  function remove(e: FormEvent) {
    e.preventDefault();
    void run(async () => {
      await api.deleteAccount(delPw);
      onSignedOut();
    });
  }

  return (
    <div className="stack">
      {!hasCode && (
        <Alert kind="warn">
          Tài khoản này chưa có <strong>mã khôi phục</strong>: quên mật khẩu là mất tài khoản. Mở Cài đặt tài khoản để
          tạo mã.
        </Alert>
      )}
      <button type="button" className="link-btn" onClick={() => setOpen((v) => !v)}>
        {open ? "Ẩn cài đặt tài khoản" : "Cài đặt tài khoản"}
      </button>
      {open && (
        <div className="advanced">
          {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
          <form className="stack" onSubmit={changePw}>
            <span className="field-label">Đổi mật khẩu</span>
            <input type="password" placeholder="Mật khẩu hiện tại" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
            <input type="password" placeholder="Mật khẩu mới (ít nhất 8 ký tự)" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
            <div className="actions">
              <button className="btn btn-sm" disabled={busy || !current || next.length < 8}>Đổi mật khẩu</button>
            </div>
          </form>
          {tfSetup ? (
            <form className="stack" onSubmit={twoFaConfirm}>
              <span className="field-label">Xác thực hai lớp: quét mã</span>
              <span className="muted small">
                Mở Google Authenticator, Microsoft Authenticator hoặc ứng dụng tương tự, quét mã QR này (hoặc nhập khoá
                bên dưới), rồi nhập mã 6 số ứng dụng hiện ra để hoàn tất.
              </span>
              <img src={qrDataUrl(tfSetup.uri)} alt="Mã QR để thêm vào ứng dụng xác thực" width={200} height={200} style={{ background: "#fff", borderRadius: 6 }} />
              <pre className="message" style={{ userSelect: "all", wordBreak: "break-all", whiteSpace: "pre-wrap" }}>{tfSetup.secret.replace(/(.{4})/g, "$1 ").trim()}</pre>
              <input type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={7} placeholder="Mã 6 số" value={tfCode} onChange={(e) => setTfCode(e.target.value.replace(/[^0-9 ]/g, ""))} />
              <div className="actions">
                <button className="btn btn-sm btn-primary" disabled={busy || tfCode.replace(/ /g, "").length !== 6}>Bật xác thực hai lớp</button>
                <button type="button" className="btn btn-sm" onClick={() => setTfSetup(null)}>Huỷ</button>
              </div>
            </form>
          ) : (
            <form className="stack" onSubmit={twoFaStart}>
              <span className="field-label">Xác thực hai lớp (2FA): {twoFa ? "đang bật" : "đang tắt"}</span>
              <span className="muted small">
                {twoFa
                  ? "Đăng nhập cần thêm mã 6 số từ ứng dụng xác thực. Mất điện thoại thì dùng mã khôi phục để vào lại."
                  : "Khi bật, đăng nhập cần thêm mã 6 số từ ứng dụng trên điện thoại, nên lộ mật khẩu cũng chưa mất tài khoản. Hãy có mã khôi phục trước khi bật."}
              </span>
              <input type="password" placeholder="Nhập mật khẩu để xác nhận" autoComplete="current-password" value={tfPw} onChange={(e) => setTfPw(e.target.value)} />
              <div className="actions">
                <button className={`btn btn-sm${twoFa ? " btn-danger" : ""}`} disabled={busy || !tfPw}>{twoFa ? "Tắt xác thực hai lớp" : "Cài xác thực hai lớp"}</button>
              </div>
            </form>
          )}
          <form className="stack" onSubmit={recoveryCode}>
            <span className="field-label">Mã khôi phục</span>
            <span className="muted small">
              Dùng để đặt lại mật khẩu khi quên. Tạo mã mới thì mã cũ hết hiệu lực. Mã chỉ hiện một lần.
            </span>
            {newCode && (
              <>
                <pre className="message" style={{ textAlign: "center", userSelect: "all" }}>{newCode}</pre>
                <span className="small text-danger">Hãy chép mã này ngay, đóng trang là không xem lại được.</span>
              </>
            )}
            <input type="password" placeholder="Nhập mật khẩu để xác nhận" autoComplete="current-password" value={rcPw} onChange={(e) => setRcPw(e.target.value)} />
            <div className="actions">
              <button className="btn btn-sm" disabled={busy || !rcPw}>{hasCode ? "Tạo mã khôi phục mới" : "Tạo mã khôi phục"}</button>
            </div>
          </form>
          <div className="stack">
            <span className="field-label">Hoạt động gần đây</span>
            <span className="muted small">
              Đăng nhập, đổi mật khẩu và các thao tác quan trọng trong 90 ngày. Thấy mục lạ thì đổi mật khẩu ngay.
            </span>
            {events === null ? (
              <span className="muted small">Đang tải…</span>
            ) : events.length === 0 ? (
              <span className="muted small">Chưa có hoạt động nào được ghi.</span>
            ) : (
              <ul className="muted small" style={{ margin: 0, paddingLeft: 18 }}>
                {events.map((ev, i) => (
                  <li key={i} className={ev.event.endsWith("_fail") ? "text-danger" : ""}>
                    {eventFmt.format(new Date(ev.ts * 1000))} · {ev.label} · {ev.ip}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <form className="stack" onSubmit={remove}>
            <span className="field-label">Xoá tài khoản</span>
            <span className="muted small">Xoá vĩnh viễn tài khoản cùng toàn bộ ảnh và khoá đã lưu trên máy chủ.</span>
            <input type="password" placeholder="Nhập mật khẩu để xác nhận" autoComplete="current-password" value={delPw} onChange={(e) => setDelPw(e.target.value)} />
            <div className="actions">
              <button className="btn btn-sm btn-danger" disabled={busy || !delPw}>Xoá tài khoản vĩnh viễn</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
