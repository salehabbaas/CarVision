import { AlertCircle, CheckCircle2, AlertTriangle, Info, X } from 'lucide-react';

const ICONS = {
  error:   <AlertCircle  size={15} />,
  success: <CheckCircle2 size={15} />,
  warning: <AlertTriangle size={15} />,
  info:    <Info size={15} />,
};

/**
 * Alert — error / success / warning / info banner.
 *
 * Props:
 *   variant   — 'error' | 'success' | 'warning' | 'info'
 *   onDismiss — () => void   (shows X button when provided)
 */
export default function Alert({ variant = 'info', onDismiss, children, className = '' }) {
  return (
    <div className={`ds-alert ds-alert--${variant} ${className}`} role="alert">
      <span className="ds-alert__icon">{ICONS[variant]}</span>
      <span className="ds-alert__body">{children}</span>
      {onDismiss && (
        <button className="ds-alert__dismiss" onClick={onDismiss} aria-label="Dismiss">
          <X size={13} />
        </button>
      )}
    </div>
  );
}
