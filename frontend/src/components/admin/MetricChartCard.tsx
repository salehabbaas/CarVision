import type { ReactNode } from "react";

import SurfaceCard from "@/components/admin/SurfaceCard";

interface MetricChartCardProps {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
}

export default function MetricChartCard({ title, meta, children }: MetricChartCardProps) {
  return (
    <SurfaceCard className="flex h-full flex-col gap-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h3 className="text-lg font-semibold text-foreground">{title}</h3>
        </div>
        {meta ? <div className="text-xs text-muted-foreground">{meta}</div> : null}
      </div>
      <div className="min-h-[280px] flex-1">{children}</div>
    </SurfaceCard>
  );
}
