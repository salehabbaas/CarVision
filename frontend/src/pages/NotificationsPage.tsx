import { useEffect, useState } from "react";
import { BellRing, CheckCheck } from "lucide-react";

import { EmptyState, ErrorState, LoadingState } from "@/components/PageState";
import PageHeader from "@/components/admin/PageHeader";
import SectionToolbar from "@/components/admin/SectionToolbar";
import StatusBadge from "@/components/admin/StatusBadge";
import SurfaceCard from "@/components/admin/SurfaceCard";
import { useAuth } from "@/context/AuthContext";
import Button from "@/design-system/components/Button";
import { request } from "@/lib/api";
import { formatTimestamp } from "@/lib/utils";
import type { NotificationItem, NotificationListResponse } from "@/types/api";

export default function NotificationsPage() {
  const { token } = useAuth();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [pageLoading, setPageLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    const response = await request<NotificationListResponse>("/api/v1/notifications?limit=150", { token });
    setItems(response.items || []);
    setUnread(response.unread || 0);
    setError("");
  }

  useEffect(() => {
    void load()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load notifications"))
      .finally(() => setPageLoading(false));

    const timer = setInterval(() => {
      void load().catch(() => null);
    }, 4000);

    return () => clearInterval(timer);
  }, []);

  async function markRead(id: number) {
    await request(`/api/v1/notifications/${id}/read`, { token, method: "POST" });
    await load();
  }

  async function markAll() {
    await request("/api/v1/notifications/read_all", { token, method: "POST" });
    await load();
  }

  if (pageLoading) return <LoadingState rows={4} message="Loading notification center..." />;
  if (error && !items.length) {
    return (
      <ErrorState
        error={{ message: error, type: "unknown" }}
        onRetry={() => {
          setPageLoading(true);
          void load()
            .catch((err) => setError(err instanceof Error ? err.message : "Failed to load notifications"))
            .finally(() => setPageLoading(false));
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Signals"
        title="Notification center"
        description="Review system alerts, operator prompts, and workflow events from one stream."
      />

      <SectionToolbar>
        <div className="flex items-center gap-3">
          <div className="rounded-2xl border border-primary/20 bg-primary/10 p-3 text-primary">
            <BellRing className="size-5" />
          </div>
          <div>
            <p className="text-sm font-semibold text-foreground">Unread alerts</p>
            <p className="text-sm text-muted-foreground">Keep operator review queues under control.</p>
          </div>
          <StatusBadge tone={unread ? "unread" : "read"}>{unread} unread</StatusBadge>
        </div>
        <Button variant="primary" icon={<CheckCheck className="size-4" />} onClick={markAll}>
          Mark all read
        </Button>
      </SectionToolbar>

      {error ? (
        <SurfaceCard className="border-warning/30 bg-warning/10 py-4 text-sm text-amber-50">
          {error}
        </SurfaceCard>
      ) : null}

      {items.length ? (
        <div className="grid gap-4">
          {items.map((item) => (
            <SurfaceCard
              key={item.id}
              className={item.is_read ? "bg-card/70" : "border-primary/25 bg-primary/10"}
            >
              <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-3">
                    <h3 className="text-lg font-semibold text-foreground">{item.title}</h3>
                    <StatusBadge tone={item.is_read ? "read" : "unread"}>
                      {item.is_read ? "Read" : "Unread"}
                    </StatusBadge>
                  </div>
                  <p className="max-w-3xl text-sm text-muted-foreground">{item.message}</p>
                  <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground/80">
                    {formatTimestamp(item.created_at)}
                  </p>
                </div>
                {!item.is_read ? (
                  <Button variant="outline" onClick={() => void markRead(item.id)}>
                    Mark read
                  </Button>
                ) : null}
              </div>
            </SurfaceCard>
          ))}
        </div>
      ) : (
        <EmptyState message="No notifications yet" sub="New system events and operator prompts will appear here." />
      )}
    </div>
  );
}
