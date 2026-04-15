import { LoaderCircle } from 'lucide-react';

/**
 * Button — primary / ghost / danger / outlined variants.
 *
 * Props:
 *   variant  — 'primary' | 'ghost' | 'danger' | 'outline' (default: 'ghost')
 *   size     — 'sm' | 'md' (default) | 'lg'
 *   loading  — shows spinner and disables the button
 *   icon     — React node placed before the label
 *   All native <button> props forwarded.
 */
export default function Button({
  variant = 'ghost',
  size = 'md',
  loading = false,
  icon,
  children,
  className = '',
  disabled,
  ...props
}) {
  return (
    <button
      className={`ds-btn ds-btn--${variant} ds-btn--${size} ${loading ? 'ds-btn--loading' : ''} ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <LoaderCircle size={14} className="ds-btn__spinner" />
      ) : (
        icon && <span className="ds-btn__icon">{icon}</span>
      )}
      {children && <span>{children}</span>}
    </button>
  );
}
