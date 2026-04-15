/**
 * Checkbox — styled checkbox with inline label.
 *
 * Props:
 *   label    — text shown beside the checkbox
 *   hint     — small muted text shown below
 *   All native <input type="checkbox"> props forwarded.
 */
export default function Checkbox({ label, hint, className = '', ...props }) {
  return (
    <label className={`ds-checkbox ${className}`}>
      <span className="ds-checkbox__box">
        <input type="checkbox" className="ds-checkbox__input" {...props} />
        <span className="ds-checkbox__tick" aria-hidden />
      </span>
      {(label || hint) && (
        <span className="ds-checkbox__text">
          {label && <span className="ds-checkbox__label">{label}</span>}
          {hint  && <span className="ds-checkbox__hint">{hint}</span>}
        </span>
      )}
    </label>
  );
}
