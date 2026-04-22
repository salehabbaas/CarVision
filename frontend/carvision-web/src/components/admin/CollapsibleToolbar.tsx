import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

type CollapsibleToolbarProps = {
  title: string;
  summary?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
};

export default function CollapsibleToolbar({
  title,
  summary,
  defaultOpen = false,
  children,
}: CollapsibleToolbarProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="panel glass">
      <div className="panel-head">
        <div>
          <h3>{title}</h3>
          {summary ? <div className="tiny muted">{summary}</div> : null}
        </div>
        <button className="btn ghost" type="button" onClick={() => setOpen((v) => !v)}>
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          {open ? "Collapse" : "Open"}
        </button>
      </div>
      {open ? <div className="toolbar" style={{ paddingTop: 12 }}>{children}</div> : null}
    </div>
  );
}
