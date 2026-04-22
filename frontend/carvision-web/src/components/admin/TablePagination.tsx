type TablePaginationProps = {
  page: number;
  totalPages: number;
  totalItems: number;
  pageSize: number;
  currentCount: number;
  pageSizeOptions?: number[];
  itemLabel?: string;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (pageSize: number) => void;
};

export default function TablePagination({
  page,
  totalPages,
  totalItems,
  pageSize,
  currentCount,
  pageSizeOptions = [10, 25, 50, 100],
  itemLabel = "rows",
  onPageChange,
  onPageSizeChange,
}: TablePaginationProps) {
  const safeTotalPages = Math.max(1, totalPages || 1);
  const safePage = Math.min(Math.max(1, page || 1), safeTotalPages);
  const start = totalItems > 0 ? (safePage - 1) * pageSize + 1 : 0;
  const end = totalItems > 0 ? start + currentCount - 1 : 0;

  return (
    <div className="row between" style={{ marginTop: 8, flexWrap: "wrap", gap: 10 }}>
      <div className="tiny muted">
        {totalItems > 0
          ? `${start}-${end} of ${totalItems} ${itemLabel}`
          : `0 ${itemLabel}`}
      </div>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        {pageSizeOptions.length && onPageSizeChange ? (
          <select
            title="Rows per page"
            value={pageSize}
            onChange={(event) => onPageSizeChange(Number(event.target.value) || pageSize)}
          >
            {pageSizeOptions.map((option) => (
              <option key={option} value={option}>
                {option} / page
              </option>
            ))}
          </select>
        ) : null}
        <button
          className="btn ghost"
          type="button"
          onClick={() => onPageChange(safePage - 1)}
          disabled={safePage <= 1}
        >
          Prev
        </button>
        <span className="tiny muted">
          Page {safePage} / {safeTotalPages}
        </span>
        <button
          className="btn ghost"
          type="button"
          onClick={() => onPageChange(safePage + 1)}
          disabled={safePage >= safeTotalPages}
        >
          Next
        </button>
      </div>
    </div>
  );
}
