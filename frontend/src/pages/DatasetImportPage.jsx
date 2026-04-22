import { useState } from 'react';
import { Archive, FileImage, UploadCloud } from 'lucide-react';
import { apiPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import FileDropZone from '../design-system/components/FileDropZone';
import Checkbox     from '../design-system/components/Checkbox';
import Button       from '../design-system/components/Button';
import Alert        from '../design-system/components/Alert';
import FormSection  from '../design-system/components/FormSection';
import FormModal    from '../design-system/components/FormModal';

export default function DatasetImportPage() {
  const { token }    = useAuth();
  const navigate     = useNavigate();
  const [images, setImages]               = useState([]);
  const [zipFile, setZipFile]             = useState(null);
  const [hasAnnotations, setHasAnnotations] = useState(false);
  const [loading, setLoading]             = useState(false);
  const [error, setError]                 = useState('');
  const [result, setResult]               = useState(null);
  const [formOpen, setFormOpen]           = useState(false);

  async function submitImport(e) {
    e.preventDefault();
    setError('');
    setResult(null);

    if (!images.length && !zipFile) {
      setError('Select images and/or a ZIP file first.');
      return;
    }

    const fd = new FormData();
    images.forEach((f) => fd.append('files', f));
    if (zipFile) fd.append('dataset_zip', zipFile);
    fd.append('has_annotations', String(Boolean(hasAnnotations)));
    fd.append('annotations_format', 'yolo');

    setLoading(true);
    try {
      const res = await fetch(apiPath('/api/v1/training/import'), {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const raw  = await res.text();
      let data   = {};
      try { data = raw ? JSON.parse(raw) : {}; } catch { data = {}; }
      if (!res.ok) {
        throw new Error(`Import failed (${res.status}): ${String(data?.detail || data?.error || raw).slice(0, 300)}`);
      }
      setResult(data);
      setFormOpen(false);
      if (data?.batch_id) navigate(`/training-data?batch=${encodeURIComponent(data.batch_id)}`);
    } catch (err) {
      setError(err.message || 'Import failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      {error  && <Alert variant="error"   onDismiss={() => setError('')}>{error}</Alert>}
      {result && (
        <Alert variant="success">
          Imported {result.created || 0} images — annotated: {result.annotated || 0},
          negatives: {result.negatives || 0}, pending: {result.pending || 0}.
        </Alert>
      )}

      <div className="panel glass" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <h3 style={{ margin: '0 0 4px' }}>Dataset Import</h3>
          <span className="muted tiny">Import images or a ZIP dataset for training.</span>
        </div>
        <Button type="button" variant="primary" icon={<UploadCloud size={14} />} onClick={() => setFormOpen(true)}>
          New Dataset Import
        </Button>
      </div>

      <FormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title="Dataset Import"
        subtitle="Import images or a ZIP dataset for training"
        formId="dataset-import-form"
        submitLabel="Import Dataset"
        submitDisabled={!images.length && !zipFile}
        submitLoading={loading}
      >
        <form
          id="dataset-import-form"
          onSubmit={submitImport}
          style={{ display: 'flex', flexDirection: 'column', gap: 20 }}
        >
          <FormSection title="Files">
            <div className="ds-grid-2">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.02em' }}>
                  Images
                </span>
                <FileDropZone
                  accept="image/*"
                  multiple
                  value={images}
                  onChange={setImages}
                  icon={<FileImage size={22} />}
                  label="Drop images here or click to browse"
                  hint="Select multiple JPEG / PNG files"
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.02em' }}>
                  ZIP Archive
                </span>
                <FileDropZone
                  accept=".zip,application/zip,application/x-zip-compressed"
                  value={zipFile}
                  onChange={setZipFile}
                  icon={<Archive size={22} />}
                  label="Drop ZIP here or click to browse"
                  hint="Can include images + YOLO label files"
                />
              </div>
            </div>
          </FormSection>

          <FormSection title="Options">
            <Checkbox
              checked={hasAnnotations}
              onChange={(e) => setHasAnnotations(e.target.checked)}
              label="Dataset already has YOLO annotations"
              hint="Enable if your ZIP or image folder includes .txt label files"
            />
          </FormSection>
        </form>
      </FormModal>
    </div>
  );
}
