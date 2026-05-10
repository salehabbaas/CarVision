import { useEffect, useRef, useState } from "react";
import { Archive, Cpu, Download, HardDrive, Save, Settings2, Zap } from "lucide-react";

import { ErrorState, LoadingState } from "@/components/PageState";
import PageHeader from "@/components/admin/PageHeader";
import SurfaceCard from "@/components/admin/SurfaceCard";
import { useAuth } from "@/context/AuthContext";
import Button from "@/design-system/components/Button";
import FormField from "@/design-system/components/FormField";
import Select from "@/design-system/components/Select";
import { apiPath, request } from "@/lib/api";
import type { ExportStatus, HardwareInfo, ImportStatus, RuntimeSettings } from "@/types/api";

interface Option { value: string; label: string }

function Opts({ options }: { options: Option[] }) {
  return <>{options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</>;
}

const PROFILE_OPTIONS: Option[] = [
  { value: "cpu", label: "CPU (safe default)" },
  { value: "nvidia", label: "NVIDIA GPU" },
  { value: "mac", label: "Mac (Apple Silicon)" },
];

const DEVICE_OPTIONS: Option[] = [
  { value: "cpu", label: "CPU" },
  { value: "cuda", label: "CUDA (NVIDIA)" },
  { value: "mps", label: "MPS (Apple)" },
  { value: "auto", label: "Auto-detect" },
];

const OCR_OPTIONS: Option[] = [
  { value: "easyocr", label: "EasyOCR" },
  { value: "paddleocr", label: "PaddleOCR" },
  { value: "tesseract", label: "Tesseract" },
];

const PLATE_REGION_OPTIONS: Option[] = [
  { value: "generic", label: "Generic" },
  { value: "palestine", label: "Palestine" },
  { value: "israel", label: "Israel" },
  { value: "palestine_israel", label: "Palestine / Israel" },
];

function HardwarePanel({ hw }: { hw: HardwareInfo }) {
  const badges = [
    { label: "CPU", active: hw.cpu },
    { label: "CUDA", active: hw.cuda },
    { label: "MPS", active: hw.mps },
    { label: "PyTorch", active: hw.pytorch_available },
  ];

  return (
    <SurfaceCard>
      <div className="flex items-center gap-3 mb-4">
        <div className="rounded-xl border border-primary/20 bg-primary/10 p-2.5 text-primary">
          <Cpu className="size-4" />
        </div>
        <div>
          <p className="text-sm font-semibold text-foreground">Hardware probe</p>
          <p className="text-xs text-muted-foreground">Detected compute capabilities</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        {badges.map((b) => (
          <span
            key={b.label}
            className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${
              b.active
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "border-border/60 bg-muted/40 text-muted-foreground"
            }`}
          >
            {b.label} {b.active ? "✓" : "—"}
          </span>
        ))}
      </div>

      {hw.gpu_names.length > 0 && (
        <div className="mb-4">
          <p className="text-xs font-medium text-muted-foreground mb-1">GPU(s)</p>
          <ul className="space-y-0.5">
            {hw.gpu_names.map((name, i) => (
              <li key={i} className="flex items-center gap-2 text-xs text-foreground">
                <Zap className="size-3 text-yellow-500" />
                {name}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <p className="text-xs font-medium text-muted-foreground mb-1">Available model backends</p>
        <div className="flex flex-wrap gap-1.5">
          {hw.usable_backends.map((b) => (
            <span
              key={b}
              className="rounded border border-border/60 bg-card px-2 py-0.5 font-mono text-xs text-foreground"
            >
              {b}
            </span>
          ))}
        </div>
      </div>
    </SurfaceCard>
  );
}

function ProgressBar({
  percent,
  isError,
  isDone,
  message,
}: {
  percent: number;
  isError: boolean;
  isDone: boolean;
  message?: string;
}) {
  return (
    <div className="space-y-1.5 mt-2">
      <div className="flex items-center justify-between">
        <span
          className={`text-xs ${
            isError
              ? "text-destructive"
              : isDone
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-muted-foreground"
          }`}
        >
          {message}
        </span>
        <span className="text-xs tabular-nums text-muted-foreground">{percent}%</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-border/40 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            isError
              ? "bg-destructive"
              : isDone
              ? "bg-emerald-500"
              : "bg-primary"
          }`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function BackupPanel({ token }: { token?: string }) {
  const [includeDetections, setIncludeDetections] = useState(false);
  const [exportStatus, setExportStatus] = useState<ExportStatus>({ phase: "idle", percent: 0 });
  const exportPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [importStatus, setImportStatus] = useState<ImportStatus>({ phase: "idle", percent: 0 });
  const [importFile, setImportFile] = useState<File | null>(null);
  const importPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopExportPolling() {
    if (exportPollRef.current) { clearInterval(exportPollRef.current); exportPollRef.current = null; }
  }
  function stopImportPolling() {
    if (importPollRef.current) { clearInterval(importPollRef.current); importPollRef.current = null; }
  }

  function startExportPolling() {
    stopExportPolling();
    exportPollRef.current = setInterval(async () => {
      try {
        const status = await request<ExportStatus>("/api/v1/exports/export/status", { token });
        // Stop polling once the backend reaches a terminal state
        if (status.phase === "ready" || status.phase === "error" || status.phase === "done" || status.phase === "idle") {
          stopExportPolling();
        }
        setExportStatus(status);
      } catch {
        // ignore transient poll failures
      }
    }, 1000);
  }

  function startImportPolling() {
    stopImportPolling();
    importPollRef.current = setInterval(async () => {
      try {
        const status = await request<ImportStatus>("/api/v1/exports/import/status", { token });
        setImportStatus(status);
        if (status.phase === "done" || status.phase === "error") {
          stopImportPolling();
        }
      } catch {
        // ignore transient poll failures
      }
    }, 1500);
  }

  // On mount: sync with server-side state so page refresh doesn't lose progress
  useEffect(() => {
    if (!token) return;
    void (async () => {
      try {
        const [expSt, impSt] = await Promise.all([
          request<ExportStatus>("/api/v1/exports/export/status", { token }),
          request<ImportStatus>("/api/v1/exports/import/status", { token }),
        ]);
        if (expSt.phase !== "idle") {
          setExportStatus(expSt);
          if (expSt.phase === "building") startExportPolling();
        }
        if (impSt.phase !== "idle") {
          setImportStatus(impSt);
          if (["uploading", "validating", "importing"].includes(impSt.phase)) startImportPolling();
        }
      } catch {
        // server unreachable at mount; leave defaults
      }
    })();
    return () => { stopExportPolling(); stopImportPolling(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function handleExport() {
    stopExportPolling();
    setExportStatus({ phase: "building", percent: 0, message: "Starting export…" });
    try {
      const res = await fetch(
        apiPath(`/api/v1/exports/export/start?include_detection_images=${includeDetections}`),
        { method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {} }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(body.detail ?? "Export failed to start");
      }
      startExportPolling();
    } catch (err) {
      setExportStatus({ phase: "error", percent: 0, message: err instanceof Error ? err.message : "Export failed" });
    }
  }

  // Called directly from a button click (user gesture) — required for reliable blob downloads
  async function handleDownload() {
    setExportStatus((s) => ({ ...s, phase: "downloading", message: "Downloading…" }));
    try {
      const res = await fetch(apiPath("/api/v1/exports/download"), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(body.detail ?? `Download failed: ${res.status}`);
      }
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const disposition = res.headers.get("content-disposition") ?? "";
      const match = disposition.match(/filename="?([^"]+)"?/);
      a.download = match?.[1] ?? "carvision-backup.zip";
      a.href = objectUrl;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(objectUrl);
      setExportStatus({ phase: "done", percent: 100, message: "Backup downloaded successfully." });
    } catch (err) {
      setExportStatus({ phase: "error", percent: 0, message: err instanceof Error ? err.message : "Download failed" });
    }
  }

  async function handleImport() {
    if (!importFile) return;
    stopImportPolling();
    setImportStatus({ phase: "uploading", percent: 5, message: "Uploading…" });
    const form = new FormData();
    form.append("file", importFile);
    try {
      const res = await fetch(apiPath("/api/v1/exports/import"), {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail ?? "Import request failed");
      }
      startImportPolling();
    } catch (err) {
      setImportStatus({ phase: "error", percent: 0, error: err instanceof Error ? err.message : "Import failed" });
    }
  }

  const exportBuilding = exportStatus.phase === "building";
  const exportReady    = exportStatus.phase === "ready";
  const exportDling    = exportStatus.phase === "downloading";
  const exportDone     = exportStatus.phase === "done";
  const exportError    = exportStatus.phase === "error";
  const exportActive   = exportBuilding || exportDling;

  const activeImport = ["uploading", "validating", "importing"].includes(importStatus.phase);
  const importDone   = importStatus.phase === "done";
  const importError  = importStatus.phase === "error";

  return (
    <SurfaceCard>
      <div className="flex items-center gap-3 mb-5">
        <div className="rounded-xl border border-primary/20 bg-primary/10 p-2.5 text-primary">
          <Archive className="size-4" />
        </div>
        <div>
          <p className="text-sm font-semibold text-foreground">Backup &amp; Restore</p>
          <p className="text-xs text-muted-foreground">
            Export all data, annotations, settings and trained model as a ZIP. Restore on any CarVision instance.
          </p>
        </div>
      </div>

      {/* Export */}
      <div className="space-y-3">
        <p className="text-xs font-medium text-foreground">Export</p>
        <div className="flex items-center gap-2">
          <input
            id="include_detections"
            type="checkbox"
            checked={includeDetections}
            disabled={exportActive}
            onChange={(e) => setIncludeDetections(e.target.checked)}
            className="size-4 rounded border-border accent-primary disabled:opacity-50"
          />
          <label htmlFor="include_detections" className="text-sm text-foreground cursor-pointer">
            Include detection snapshot images{" "}
            <span className="text-muted-foreground">(increases export size)</span>
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          {/* Primary action: build when idle/error/done, download when ready */}
          {exportReady ? (
            <Button type="button" onClick={() => void handleDownload()}>
              <Download className="size-4" />
              Download backup ZIP
            </Button>
          ) : (
            <Button type="button" disabled={exportActive} onClick={() => void handleExport()}>
              <Archive className="size-4" />
              {exportBuilding ? "Preparing…" : exportDling ? "Downloading…" : "Build backup ZIP"}
            </Button>
          )}

          {/* Secondary: re-download if already downloaded once (file still cached on server) */}
          {exportDone && (
            <Button type="button" variant="outline" onClick={() => void handleDownload()}>
              <Download className="size-4" />
              Download again
            </Button>
          )}

          {/* Reset to start a fresh export */}
          {(exportDone || exportError) && (
            <Button
              type="button"
              variant="ghost"
              onClick={() => setExportStatus({ phase: "idle", percent: 0 })}
            >
              New export
            </Button>
          )}
        </div>

        {exportStatus.phase !== "idle" && (
          <ProgressBar
            percent={exportStatus.percent}
            isError={exportError}
            isDone={exportDone}
            message={exportStatus.message}
          />
        )}
      </div>

      <hr className="border-border/40 my-5" />

      {/* Import */}
      <div className="space-y-3">
        <p className="text-xs font-medium text-foreground">Restore</p>
        <p className="text-xs text-amber-600 dark:text-amber-400">
          Restoring will replace all data except user credentials. This cannot be undone.
        </p>
        <input
          type="file"
          accept=".zip"
          disabled={activeImport}
          onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm text-muted-foreground file:mr-3 file:rounded-lg file:border file:border-border file:bg-muted file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-foreground hover:file:bg-muted/80 disabled:opacity-50"
        />
        <Button
          type="button"
          disabled={!importFile || activeImport}
          onClick={() => void handleImport()}
        >
          {activeImport ? "Restoring…" : "Restore from ZIP"}
        </Button>

        {importStatus.phase !== "idle" && (
          <ProgressBar
            percent={importStatus.percent}
            isError={importError}
            isDone={importDone}
            message={importError ? (importStatus.error ?? "Import failed") : importStatus.message}
          />
        )}
      </div>
    </SurfaceCard>
  );
}

export default function SettingsPage() {
  const { token } = useAuth();
  const [hw, setHw] = useState<HardwareInfo | null>(null);
  const [form, setForm] = useState<RuntimeSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    const [hwData, rtData] = await Promise.all([
      request<HardwareInfo>("/api/v1/settings/hardware", { token }),
      request<RuntimeSettings>("/api/v1/settings/runtime", { token }),
    ]);
    setHw(hwData);
    setForm(rtData);
  }

  useEffect(() => {
    void load()
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load settings"))
      .finally(() => setLoading(false));
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    setSaved(false);
    try {
      const updated = await request<RuntimeSettings>("/api/v1/settings/runtime", {
        token,
        method: "PUT",
        body: form,
      });
      setForm(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  function patch(key: keyof RuntimeSettings, value: unknown) {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  if (loading) return <LoadingState rows={4} message="Loading settings..." />;
  if (error && !form) {
    return (
      <ErrorState
        error={{ message: error, type: "unknown" }}
        onRetry={() => {
          setLoading(true);
          void load()
            .catch((err) => setError(err instanceof Error ? err.message : "Failed to load settings"))
            .finally(() => setLoading(false));
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Configuration"
        title="Runtime settings"
        description="Configure hardware profile, inference device, detection throughput, and OCR engine."
      />

      {hw && <HardwarePanel hw={hw} />}

      {form && (
        <form onSubmit={handleSave} className="space-y-4">
          <SurfaceCard>
            <div className="flex items-center gap-3 mb-5">
              <div className="rounded-xl border border-primary/20 bg-primary/10 p-2.5 text-primary">
                <Settings2 className="size-4" />
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground">Runtime profile</p>
                <p className="text-xs text-muted-foreground">Hardware deployment target</p>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <FormField label="Profile">
                <Select value={form.runtime_profile} onChange={(e) => patch("runtime_profile", e.target.value)}>
                  <Opts options={PROFILE_OPTIONS} />
                </Select>
              </FormField>
              <FormField label="Inference device">
                <Select value={form.inference_device} onChange={(e) => patch("inference_device", e.target.value)}>
                  <Opts options={DEVICE_OPTIONS} />
                </Select>
              </FormField>
              <FormField label="Training device">
                <Select value={form.training_device} onChange={(e) => patch("training_device", e.target.value)}>
                  <Opts options={DEVICE_OPTIONS} />
                </Select>
              </FormField>
              <FormField label="Model backend">
                <Select value={form.model_backend} onChange={(e) => patch("model_backend", e.target.value)}>
                  {(hw?.usable_backends ?? ["pytorch"]).map((b) => (
                    <option key={b} value={b}>{b.charAt(0).toUpperCase() + b.slice(1)}</option>
                  ))}
                </Select>
              </FormField>
            </div>
          </SurfaceCard>

          <SurfaceCard>
            <div className="flex items-center gap-3 mb-5">
              <div className="rounded-xl border border-primary/20 bg-primary/10 p-2.5 text-primary">
                <HardDrive className="size-4" />
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground">Detection & streaming</p>
                <p className="text-xs text-muted-foreground">Throughput and quality knobs</p>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <FormField label="Target detection FPS">
                <input
                  type="number"
                  min={0.5}
                  max={30}
                  step={0.5}
                  value={form.target_detection_fps}
                  onChange={(e) => patch("target_detection_fps", parseFloat(e.target.value))}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
                />
              </FormField>
              <FormField label="Max live cameras">
                <input
                  type="number"
                  min={1}
                  max={64}
                  value={form.max_live_cameras}
                  onChange={(e) => patch("max_live_cameras", parseInt(e.target.value))}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
                />
              </FormField>
              <FormField label="JPEG quality">
                <input
                  type="number"
                  min={10}
                  max={100}
                  value={form.jpeg_quality}
                  onChange={(e) => patch("jpeg_quality", parseInt(e.target.value))}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
                />
              </FormField>
            </div>

            <div className="mt-4 flex items-center gap-3">
              <input
                id="batch_inference"
                type="checkbox"
                checked={form.batch_inference}
                onChange={(e) => patch("batch_inference", e.target.checked)}
                className="size-4 rounded border-border accent-primary"
              />
              <label htmlFor="batch_inference" className="text-sm text-foreground cursor-pointer">
                Batch inference (group frames for GPU efficiency)
              </label>
            </div>
          </SurfaceCard>

          <SurfaceCard>
            <div className="flex items-center gap-3 mb-5">
              <div className="rounded-xl border border-primary/20 bg-primary/10 p-2.5 text-primary">
                <Zap className="size-4" />
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground">OCR & plate recognition</p>
                <p className="text-xs text-muted-foreground">Engine and regional format rules</p>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <FormField label="OCR engine">
                <Select value={form.ocr_engine} onChange={(e) => patch("ocr_engine", e.target.value)}>
                  <Opts options={OCR_OPTIONS} />
                </Select>
              </FormField>
              <FormField label="Plate region">
                <Select value={form.plate_region} onChange={(e) => patch("plate_region", e.target.value)}>
                  <Opts options={PLATE_REGION_OPTIONS} />
                </Select>
              </FormField>
            </div>
          </SurfaceCard>

          <div className="flex items-center gap-3">
            <Button type="submit" disabled={saving}>
              <Save className="size-4" />
              {saving ? "Saving…" : "Save settings"}
            </Button>
            {saved && (
              <span className="text-sm font-medium text-emerald-600 dark:text-emerald-400">
                Settings saved.
              </span>
            )}
            {error && !saving && (
              <span className="text-sm text-destructive">{error}</span>
            )}
          </div>
        </form>
      )}

      <BackupPanel token={token ?? undefined} />
    </div>
  );
}
