import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface FormFieldProps {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  children: ReactNode;
  className?: string;
}

export default function FormField({ label, hint, error, required, children, className = "" }: FormFieldProps) {
  return (
    <div className={cn("space-y-2", className)}>
      {label ? (
        <label className="flex items-center gap-1 text-sm font-medium text-foreground">
          <span>{label}</span>
          {required ? <span className="text-destructive">*</span> : null}
        </label>
      ) : null}
      {children}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
      {!error && hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
