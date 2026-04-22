import { useRef, useState } from "react";
import { UploadCloud, X } from "lucide-react";

import { cn } from "@/lib/utils";

interface FileDropZoneProps {
  accept?: string;
  multiple?: boolean;
  value?: File | File[] | null;
  onChange: (value: File | File[] | null) => void;
  icon?: React.ReactNode;
  label?: string;
  hint?: string;
  error?: string;
  className?: string;
}

export default function FileDropZone({
  accept,
  multiple = false,
  value,
  onChange,
  icon,
  label = "Drop file here or click to browse",
  hint,
  error,
  className = "",
}: FileDropZoneProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);

  const files: File[] = multiple ? (Array.isArray(value) ? value : value ? [value] : []) : value instanceof File ? [value] : [];

  function handleFiles(fileList?: FileList | null) {
    const items = Array.from(fileList || []);
    if (!items.length) return;
    onChange(multiple ? items : items[0]);
  }

  return (
    <div className="space-y-2">
      <div
        className={cn(
          "group relative flex min-h-[160px] cursor-pointer flex-col items-center justify-center rounded-[var(--radius-lg)] border border-dashed border-border bg-white/5 px-6 py-8 text-center transition hover:border-primary/50 hover:bg-primary/5",
          dragging && "border-primary/60 bg-primary/10",
          error && "border-destructive/60 bg-destructive/5",
          className
        )}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          handleFiles(event.dataTransfer.files);
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") inputRef.current?.click();
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          className="hidden"
          onChange={(event) => handleFiles(event.target.files)}
        />

        {files.length ? (
          <div className="flex w-full items-start gap-4 text-left">
            <div className="rounded-full border border-emerald-400/30 bg-emerald-400/10 p-3 text-emerald-300">
              {icon || <UploadCloud className="size-5" />}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-foreground">Ready to upload</p>
              <div className="mt-2 space-y-1">
                {files.map((file, index) => (
                  <p key={`${file.name}-${index}`} className="truncate text-sm text-muted-foreground">
                    {file.name}
                  </p>
                ))}
              </div>
            </div>
            <button
              type="button"
              className="rounded-full border border-border bg-background/70 p-2 text-muted-foreground transition hover:border-destructive/50 hover:text-destructive"
              onClick={(event) => {
                event.stopPropagation();
                onChange(multiple ? [] : null);
                if (inputRef.current) inputRef.current.value = "";
              }}
            >
              <X className="size-4" />
            </button>
          </div>
        ) : (
          <>
            <div className="rounded-full border border-primary/30 bg-primary/10 p-4 text-primary">
              {icon || <UploadCloud className="size-6" />}
            </div>
            <p className="mt-4 text-base font-semibold text-foreground">{label}</p>
            {hint ? <p className="mt-2 max-w-md text-sm text-muted-foreground">{hint}</p> : null}
          </>
        )}
      </div>
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}
