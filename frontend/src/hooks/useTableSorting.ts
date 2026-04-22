import { useMemo, useState } from "react";

function normalizeValue(value: any) {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return value;
  if (typeof value === "boolean") return value ? 1 : 0;
  if (value instanceof Date) return value.getTime();
  const date = new Date(value);
  if (!Number.isNaN(date.getTime()) && typeof value === "string" && value.includes("-")) {
    return date.getTime();
  }
  return String(value).toLowerCase();
}

export function compareTableValues(left: any, right: any) {
  const a = normalizeValue(left);
  const b = normalizeValue(right);
  if (a === b) return 0;
  return a > b ? 1 : -1;
}

export function useTableSorting<T>(
  rows: T[],
  {
    initialKey,
    initialDirection = "asc",
    sorters = {},
  }: {
    initialKey?: string | null;
    initialDirection?: "asc" | "desc";
    sorters?: Record<string, (left: T, right: T) => number>;
  } = {}
) {
  const [sortKey, setSortKey] = useState<string | null>(initialKey || null);
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">(initialDirection);

  const sortedRows = useMemo(() => {
    if (!sortKey) return rows;
    const sorter = sorters[sortKey];
    if (!sorter) return rows;
    const items = [...rows].sort((left, right) => {
      const result = sorter(left, right);
      return sortDirection === "asc" ? result : -result;
    });
    return items;
  }, [rows, sortDirection, sortKey, sorters]);

  function requestSort(nextKey: string) {
    if (sortKey === nextKey) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextKey);
    setSortDirection("asc");
  }

  return {
    sortKey,
    sortDirection,
    sortedRows,
    requestSort,
    setSortKey,
    setSortDirection,
  };
}
