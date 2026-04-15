/**
 * FormSection — named section inside a form with a subtle divider.
 *
 * Usage:
 *   <FormSection title="Credentials" icon={<Lock size={14}/>}>
 *     <FormField .../>
 *   </FormSection>
 */
export default function FormSection({ title, icon, children, className = '' }) {
  return (
    <div className={`ds-form-section ${className}`}>
      {(title || icon) && (
        <div className="ds-form-section__header">
          {icon  && <span className="ds-form-section__icon">{icon}</span>}
          {title && <span className="ds-form-section__title">{title}</span>}
          <span className="ds-form-section__rule" aria-hidden />
        </div>
      )}
      <div className="ds-form-section__body">{children}</div>
    </div>
  );
}
