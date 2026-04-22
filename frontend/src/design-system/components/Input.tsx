import * as React from "react";

import { cn } from "@/lib/utils";

interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size"> {
  icon?: React.ReactNode;
  suffix?: React.ReactNode;
  error?: boolean;
  size?: "sm" | "md" | "lg";
}

const sizeMap = {
  sm: "h-9 text-sm",
  md: "h-11 text-sm",
  lg: "h-12 text-base",
} as const;

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, icon, suffix, error, size = "md", ...props }, ref) => {
    if (!icon && !suffix) {
      return (
        <input
          ref={ref}
          className={cn(
            "flex w-full rounded-[var(--radius-md)] border bg-white/5 px-4 py-2 text-foreground shadow-inner transition placeholder:text-muted-foreground/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            sizeMap[size],
            error ? "border-destructive/60 focus-visible:ring-destructive/50" : "border-border",
            className
          )}
          {...props}
        />
      );
    }

    return (
      <div
        className={cn(
          "flex w-full items-center gap-2 rounded-[var(--radius-md)] border bg-white/5 px-3 shadow-inner transition focus-within:ring-2 focus-within:ring-ring",
          sizeMap[size],
          error ? "border-destructive/60 focus-within:ring-destructive/50" : "border-border",
          className
        )}
      >
        {icon ? <span className="text-muted-foreground">{icon}</span> : null}
        <input
          ref={ref}
          className="h-full w-full bg-transparent text-foreground outline-none placeholder:text-muted-foreground/70"
          {...props}
        />
        {suffix ? <span className="text-muted-foreground">{suffix}</span> : null}
      </div>
    );
  }
);

Input.displayName = "Input";

export default Input;
