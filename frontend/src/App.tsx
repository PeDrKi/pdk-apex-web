import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Health, type HistoryList, type Session, type User } from "./api";
import { AuthDialog } from "./components/AuthDialog";
import { HistoryPanel } from "./components/HistoryPanel";
import { loadAutoSave, MAX_LOCAL, storeAutoSave, toLocal, type LocalEntry, type NewEntry } from "./lib/history";
import { BatchPanel } from "./components/BatchPanel";
import { AttackPanel } from "./components/AttackPanel";
import { ComparePanel } from "./components/ComparePanel";
import { AboutPanel } from "./components/AboutPanel";
import { EmbedPanel } from "./components/EmbedPanel";
import { ExtractPanel } from "./components/ExtractPanel";

type Tab = "embed" | "extract" | "batch" | "attack" | "compare" | "history" | "about";

const TABS: { id: Tab; label: string }[] = [
  { id: "embed", label: "Giấu tin" },
  { id: "extract", label: "Đọc tin" },
  { id: "batch", label: "Hàng loạt" },
  { id: "attack", label: "Thử tấn công" },
  { id: "compare", label: "So sánh" },
  { id: "history", label: "Lịch sử" },
  { id: "about", label: "Cách hoạt động" },
];

function tabFromHash(): Tab {
  const h = window.location.hash.replace("#", "");
  return (TABS.find((t) => t.id === h)?.id ?? "embed") as Tab;
}

