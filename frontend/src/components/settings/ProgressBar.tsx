export default function ProgressBar({
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
