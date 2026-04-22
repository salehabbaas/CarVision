import { useMemo } from "react";
import { Activity, BadgeCheck, Bell, Camera, ClipboardCheck, ShieldAlert, Users } from "lucide-react";
import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
} from "chart.js";
import { Bar, Doughnut, Line } from "react-chartjs-2";

import MetricChartCard from "@/components/admin/MetricChartCard";
import PageHeader from "@/components/admin/PageHeader";
import SectionToolbar from "@/components/admin/SectionToolbar";
import StatCard from "@/components/admin/StatCard";
import StatusBadge from "@/components/admin/StatusBadge";
import SurfaceCard from "@/components/admin/SurfaceCard";
import { ErrorState, LoadingState, StaleBanner } from "@/components/PageState";
import { useAuth } from "@/context/AuthContext";
import { useApiQuery } from "@/hooks/useApiQuery";
import { request } from "@/lib/api";
import type { DashboardSummary } from "@/types/api";

ChartJS.register(ArcElement, CategoryScale, Filler, Legend, LineElement, BarElement, LinearScale, PointElement, Tooltip);

const cards = [
  { key: "detections", label: "Detections", icon: Activity },
  { key: "active_cameras", label: "Active Cameras", icon: Camera },
  { key: "allowed", label: "Allowed", icon: BadgeCheck },
  { key: "denied", label: "Denied", icon: ShieldAlert },
  { key: "unread_notifications", label: "Unread Alerts", icon: Bell },
  { key: "users_active", label: "Active Users", icon: Users, futureKey: "users.active" },
  { key: "actions_pending", label: "Pending Actions", icon: ClipboardCheck, futureKey: "actions.pending" },
];

function getNestedValue(object: Record<string, any>, path?: string) {
  if (!path) return undefined;
  return path.split(".").reduce<any>((accumulator, key) => (accumulator ? accumulator[key] : undefined), object);
}

function chartOptions(legend = true) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index" as const, intersect: false },
    plugins: {
      legend: {
        display: legend,
        labels: { color: "#d9e8ff", usePointStyle: true, boxWidth: 8 },
      },
      tooltip: { enabled: true },
    },
    scales: {
      x: {
        ticks: { color: "#92a7c5" },
        grid: { color: "rgba(143, 173, 204, 0.1)" },
      },
      y: {
        ticks: { color: "#92a7c5" },
        grid: { color: "rgba(143, 173, 204, 0.1)" },
        beginAtZero: true,
      },
    },
  };
}

