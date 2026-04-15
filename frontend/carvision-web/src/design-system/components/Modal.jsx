import { useEffect } from 'react';
import { X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

/**
 * Modal — accessible, animated dialog with header / body / footer slots.
 *
 * Props:
 *   open      — boolean
 *   onClose   — () => void
 *   title     — string | React node
 *   subtitle  — string | React node
 *   footer    — React node (action buttons)
 *   size      — 'sm' | 'md' (default) | 'lg' | 'xl'
 *   children  — modal body
 */
export default function Modal({ open, onClose, title, subtitle, footer, size = 'md', children }) {
  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // Lock body scroll
  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="ds-modal-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
        >
          <motion.div
            className={`ds-modal ds-modal--${size} glass`}
            initial={{ y: 24, opacity: 0, scale: 0.97 }}
            animate={{ y: 0, opacity: 1, scale: 1 }}
            exit={{ y: 16, opacity: 0, scale: 0.97 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            role="dialog"
            aria-modal="true"
          >
            {/* Header */}
            {(title || onClose) && (
              <div className="ds-modal__header">
                <div className="ds-modal__title-wrap">
                  {title    && <h3 className="ds-modal__title">{title}</h3>}
                  {subtitle && <p  className="ds-modal__subtitle">{subtitle}</p>}
                </div>
                {onClose && (
                  <button className="ds-modal__close" onClick={onClose} aria-label="Close">
                    <X size={16} />
                  </button>
                )}
              </div>
            )}

            {/* Body */}
            <div className="ds-modal__body">{children}</div>

            {/* Footer */}
            {footer && <div className="ds-modal__footer">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
