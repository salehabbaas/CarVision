import { ChevronDown } from 'lucide-react';

/**
 * Select — styled dropdown.
 *
 * Props:
 *   error  — truthy = red border
 *   All native <select> props forwarded.
 */
export default function Select({ error, className = '', children, ...props }) {
  return (
    <div className={`ds-select-wrap ${error ? 'ds-select-wrap--error' : ''}`}>
      <select className={`ds-select ${className}`} {...props}>
        {children}
      </select>
      <ChevronDown size={14} className="ds-select-wrap__arrow" />
    </div>
  );
}
