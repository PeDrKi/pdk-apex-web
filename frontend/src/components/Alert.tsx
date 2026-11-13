import type { ReactNode } from "react";

export function Alert({ kind, children }: { kind: "error" | "warn" | "ok"; children: ReactNode }) {
  return (
    <div className={`alert alert-${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}
