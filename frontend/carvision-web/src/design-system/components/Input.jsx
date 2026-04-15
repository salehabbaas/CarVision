/**
 * Input — styled text / number / password / email input.
 *
 * Props:
 *   icon        — React node rendered on the left side
 *   suffix      — React node rendered on the right side
 *   error       — truthy = red border
 *   size        — 'sm' | 'md' (default) | 'lg'
 *   All native <input> props forwarded.
 */
export default function Input({ icon, suffix, error, size = 'md', className = '', ...props }) {
  if (!icon && !suffix) {
    return (
      <input
        className={`ds-input ds-input--${size} ${error ? 'ds-input--error' : ''} ${className}`}
        {...props}
      />
    );
  }

  return (
    <div className={`ds-input-wrap ds-input-wrap--${size} ${error ? 'ds-input-wrap--error' : ''}`}>
      {icon  && <span className="ds-input-wrap__icon">{icon}</span>}
      <input className={`ds-input ds-input--bare ${className}`} {...props} />
      {suffix && <span className="ds-input-wrap__suffix">{suffix}</span>}
    </div>
  );
}
