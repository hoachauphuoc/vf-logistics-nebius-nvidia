"use client";

import { Search, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SORT_LABELS, type PriorityFilter, type SortKey } from "@/lib/pipeline";

/** Radix Select has no empty-string value, so "all" stands in for no filter. */
const ALL = "all";

export function BoardToolbar({
  search,
  onSearch,
  sort,
  onSort,
  priority,
  onPriority,
  matched,
  totalFetched,
}: {
  search: string;
  onSearch: (next: string) => void;
  sort: SortKey;
  onSort: (next: SortKey) => void;
  priority: PriorityFilter;
  onPriority: (next: PriorityFilter) => void;
  matched: number;
  totalFetched: number;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <div className="relative min-w-0 flex-1 sm:max-w-xs">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint"
          aria-hidden
        />
        <Input
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Case, shipment, company, route"
          aria-label="Search the board"
          className="h-8 border-white/10 bg-black/30 pl-8 pr-7 text-[12.5px] placeholder:text-faint"
        />
        {search && (
          <button
            type="button"
            onClick={() => onSearch("")}
            aria-label="Clear search"
            className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-white"
          >
            <X className="size-3.5" />
          </button>
        )}
      </div>

      <Select
        value={priority === "" ? ALL : priority}
        onValueChange={(v) => onPriority(v === ALL ? "" : (v as PriorityFilter))}
      >
        <SelectTrigger
          className="h-8 w-[10.5rem] border-white/10 bg-black/30 text-[12.5px]"
          aria-label="Filter by priority"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All priorities</SelectItem>
          {/* Worded as a floor, because that is how the filter behaves: asking
              for HIGH shows CRITICAL too. A label reading plain "High" would
              imply an exact match and make the urgent cases look missing. */}
          <SelectItem value="CRITICAL">Critical only</SelectItem>
          <SelectItem value="HIGH">High and above</SelectItem>
          <SelectItem value="MEDIUM">Medium and above</SelectItem>
        </SelectContent>
      </Select>

      <Select value={sort} onValueChange={(v) => onSort(v as SortKey)}>
        <SelectTrigger
          className="h-8 w-[9.5rem] border-white/10 bg-black/30 text-[12.5px]"
          aria-label="Sort cases"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(SORT_LABELS).map(([key, label]) => (
            <SelectItem key={key} value={key}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <span className="ml-auto shrink-0 font-mono text-[11.5px] tabular-nums text-faint">
        {matched < totalFetched
          ? `${matched} of ${totalFetched} shown`
          : `${totalFetched} on board`}
      </span>
    </div>
  );
}
