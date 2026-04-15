/**
 * Textarea — styled multiline input.
 *
 * Props:
 *   error  — truthy = red border
 *   rows   — default 3
 *   All native <textarea> props forwarded.
 */
export default function Textarea({ error, rows = 3, className = '', ...props }) {
  return (
    <textarea
      rows={rows}
      className={`ds-textarea ${error ? 'ds-textarea--error' : ''} ${className}`}
      {...props}
    />
  );
}