export default function DashboardPage() {
  const { token } = useAuth();
  const { data, loading, error, refetch, lastUpdated } = useApiQuery<DashboardSummary>(
    () => request<DashboardSummary>("/api/v1/dashboard/summary", { token }),
    { pollInterval: 5000, deps: [token], keepOnError: true }
  );

  const totals = data?.totals || {};
  const details = data?.details || {};
  const charts = data?.charts || {};
  const training = data?.training || {};
  const future = data?.future_metrics || {};
  const events = data?.recent_events || [];

  const lineData = useMemo(
    () => ({
      labels: charts.hourly_activity?.labels || [],
      datasets: [
        {
          label: "Detections",
          data: charts.hourly_activity?.detections || [],
          borderColor: "#38bdf8",
          backgroundColor: "rgba(56,189,248,0.18)",
          fill: true,
          tension: 0.3,
          pointRadius: 2,
        },
        {
          label: "Allowed",
          data: charts.hourly_activity?.allowed || [],
          borderColor: "#34d399",
          backgroundColor: "rgba(52,211,153,0.12)",
          fill: false,
          tension: 0.3,
          pointRadius: 2,
        },
        {
          label: "Denied",
          data: charts.hourly_activity?.denied || [],
          borderColor: "#fb7185",
          backgroundColor: "rgba(251,113,133,0.12)",
          fill: false,
          tension: 0.3,
          pointRadius: 2,
        },
      ],
    }),
    [charts]
  );

  const statusData = useMemo(
    () => ({
      labels: charts.status_breakdown?.labels || [],
      datasets: [
        {
          data: charts.status_breakdown?.values || [],
          backgroundColor: ["#34d399", "#fb7185", "#64748b"],
          borderColor: "rgba(6, 10, 18, 0.8)",
          borderWidth: 3,
        },
      ],
    }),
    [charts]
  );

  const cameraData = useMemo(
    () => ({
      labels: charts.top_cameras?.labels || [],
      datasets: [
        {
          label: "Detections (24h)",
          data: charts.top_cameras?.values || [],
          backgroundColor: "rgba(56,189,248,0.72)",
          borderRadius: 10,
          borderSkipped: false,
        },
      ],
    }),
    [charts]
  );

  const futureData = useMemo(
    () => ({
      labels: charts.future_users_actions?.labels || [],
      datasets: [
        {
          label: "Users",
          data: charts.future_users_actions?.users || [],
          borderColor: "#a78bfa",
          backgroundColor: "rgba(167,139,250,0.18)",
          fill: true,
          tension: 0.3,
          pointRadius: 2,
        },
        {
          label: "Actions",
          data: charts.future_users_actions?.actions || [],
          borderColor: "#fbbf24",
          backgroundColor: "rgba(251,191,36,0.16)",
          fill: true,
          tension: 0.3,
          pointRadius: 2,
        },
      ],
    }),
    [charts]
  );

  if (loading && !data) return <LoadingState rows={4} message="Loading dashboard intelligence..." />;
  if (error && !data) return <ErrorState error={error} onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Overview"
        title="Command dashboard"
        description="Track live detections, stream health, operator load, and training progress from one control surface."
      />

      <StaleBanner error={error} onRetry={refetch} />

      <SectionToolbar>
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge tone={training.status || "idle"}>{training.status || "idle"}</StatusBadge>
          <p className="text-sm text-muted-foreground">{training.message || "No training job is running."}</p>
        </div>
        <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
          Last update {lastUpdated ? lastUpdated.toLocaleTimeString() : "--"}
        </p>
      </SectionToolbar>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => {
          const value = card.futureKey ? getNestedValue(future as Record<string, any>, card.futureKey) : totals[card.key];
          return <StatCard key={card.key} label={card.label} value={value ?? 0} icon={card.icon} />;
        })}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <MetricChartCard
          title="Detection activity"
          meta={<span>{details.recent_24h_total || 0} events in the last 24 hours</span>}
        >
          <Line data={lineData} options={chartOptions(true)} />
        </MetricChartCard>

        <MetricChartCard
          title="Status distribution"
          meta={<span>allow {details.allowed_rate_24h ?? 0}% / deny {details.denied_rate_24h ?? 0}%</span>}
        >
          <Doughnut data={statusData} options={{ ...chartOptions(true), scales: undefined }} />
        </MetricChartCard>

        <MetricChartCard title="Top cameras" meta={<span>24h ranking</span>}>
          <Bar data={cameraData} options={chartOptions(false)} />
        </MetricChartCard>

        <MetricChartCard title="Future operations" meta={<span>Upcoming staffing and action signal</span>}>
          <Line data={futureData} options={chartOptions(true)} />
        </MetricChartCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.4fr_0.6fr]">
        <SurfaceCard className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-foreground">Recent events</h3>
            <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Latest detections</p>
          </div>

          <div className="space-y-3">
            {events.length ? (
              events.map((event: any) => (
                <div key={event.id || `${event.camera_name}-${event.detected_at}`} className="rounded-[var(--radius-md)] border border-border/70 bg-white/5 p-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <StatusBadge tone={event.status || "idle"}>{event.status || "unknown"}</StatusBadge>
                    <p className="font-mono text-sm font-semibold text-foreground">{event.plate_text || "Unknown plate"}</p>
                    <p className="text-sm text-muted-foreground">{event.camera_name || "Unknown camera"}</p>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-4 text-sm text-muted-foreground">
                    <span>{event.location || "No location"}</span>
                    <span>{event.detected_at ? new Date(event.detected_at).toLocaleString() : "-"}</span>
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No recent events available.</p>
            )}
          </div>
        </SurfaceCard>

        <SurfaceCard className="space-y-4">
          <h3 className="text-lg font-semibold text-foreground">System notes</h3>
          <div className="space-y-3 text-sm text-muted-foreground">
            <p>Active cameras: {totals.active_cameras ?? 0}</p>
            <p>Unread notifications: {totals.unread_notifications ?? 0}</p>
            <p>Allowed plates: {totals.allowed ?? 0}</p>
            <p>Denied plates: {totals.denied ?? 0}</p>
          </div>
        </SurfaceCard>
      </div>
    </div>
  );
}
