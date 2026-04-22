import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface FormSectionProps {
  title?: ReactNode;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}

export default function FormSection({ title, icon, children, className = "" }: FormSectionProps) {
  return (
    <section
      className={cn(
        "rounded-[var(--radius-lg)] border border-border/80 bg-card/70 p-5 shadow-card backdrop-blur-shell",
        className
      )}
    >
      {title || icon ? (
        <div className="mb-5 flex items-center gap-3 border-b border-border/70 pb-3">
          {icon ? <span className="text-muted-foreground">{icon}</span> : null}
          {title ? <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">{title}</h3> : null}
        </div>
      ) : null}
      <div className="space-y-4">{children}</div>
    </section>
  );
}
