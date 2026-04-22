import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export default function SectionToolbar({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-[var(--radius-lg)] border border-border/80 bg-card/75 p-4 shadow-card backdrop-blur-shell md:flex-row md:items-center md:justify-between",
        className
      )}
      {...props}
    />
  );
}
