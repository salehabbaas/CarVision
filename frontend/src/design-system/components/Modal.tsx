import type { ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

interface ModalProps {
  open: boolean;
  onClose?: () => void;
  title?: ReactNode;
  subtitle?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  children: ReactNode;
}

const sizeClass = {
  sm: "max-w-md",
  md: "max-w-2xl",
  lg: "max-w-4xl",
  xl: "max-w-6xl",
} as const;

export default function Modal({ open, onClose, title, subtitle, footer, size = "md", children }: ModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose?.()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-slate-950/75 backdrop-blur-sm" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-[100] w-[min(calc(100vw-2rem),72rem)] -translate-x-1/2 -translate-y-1/2 rounded-[var(--radius-xl)] border border-border bg-card/95 p-0 text-card-foreground shadow-shell backdrop-blur-shell focus:outline-none",
            sizeClass[size]
          )}
        >
          {(title || subtitle || onClose) ? (
            <div className="flex items-start justify-between gap-4 border-b border-border/70 px-6 py-5">
              <div className="space-y-1">
                {title ? <Dialog.Title className="text-xl font-semibold text-foreground">{title}</Dialog.Title> : null}
                {subtitle ? <Dialog.Description className="text-sm text-muted-foreground">{subtitle}</Dialog.Description> : null}
              </div>
              {onClose ? (
                <Dialog.Close asChild>
                  <button
                    type="button"
                    className="rounded-full border border-border bg-white/5 p-2 text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                    aria-label="Close"
                  >
                    <X className="size-4" />
                  </button>
                </Dialog.Close>
              ) : null}
            </div>
          ) : null}
          <div className="max-h-[72vh] overflow-auto px-6 py-5">{children}</div>
          {footer ? <div className="border-t border-border/70 px-6 py-4">{footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
