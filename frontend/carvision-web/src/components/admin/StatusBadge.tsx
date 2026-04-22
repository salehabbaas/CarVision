import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const styles: Record<string, string> = {
  complete: "border-emerald-400/30 bg-emerald-400/10 text-emerald-100",
  running: "border-sky-400/30 bg-sky-400/10 text-sky-100",
  queued: "border-amber-400/30 bg-amber-400/10 text-amber-100",
  stopping: "border-amber-400/30 bg-amber-400/10 text-amber-100",
  stale: "border-orange-400/30 bg-orange-400/10 text-orange-100",
  stopped: "border-slate-400/30 bg-slate-400/10 text-slate-100",
  failed: "border-rose-400/30 bg-rose-400/10 text-rose-100",
  idle: "border-border bg-white/5 text-muted-foreground",
  allowed: "border-emerald-400/30 bg-emerald-400/10 text-emerald-100",
  denied: "border-rose-400/30 bg-rose-400/10 text-rose-100",
  unread: "border-primary/30 bg-primary/10 text-sky-100",
  read: "border-border bg-white/5 text-muted-foreground",
};

interface StatusBadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: string;
}

export default function StatusBadge({ tone = "idle", className, children, ...props }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em]",
        styles[tone] || styles.idle,
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}
