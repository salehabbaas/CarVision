/**
 * FormField — label + control + optional hint/error wrapper.
 *
 * Usage:
 *   <FormField label="Username" error={errors.username} hint="Must be unique">
 *     <Input ... />
 *   </FormField>
 */
export default function FormField({ label, hint, error, required, children, className = '' }) {
  return (
    <div className={`ds-field ${error ? 'ds-field--error' : ''} ${className}`}>
      {label && (
        <label className="ds-field__label">
          {label}
          {required && <span className="ds-field__required" aria-hidden>*</span>}
        </label>
      )}
      <div className="ds-field__control">{children}</div>
      {error  && <p className="ds-field__msg ds-field__msg--error">{error}</p>}
      {!error && hint && <p className="ds-field__msg ds-field__msg--hint">{hint}</p>}
    </div>
  );
}
