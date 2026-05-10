import { useEffect, useRef, useState } from "react";
import { Archive, Download } from "lucide-react";

import SurfaceCard from "@/components/admin/SurfaceCard";
import Button from "@/design-system/components/Button";
import { apiPath, request } from "@/lib/api";
import type { ExportStatus, ImportStatus } from "@/types/api";
import ProgressBar from "./ProgressBar";

export default function BackupPanel({ token }: { token?: string }) {
  const [includeDetections, setIncludeDetections] = useState(false);
  const [exportStatus, setExportStatus] = useState<ExportStatus>({ phase: "idle", percent: 0 });
  const exportPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [importStatus, setImportStatus] = useState<ImportStatus>({ phase: "idle", percent: 0 });
  const [importFile, setImportFile] = useState<File | null>(null);
  const importPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopExportPolling = () => { if (exportPollRef.current) { clearInterval(exportPollRef.current); exportPollRef.current = null; } };
  const stopImportPolling = () => { if (importPollRef.current) { clearInterval(importPollRef.current); importPollRef.current = null; } };

  function startExportPolling() {
    stopExportPolling();
    exportPollRef.current = setInterval(async () => {
      try {
        const status = await request<ExportStatus>("/api/v1/exports/export/status", { token });
        if (status.phase === "ready" || status.phase === "error" || status.phase === "done" || status.phase === "idle") {
          stopExportPolling();
        }
        setExportStatus(status);
      } catch { /* ignore transient poll failures */ }
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
      } catch { /* server unreachable at mount; leave defaults */ }
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
  const exportReady = exportStatus.phase === "ready";
  const exportDling = exportStatus.phase === "downloading";
  const exportDone = exportStatus.phase === "done";
  const exportError = exportStatus.phase === "error";
  const exportActive = exportBuilding || exportDling;
  const activeImport = ["uploading", "validating", "importing"].includes(importStatus.phase);
  const importDone = importStatus.phase === "done";
  const importError = importStatus.phase === "error";

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

          {exportDone && (
            <Button type="button" variant="outline" onClick={() => void handleDownload()}>
              <Download className="size-4" />
              Download again
            </Button>
          )}

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
