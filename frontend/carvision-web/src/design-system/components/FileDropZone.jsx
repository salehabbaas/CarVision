import { useRef, useState } from 'react';
import { UploadCloud, X } from 'lucide-react';

/**
 * FileDropZone — drag-and-drop + click-to-browse file selector.
 *
 * Props:
 *   accept    — native accept string, e.g. "image/*,video/*"
 *   multiple  — allow multiple files
 *   value     — File | File[] | null
 *   onChange  — (File | File[] | null) => void
 *   icon      — React node (default: UploadCloud)
 *   label     — primary label text
 *   hint      — secondary hint text
 *   error     — error message string
 */
export default function FileDropZone({
  accept,
  multiple = false,
  value,
  onChange,
  icon,
  label = 'Drop file here or click to browse',
  hint,
  error,
  className = '',
}) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  const files = multiple
    ? Array.isArray(value) ? value : (value ? [value] : [])
    : (value ? [value] : []);

  function handleFiles(fileList) {
    const arr = Array.from(fileList || []);
    if (!arr.length) return;
    onChange(multiple ? arr : arr[0]);
  }

  function onDrop(e) {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  }

  function clear(e) {
    e.stopPropagation();
    onChange(multiple ? [] : null);
    if (inputRef.current) inputRef.current.value = '';
  }

  return (
    <div
      className={`ds-dropzone ${dragging ? 'ds-dropzone--dragging' : ''} ${error ? 'ds-dropzone--error' : ''} ${files.length ? 'ds-dropzone--filled' : ''} ${className}`}
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        className="ds-dropzone__input"
        onChange={(e) => handleFiles(e.target.files)}
      />

      {files.length === 0 ? (
        <div className="ds-dropzone__empty">
          <span className="ds-dropzone__icon">{icon || <UploadCloud size={24} />}</span>
          <span className="ds-dropzone__label">{label}</span>
          {hint && <span className="ds-dropzone__hint">{hint}</span>}
        </div>
      ) : (
        <div className="ds-dropzone__filled">
          <span className="ds-dropzone__icon ds-dropzone__icon--ok">{icon || <UploadCloud size={20} />}</span>
          <div className="ds-dropzone__filelist">
            {files.map((f, i) => (
              <span key={i} className="ds-dropzone__filename">{f.name}</span>
            ))}
          </div>
          <button
            type="button"
            className="ds-dropzone__clear"
            onClick={clear}
            title="Remove file"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {error && <p className="ds-dropzone__error">{error}</p>}
    </div>
  );
}
