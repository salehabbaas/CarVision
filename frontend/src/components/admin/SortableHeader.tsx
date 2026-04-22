import type { ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { cn } from "@/lib/utils";

export default function SortableHeader({
  label,
  sortKey,
  activeKey,
  direction,
  onSort,
  className,
}: {
  label: ReactNode;
  sortKey: string;
  activeKey: string | null;
  direction: "asc" | "desc";
  onSort: (key: string) => void;
  className?: string;
}) {
  const active = activeKey === sortKey;
  const Icon = !active ? ArrowUpDown : direction === "asc" ? ArrowUp : ArrowDown;

  return (
    <button
      type="button"
      className={cn(
        "inline-flex items-center gap-1 text-left text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground transition hover:text-foreground",
        active && "text-foreground",
        className
      )}
      onClick={() => onSort(sortKey)}
    >
      <span>{label}</span>
      <Icon className="size-3.5" />
    </button>
  );
}
