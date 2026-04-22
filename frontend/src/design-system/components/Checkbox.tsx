import * as React from "react";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

interface CheckboxProps {
  checked?: boolean;
  onChange?: (event: { target: { checked: boolean } }) => void;
  onCheckedChange?: (checked: boolean) => void;
  label?: React.ReactNode;
  hint?: React.ReactNode;
  className?: string;
  disabled?: boolean;
}

export default function Checkbox({
  checked,
  onChange,
  onCheckedChange,
  label,
  hint,
  className,
  disabled,
}: CheckboxProps) {
  return (
    <label className={cn("flex items-start gap-3", disabled && "opacity-60", className)}>
      <CheckboxPrimitive.Root
        checked={checked}
        disabled={disabled}
        onCheckedChange={(next) => {
          const value = Boolean(next);
          onCheckedChange?.(value);
          onChange?.({ target: { checked: value } });
        }}
        className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border border-border bg-white/5 text-primary transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=checked]:border-primary/60 data-[state=checked]:bg-primary/15"
      >
        <CheckboxPrimitive.Indicator>
          <Check className="size-4" />
        </CheckboxPrimitive.Indicator>
      </CheckboxPrimitive.Root>
      {(label || hint) ? (
        <span className="space-y-1">
          {label ? <span className="block text-sm font-medium text-foreground">{label}</span> : null}
          {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
        </span>
      ) : null}
    </label>
  );
}
