import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export default function SurfaceCard({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-lg)] border border-border/80 bg-card/75 p-5 shadow-card backdrop-blur-shell",
        className
      )}
      {...props}
    />
  );
}
