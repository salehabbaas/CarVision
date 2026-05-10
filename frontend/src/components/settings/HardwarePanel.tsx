import { Cpu, Zap } from "lucide-react";
import SurfaceCard from "@/components/admin/SurfaceCard";
import type { HardwareInfo } from "@/types/api";

export default function HardwarePanel({ hw }: { hw: HardwareInfo }) {
  const badges = [
    { label: "CPU", active: hw.cpu },
    { label: "CUDA", active: hw.cuda },
    { label: "MPS", active: hw.mps },
    { label: "PyTorch", active: hw.pytorch_available },
  ];

  return (
    <SurfaceCard>
      <div className="flex items-center gap-3 mb-4">
        <div className="rounded-xl border border-primary/20 bg-primary/10 p-2.5 text-primary">
          <Cpu className="size-4" />
        </div>
        <div>
          <p className="text-sm font-semibold text-foreground">Hardware probe</p>
          <p className="text-xs text-muted-foreground">Detected compute capabilities</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        {badges.map((b) => (
          <span
            key={b.label}
            className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${
              b.active
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "border-border/60 bg-muted/40 text-muted-foreground"
            }`}
          >
            {b.label} {b.active ? "✓" : "—"}
          </span>
        ))}
      </div>

      {hw.gpu_names.length > 0 && (
        <div className="mb-4">
          <p className="text-xs font-medium text-muted-foreground mb-1">GPU(s)</p>
          <ul className="space-y-0.5">
            {hw.gpu_names.map((name, i) => (
              <li key={i} className="flex items-center gap-2 text-xs text-foreground">
                <Zap className="size-3 text-yellow-500" />
                {name}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <p className="text-xs font-medium text-muted-foreground mb-1">Available model backends</p>
        <div className="flex flex-wrap gap-1.5">
          {hw.usable_backends.map((b) => (
            <span
              key={b}
              className="rounded border border-border/60 bg-card px-2 py-0.5 font-mono text-xs text-foreground"
            >
              {b}
            </span>
          ))}
        </div>
      </div>
    </SurfaceCard>
  );
}
