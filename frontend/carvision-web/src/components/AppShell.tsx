import { useEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import * as Popover from "@radix-ui/react-popover";
import {
  Bell,
  BrainCircuit,
  Camera,
  FolderCheck,
  Gauge,
  ListChecks,
  LogOut,
  Menu,
  Moon,
  Network,
  Radar,
  ShieldCheck,
  Sun,
  Upload,
  X,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import { NetworkBanner } from "@/components/PageState";
import { useAuth } from "@/context/AuthContext";
import Button from "@/design-system/components/Button";
import { classifyError } from "@/hooks/useApiQuery";
import useTheme from "@/hooks/useTheme";
import { request } from "@/lib/api";
import { cn, formatTimestamp } from "@/lib/utils";
import type { NotificationItem, NotificationListResponse } from "@/types/api";

const menu = [
  { to: "/", label: "Dashboard", icon: Gauge },
  { to: "/live", label: "Live", icon: Radar },
  { to: "/detections", label: "Detections", icon: ShieldCheck },
  { to: "/upload", label: "Media", icon: Upload },
  { to: "/training-data", label: "Training Data", icon: FolderCheck },
  { to: "/cameras", label: "Cameras", icon: Camera },
  { to: "/allowed", label: "Allowed Plates", icon: ListChecks },
  { to: "/discovery", label: "Discovery", icon: Network },
  { to: "/training", label: "Training", icon: BrainCircuit },
];

function HorizontalNav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex items-center gap-1 overflow-x-auto">
      {menu.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex shrink-0 items-center gap-2 rounded-full border px-3 py-2 text-xs font-medium transition-colors",
                isActive
                  ? "border-foreground/15 bg-foreground text-background"
                  : "border-border/70 bg-card/70 text-muted-foreground hover:border-border hover:text-foreground"
              )
            }
          >
            <Icon className="size-3.5" />
            <span>{item.label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}

function MobileNav({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-slate-950/60 backdrop-blur-sm" />
        <Dialog.Content className="fixed inset-x-4 top-4 z-[90] rounded-[var(--radius-lg)] border border-border bg-card p-4 shadow-shell">
          <div className="mb-4 flex items-center justify-between">
            <Dialog.Title className="text-sm font-semibold text-foreground">Navigation</Dialog.Title>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Close navigation">
                <X className="size-4" />
              </Button>
            </Dialog.Close>
          </div>
          <div className="grid gap-2">
            <HorizontalNav onNavigate={() => onOpenChange(false)} />
            <NavLink
              to="/notifications"
              onClick={() => onOpenChange(false)}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-medium transition-colors",
                  isActive
                    ? "border-foreground/15 bg-foreground text-background"
                    : "border-border/70 bg-card/70 text-muted-foreground hover:border-border hover:text-foreground"
                )
              }
            >
              <Bell className="size-3.5" />
              <span>Notifications</span>
            </NavLink>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { token, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [notifItems, setNotifItems] = useState<NotificationItem[]>([]);
  const [notifUnread, setNotifUnread] = useState(0);
  const [apiFails, setApiFails] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;

    const pingBackend = async () => {
      try {
        await request("/api/v1/cameras", { token });
        if (!mountedRef.current) return;
        setApiFails(0);
        setDismissed(false);
      } catch (error) {
        if (!mountedRef.current) return;
        const classified = classifyError(error);
        if (classified.type === "network" || classified.type === "server") {
          setApiFails((current) => current + 1);
        }
      } finally {
        timer = setTimeout(pingBackend, 6000);
      }
    };

    void pingBackend();
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [token]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;

    const loadNotifications = async () => {
      try {
        const response = await request<NotificationListResponse>("/api/v1/notifications?limit=8", { token });
        if (!mountedRef.current) return;
        setNotifItems(response.items || []);
        setNotifUnread(response.unread || 0);
      } catch {
        // Notification polling is best effort.
      } finally {
        timer = setTimeout(loadNotifications, 8000);
      }
    };

    void loadNotifications();
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [token]);

  return (
    <div className="min-h-screen">
      <div className="mx-auto flex min-h-screen w-full max-w-[1680px] flex-col px-4 py-4 sm:px-6 lg:px-8">
        <NetworkBanner consecutive={dismissed ? 0 : apiFails} onDismiss={() => setDismissed(true)} />

        <header className="sticky top-4 z-40 mt-3 rounded-[var(--radius-xl)] border border-border/70 bg-card/85 px-3 py-2 shadow-card backdrop-blur-shell">
          <div className="flex items-center gap-2">
            <div className="lg:hidden">
              <Button variant="outline" size="icon" onClick={() => setMobileNavOpen(true)} aria-label="Open navigation">
                <Menu className="size-4" />
              </Button>
            </div>

            <div className="hidden min-w-0 flex-1 lg:block">
              <HorizontalNav />
            </div>

            <div className="ml-auto flex items-center gap-2">
              <Button
                variant="outline"
                size="icon"
                onClick={toggleTheme}
                aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
                title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              >
                {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
              </Button>

              <Popover.Root>
                <Popover.Trigger asChild>
                  <Button variant="outline" size="icon" className="relative" aria-label="Open notifications">
                    <Bell className="size-4" />
                    {notifUnread > 0 ? (
                      <span className="absolute -right-1 -top-1 min-w-[18px] rounded-full bg-foreground px-1.5 py-0.5 text-[10px] font-semibold leading-none text-background">
                        {notifUnread > 99 ? "99+" : notifUnread}
                      </span>
                    ) : null}
                  </Button>
                </Popover.Trigger>
                <Popover.Portal>
                  <Popover.Content
                    align="end"
                    sideOffset={10}
                    className="z-[70] w-[min(92vw,380px)] rounded-[var(--radius-lg)] border border-border bg-popover/95 p-4 shadow-shell backdrop-blur-shell"
                  >
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-foreground">Notifications</p>
                      <NavLink to="/notifications" className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                        Open
                      </NavLink>
                    </div>
                    <div className="space-y-3">
                      {notifItems.length ? (
                        notifItems.map((item) => (
                          <div
                            key={item.id}
                            className={cn(
                              "rounded-[var(--radius-md)] border p-3",
                              item.is_read ? "border-border bg-white/5" : "border-primary/25 bg-primary/10"
                            )}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <p className="text-sm font-semibold text-foreground">{item.title}</p>
                              <span className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                                {item.is_read ? "Read" : "Unread"}
                              </span>
                            </div>
                            <p className="mt-1 text-sm text-muted-foreground">{item.message}</p>
                            <p className="mt-2 text-xs text-muted-foreground/80">{formatTimestamp(item.created_at)}</p>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-[var(--radius-md)] border border-border bg-white/5 px-4 py-5 text-sm text-muted-foreground">
                          No notifications available.
                        </div>
                      )}
                    </div>
                  </Popover.Content>
                </Popover.Portal>
              </Popover.Root>

              <Button variant="ghost" size="sm" icon={<LogOut className="size-4" />} onClick={logout}>
                Logout
              </Button>
            </div>
          </div>
        </header>

        <MobileNav open={mobileNavOpen} onOpenChange={setMobileNavOpen} />

        <main className="min-w-0 flex-1 pt-4 pb-8">{children}</main>
      </div>
    </div>
  );
}