export default function App() {
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);
  const [waking, setWaking] = useState(false);
  const [session, setSession] = useState<Session | null>(null);

  // Tài khoản và lịch sử. Khách: `local` chỉ nằm trong bộ nhớ của tab này.
  const [user, setUser] = useState<User | null>(null);
  const [registrationOpen, setRegistrationOpen] = useState(true);
  const [authMode, setAuthMode] = useState<"login" | "register" | null>(null);
  const [local, setLocal] = useState<LocalEntry[]>([]);
  const [remote, setRemote] = useState<HistoryList | null>(null);
  const [remoteError, setRemoteError] = useState<string | null>(null);
  const [autoSave, setAutoSave] = useState(loadAutoSave);
  const [extractPreset, setExtractPreset] = useState<{ image: File; keys: File } | null>(null);
  // record() được gọi từ các tác vụ chạy dài (hàng loạt) nên đọc trạng thái mới nhất qua ref.
  const live = useRef({ user, autoSave });
  live.current = { user, autoSave };

  const signedOut = useCallback(() => {
    setUser(null);
    setRemote(null);
    setRemoteError(null);
  }, []);

  const refreshRemote = useCallback(async () => {
    try {
      setRemote(await api.history());
      setRemoteError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) signedOut(); // phiên đã hết hạn
      else setRemoteError((e as Error).message);
    }
  }, [signedOut]);

  const addLocal = useCallback((e: NewEntry, saveError?: string) => {
    setLocal((prev) => {
      const next = [toLocal(e, saveError), ...prev];
      for (const old of next.slice(MAX_LOCAL)) URL.revokeObjectURL(old.thumbUrl);
      return next.slice(0, MAX_LOCAL);
    });
  }, []);

  const removeLocal = useCallback((id: string) => {
    setLocal((prev) => {
      const hit = prev.find((x) => x.id === id);
      if (hit) URL.revokeObjectURL(hit.thumbUrl);
      return prev.filter((x) => x.id !== id);
    });
  }, []);

  /** Ghi nhận một lần giấu tin: có tài khoản thì lưu lên máy chủ, không thì giữ trong phiên. */
  const record = useCallback(
    async (e: NewEntry) => {
      if (e.savedId) return refreshRemote(); // máy chủ đã lưu ngay lúc giấu tin
      if (e.saveError) return addLocal(e, e.saveError);
      if (!live.current.user || !live.current.autoSave) return addLocal(e);
      try {
        await api.historySave(e);
        await refreshRemote();
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) signedOut();
        addLocal(e, (err as Error).message);
      }
    },
    [addLocal, refreshRemote, signedOut],
  );

  /** Đưa các mục của phiên (làm khi chưa đăng nhập) vào tài khoản. */
  const saveLocal = useCallback(async () => {
    let firstError: string | null = null;
    for (const e of [...local].reverse()) {
      try {
        await api.historySave(e);
        removeLocal(e.id);
      } catch (err) {
        firstError ??= (err as Error).message;
      }
    }
    await refreshRemote();
    if (firstError) throw new Error(firstError);
  }, [local, removeLocal, refreshRemote]);

  async function logout() {
    try {
      await api.logout();
    } finally {
      signedOut();
    }
  }

  useEffect(() => {
    api
      .me()
      .then((m) => {
        setUser(m.user);
        setRegistrationOpen(m.registration_open);
        if (m.user) void refreshRemote();
      })
      .catch(() => undefined);
  }, [refreshRemote]);

  useEffect(() => {
    // Máy chủ gói miễn phí ngủ khi không ai dùng và mất khoảng một phút để dậy:
    // hỏi lại vài lần thay vì báo mất kết nối ngay.
    let alive = true;
    const slow = setTimeout(() => alive && setWaking(true), 2500);
    (async () => {
      const until = Date.now() + 150_000;
      for (;;) {
        try {
          const h = await api.health();
          if (alive) setHealth(h);
          break;
        } catch {
          if (!alive) return;
          setWaking(true);
          if (Date.now() > until) {
            setOffline(true);
            break;
          }
          await new Promise((r) => setTimeout(r, 4000));
        }
      }
      clearTimeout(slow);
      if (alive) setWaking(false);
    })();
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => {
      alive = false;
      clearTimeout(slow);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <img src="/logo.png" alt="Logo Perfect Dragon King" width={56} height={56} />
          <div>
            <h1>PDK<span>::</span>APEX</h1>
            <p>Perfect Dragon King · Giấu tin trong ảnh, bền vững với nén</p>
          </div>
        </div>
        <div className="header-right">
          <span className={`status${offline ? " is-off" : health ? " is-on" : ""}`}>
            {offline
              ? "Mất kết nối máy chủ"
              : health
                ? `apexmark ${health.apexmark_version}`
                : waking
                  ? "Đang đánh thức máy chủ…"
                  : "Đang kết nối…"}
          </span>
          {user ? (
            <>
              <a className="user-chip" href="#history" title="Xem lịch sử đã lưu">{user.username}</a>
              <button type="button" className="btn btn-sm" onClick={logout}>Đăng xuất</button>
            </>
          ) : (
            <>
              <button type="button" className="btn btn-sm" onClick={() => setAuthMode("login")}>Đăng nhập</button>
              {registrationOpen && (
                <button type="button" className="btn btn-sm btn-primary" onClick={() => setAuthMode("register")}>Đăng ký</button>
              )}
            </>
          )}
        </div>
      </header>

      <ul className="badges" aria-label="Cơ chế bảo vệ">
        <li><b>AES-256-GCM</b> mã hoá tại trình duyệt</li>
        <li><b>PBKDF2</b> 600.000 vòng</li>
        <li><b>CRC32</b> kiểm tra toàn vẹn</li>
        <li><b>ZERO-LOG</b> không lưu dữ liệu của khách</li>
      </ul>

      {waking && !health && !offline && (
        <p className="wake-note">
          Máy chủ đang khởi động lại sau thời gian nghỉ, thường mất khoảng một phút. Bạn vẫn có thể chọn ảnh trong lúc chờ.
        </p>
      )}

      <nav className="tabs" role="tablist">
        {TABS.map((t, i) => (
          <a
            key={t.id}
            href={`#${t.id}`}
            role="tab"
            data-n={`0${i + 1}`}
            data-count={t.id === "history" && local.length + (remote?.items.length ?? 0) > 0 ? local.length + (remote?.items.length ?? 0) : undefined}
            aria-selected={tab === t.id}
            className={`tab${tab === t.id ? " is-active" : ""}`}
          >
            {t.label}
          </a>
        ))}
      </nav>

      <main>
        <div hidden={tab !== "embed"}>
          <EmbedPanel
            maxRedundancy={health?.max_redundancy ?? 50}
            onResult={record}
            saveToAccount={!!user && autoSave}
            onSend={(target, s) => {
              setSession({ ...s });
              window.location.hash = target;
            }}
          />
        </div>
        <div hidden={tab !== "extract"}>
          <ExtractPanel syncAvailable={health?.sync_available ?? true} preset={extractPreset} />
        </div>
        <div hidden={tab !== "batch"}>
          <BatchPanel onResult={record} saveToAccount={!!user && autoSave} />
        </div>
        <div hidden={tab !== "attack"}>
          <AttackPanel session={session} />
        </div>
        <div hidden={tab !== "compare"}>
          <ComparePanel session={session} />
        </div>
        <div hidden={tab !== "history"}>
          <HistoryPanel
            user={user}
            local={local}
            remote={remote}
            remoteError={remoteError}
            autoSave={autoSave}
            onAutoSave={(on) => {
              setAutoSave(on);
              storeAutoSave(on);
            }}
            onLogin={setAuthMode}
            onSaveLocal={saveLocal}
            onDeleteLocal={removeLocal}
            onRemoteChanged={refreshRemote}
            onOpenExtract={(image, keys) => {
              setExtractPreset({ image, keys });
              window.location.hash = "extract";
            }}
            onSignedOut={signedOut}
          />
        </div>
        {tab === "about" && <AboutPanel />}
      </main>

      <footer className="footer muted small">
        {user
          ? "Máy chủ chỉ lưu những mục bạn thấy trong tab Lịch sử; mật khẩu nội dung không bao giờ được lưu"
          : "Khách: dữ liệu chỉ được xử lý trong bộ nhớ, máy chủ không lưu lại"}{" "}
        · PDK © {new Date().getFullYear()}
      </footer>

      {authMode && (
        <AuthDialog
          mode={authMode}
          registrationOpen={registrationOpen}
          onMode={setAuthMode}
          onClose={() => setAuthMode(null)}
          onDone={(u) => {
            setUser(u);
            setAuthMode(null);
            void refreshRemote();
          }}
        />
      )}
    </div>
  );
}
