import type { HTMLAttributes } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

import { cn } from "@/lib/utils";

const variants = {
  error: {
    icon: AlertCircle,
    className: "border-destructive/40 bg-destructive/10 text-rose-100",
  },
  success: {
    icon: CheckCircle2,
    className: "border-emerald-400/30 bg-emerald-400/10 text-emerald-100",
  },
  warning: {
    icon: AlertTriangle,
    className: "border-warning/40 bg-warning/10 text-amber-50",
  },
  info: {
    icon: Info,
    className: "border-primary/40 bg-primary/10 text-sky-100",
  },
} as const;

interface AlertProps extends HTMLAttributes<HTMLDivElement> {
  variant?: keyof typeof variants;
  onDismiss?: () => void;
}

export default function Alert({ variant = "info", onDismiss, children, className, ...props }: AlertProps) {
  const current = variants[variant];
  const Icon = current.icon;

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-[var(--radius-md)] border px-4 py-3 text-sm shadow-card",
        current.className,
        className
      )}
      role="alert"
      {...props}
    >
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="flex-1">{children}</div>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="rounded-full p-1 opacity-70 transition hover:bg-white/10 hover:opacity-100"
          aria-label="Dismiss"
        >
          <X className="size-3.5" />
        </button>
      ) : null}
    </div>
  );
}
