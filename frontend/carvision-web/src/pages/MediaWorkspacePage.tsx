import { Archive, Clapperboard, DatabaseZap, UploadCloud } from "lucide-react";
import { useSearchParams } from "react-router-dom";

import PageHeader from "@/components/admin/PageHeader";
import SurfaceCard from "@/components/admin/SurfaceCard";
import { cn } from "@/lib/utils";

import UploadPage from "./UploadPage";
import DatasetImportPage from "./DatasetImportPage";
import TrainedDataPage from "./TrainedDataPage";
import ClipsPage from "./ClipsPage";

const tabs = [
  {
    key: "upload",
    label: "Upload & Test",
    description: "Run a single image or video through the detection pipeline.",
    icon: UploadCloud,
  },
  {
    key: "dataset-import",
    label: "Dataset Import",
    description: "Bring in images or ZIP datasets for training intake.",
    icon: Archive,
  },
  {
    key: "trained-data",
    label: "Trained Data",
    description: "Manage imported batches and OCR reprocessing jobs.",
    icon: DatabaseZap,
  },
  {
    key: "clips",
    label: "Clips",
    description: "Review active recordings and saved clip exports.",
    icon: Clapperboard,
  },
] as const;

type TabKey = (typeof tabs)[number]["key"];

function Content({ tab }: { tab: TabKey }) {
  if (tab === "dataset-import") return <DatasetImportPage />;
  if (tab === "trained-data") return <TrainedDataPage />;
  if (tab === "clips") return <ClipsPage />;
  return <UploadPage />;
}

export default function MediaWorkspacePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab");
  const activeTab: TabKey = tabs.some((tab) => tab.key === rawTab) ? (rawTab as TabKey) : "upload";
  const activeMeta = tabs.find((tab) => tab.key === activeTab)!;
  const ActiveIcon = activeMeta.icon;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Media Ops"
        title="Media workspace"
        description="One place for upload testing, dataset intake, imported-batch management, and clip review."
      />

      <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
        <div className="space-y-3">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = tab.key === activeTab;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => setSearchParams({ tab: tab.key })}
                className={cn(
                  "w-full rounded-[var(--radius-lg)] border p-4 text-left transition-all",
                  isActive
                    ? "border-primary/40 bg-primary/12 text-foreground shadow-glow"
                    : "border-border/80 bg-card/75 text-muted-foreground shadow-card hover:border-border hover:bg-white/5 hover:text-foreground"
                )}
              >
                <div className="flex items-start gap-3">
                  <div className={cn("rounded-2xl border p-3", isActive ? "border-primary/30 bg-primary/10 text-primary" : "border-border/70 bg-white/5 text-muted-foreground")}>
                    <Icon className="size-5" />
                  </div>
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm font-semibold">{tab.label}</span>
                      {isActive ? <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">Active</span> : null}
                    </div>
                    <p className="text-sm text-muted-foreground">{tab.description}</p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        <SurfaceCard className="overflow-hidden p-0">
          <div className="border-b border-border/70 px-6 py-4">
            <div className="flex items-center gap-3">
              <div className="rounded-2xl border border-primary/20 bg-primary/10 p-3 text-primary">
                <ActiveIcon className="size-5" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-foreground">{activeMeta.label}</h2>
                <p className="text-sm text-muted-foreground">{activeMeta.description}</p>
              </div>
            </div>
          </div>
          <div className="p-6">
            <Content tab={activeTab} />
          </div>
        </SurfaceCard>
      </div>
    </div>
  );
}
