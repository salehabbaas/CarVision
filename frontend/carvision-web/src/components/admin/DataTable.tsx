import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface DataTableProps {
  headers: ReactNode[];
  children: ReactNode;
  className?: string;
}

export default function DataTable({ headers, children, className }: DataTableProps) {
  return (
    <div className={cn("overflow-hidden rounded-[var(--radius-lg)] border border-border/80 bg-card/75 shadow-card", className)}>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border/70 text-sm">
          <thead className="bg-white/5">
            <tr>
              {headers.map((header, index) => (
                <th key={index} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">{children}</tbody>
        </table>
      </div>
    </div>
  );
}
