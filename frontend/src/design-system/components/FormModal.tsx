import type { ReactNode } from "react";

import Button from "@/design-system/components/Button";
import Modal from "@/design-system/components/Modal";

interface FormModalProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  formId?: string;
  submitLabel?: string;
  cancelLabel?: string;
  submitDisabled?: boolean;
  submitLoading?: boolean;
  onSubmitClick?: () => void;
  footerStart?: ReactNode;
  footerEnd?: ReactNode;
  children: ReactNode;
}

export default function FormModal({
  open,
  onClose,
  title,
  subtitle,
  size = "md",
  formId,
  submitLabel = "Save",
  cancelLabel = "Cancel",
  submitDisabled,
  submitLoading,
  onSubmitClick,
  footerStart,
  footerEnd,
  children,
}: FormModalProps) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      subtitle={subtitle}
      size={size}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">{footerStart}</div>
          <div className="flex flex-wrap items-center gap-2">
            {footerEnd}
            <Button variant="ghost" type="button" onClick={onClose}>
              {cancelLabel}
            </Button>
            <Button
              variant="primary"
              type={formId ? "submit" : "button"}
              form={formId}
              disabled={submitDisabled}
              loading={submitLoading}
              onClick={formId ? undefined : onSubmitClick}
            >
              {submitLabel}
            </Button>
          </div>
        </div>
      }
    >
      {children}
    </Modal>
  );
}
