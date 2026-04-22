import { AlertTriangle, HelpCircle, RefreshCw, ServerCrash, ShieldOff, WifiOff } from "lucide-react";

import Button from "@/design-system/components/Button";
import SurfaceCard from "@/components/admin/SurfaceCard";
import { cn } from "@/lib/utils";
import type { ClassifiedError } from "@/hooks/useApiQuery";

function SkeletonCard() {
  return (
    <SurfaceCard className="space-y-3">
      <div className="h-3 w-1/3 animate-pulse rounded-full bg-white/10" />
      <div className="h-7 w-2/3 animate-pulse rounded-full bg-white/10" />
      <div className="h-3 w-1/2 animate-pulse rounded-full bg-white/10" />
    </SurfaceCard>
  );
}

export function LoadingState({ rows = 3, message = "Loading data...", inline = false }: { rows?: number; message?: string; inline?: boolean }) {
  if (inline) {
    return (
      <div className="flex items-center gap-3 py-5 text-sm text-muted-foreground">
        <RefreshCw className="size-4 animate-spin" />
        <span>{message}</span>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {Array.from({ length: rows }).map((_, index) => (
        <SkeletonCard key={index} />
      ))}
      <div className="flex items-center gap-3 px-1 text-sm text-muted-foreground">
        <RefreshCw className="size-4 animate-spin" />
        <span>{message}</span>
      </div>
    </div>
  );
}

const ERROR_META = {
  network: {
    Icon: WifiOff,
    title: "Cannot reach server",
    hint: "Check connectivity and verify the CarVision backend is running.",
  },
  auth: {
    Icon: ShieldOff,
    title: "Session expired",
    hint: "Your secure session is no longer valid. Sign in again.",
  },
  permission: {
    Icon: ShieldOff,
    title: "Access denied",
    hint: "This account does not have permission to view the requested resource.",
  },
  server: {
    Icon: ServerCrash,
    title: "Server error",
    hint: "The backend returned an internal error. Check API logs and retry.",
  },
  unknown: {
    Icon: HelpCircle,
    title: "Unexpected error",
    hint: "The request failed in an unexpected way.",
  },
} as const;

export function ErrorState({ error, onRetry, compact = false }: { error?: ClassifiedError | null; onRetry?: () => void; compact?: boolean }) {
  const meta = ERROR_META[error?.type || "unknown"];
  const { Icon, title, hint } = meta;

  if (compact) {
    return (
      <div className="flex items-center gap-3 rounded-[var(--radius-md)] border border-destructive/30 bg-destructive/10 px-4 py-3">
        <Icon className="size-4 shrink-0 text-destructive" />
        <div className="min-w-0 flex-1">
          <span className="font-semibold text-destructive">{title}: </span>
          <span className="text-sm text-muted-foreground">{error?.message || hint}</span>
        </div>
        {onRetry ? <Button size="sm" variant="outline" onClick={onRetry} icon={<RefreshCw className="size-3.5" />}>Retry</Button> : null}
      </div>
    );
  }

  return (
    <SurfaceCard className="flex min-h-[340px] flex-col items-center justify-center gap-5 text-center">
      <div className="rounded-full border border-destructive/30 bg-destructive/10 p-4 text-destructive">
        <Icon className="size-8" />
      </div>
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold text-foreground">{title}</h2>
        <p className="mx-auto max-w-xl text-sm text-muted-foreground">{error?.message || hint}</p>
        <p className="mx-auto max-w-xl text-xs uppercase tracking-[0.2em] text-muted-foreground/80">{hint}</p>
      </div>
      {onRetry ? <Button variant="primary" onClick={onRetry} icon={<RefreshCw className="size-4" />}>Try again</Button> : null}
    </SurfaceCard>
  );
}

export function StaleBanner({ error, onRetry }: { error?: ClassifiedError | null; onRetry?: () => void }) {
  if (!error) return null;
  const meta = ERROR_META[error.type || "unknown"];
  const { Icon, title } = meta;

  return (
    <div className="flex items-center gap-3 rounded-[var(--radius-md)] border border-warning/30 bg-warning/10 px-4 py-3 text-sm">
      <Icon className="size-4 shrink-0 text-warning" />
      <span className="font-semibold text-warning">{title}</span>
      <span className="min-w-0 flex-1 text-muted-foreground">{error.message} - showing last known data</span>
      {onRetry ? <Button size="sm" variant="ghost" onClick={onRetry}>Retry</Button> : null}
    </div>
  );
}

export function EmptyState({ message = "No data found", sub }: { message?: string; sub?: string }) {
  return (
    <SurfaceCard className="flex min-h-[220px] flex-col items-center justify-center gap-2 text-center">
      <AlertTriangle className="size-8 text-muted-foreground/70" />
      <h3 className="text-lg font-semibold text-foreground">{message}</h3>
      {sub ? <p className="max-w-lg text-sm text-muted-foreground">{sub}</p> : null}
    </SurfaceCard>
  );
}

export function NetworkBanner({ consecutive = 0, onDismiss }: { consecutive?: number; onDismiss?: () => void }) {
  if (consecutive < 2) return null;

  return (
    <div className="flex items-center gap-3 border-b border-destructive/20 bg-destructive/10 px-4 py-3 text-sm">
      <WifiOff className="size-4 shrink-0 text-destructive" />
      <span className="font-semibold text-destructive">Server unreachable</span>
      <span className="flex-1 text-muted-foreground">
        {consecutive >= 5
          ? "The backend has been unreachable for a while. Verify Docker and the API process."
          : "Cannot reach the backend. Automatic retries are in progress."}
      </span>
      {onDismiss ? <Button size="sm" variant="ghost" onClick={onDismiss}>Dismiss</Button> : null}
    </div>
  );
}

export function ScreenCenter({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("flex min-h-screen items-center justify-center px-6", className)}>{children}</div>;
}
