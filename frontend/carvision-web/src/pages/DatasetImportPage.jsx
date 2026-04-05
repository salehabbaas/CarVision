import { useState } from 'react';
import { Archive, FileImage, UploadCloud } from 'lucide-react';
import { apiPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';

export default function DatasetImportPage() {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [images, setImages] = useState([]);
  const [zipFile, setZipFile] = useState(null);
  const [hasAnnotations, setHasAnnotations] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  async function submitImport(e) {
    e.preventDefault();
    setError('');
    setResult(null);

    if (!images.length && !zipFile) {
      setError('Select images and/or one ZIP file first.');
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
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.detail || 'Dataset import failed');
      setResult(data);
      if (data?.batch_id) {
        navigate(`/training-data?batch=${encodeURIComponent(data.batch_id)}`);
      }
    } catch (err) {
      setError(err.message || 'Import failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}
      {result ? (
        <div className="alert success">
          Imported {result.created || 0} images. Annotated: {result.annotated || 0}, negatives: {result.negatives || 0}, pending: {result.pending || 0}.
        </div>
      ) : null}

      <form className="panel glass stack" onSubmit={submitImport}>
        <div className="panel-head">
          <h3>Dataset Import</h3>
          <span className="muted tiny">Import many images or a ZIP dataset</span>
        </div>

        <div className="row two">
          <label className="panel glass" style={{ cursor: 'pointer' }}>
            <div className="row"><FileImage size={16} /> Upload Images</div>
            <div className="tiny muted">Select multiple images</div>
            <input
              type="file"
              accept="image/*"
              multiple
              hidden
              onChange={(e) => setImages(Array.from(e.target.files || []))}
            />
            <div className="tiny">{images.length ? `${images.length} selected` : 'None selected'}</div>
          </label>

          <label className="panel glass" style={{ cursor: 'pointer' }}>
            <div className="row"><Archive size={16} /> Upload ZIP</div>
            <div className="tiny muted">Supports images + YOLO txt labels</div>
            <input
              type="file"
              accept=".zip,application/zip,application/x-zip-compressed"
              hidden
              onChange={(e) => setZipFile(e.target.files?.[0] || null)}
            />
            <div className="tiny">{zipFile ? zipFile.name : 'None selected'}</div>
          </label>
        </div>

        <label className="row tiny">
          <input
            type="checkbox"
            checked={hasAnnotations}
            onChange={(e) => setHasAnnotations(e.target.checked)}
          />
          This dataset already has YOLO annotations
        </label>

        <div className="row end">
          <button className="btn primary" type="submit" disabled={loading}>
            <UploadCloud size={15} /> {loading ? 'Importing...' : 'Import Dataset'}
          </button>
        </div>
      </form>
    </div>
  );
}
