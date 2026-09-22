"use client";

import { useQuery } from "@tanstack/react-query";
import { Ban, Check, RotateCw, Search, SkipForward, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PageHeading } from "@/components/layout/PageHeading";
import { EmptyState, ErrorState } from "@/components/layout/States";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { fetchAuditTrail, queryKeys } from "@/lib/api";
import { actionLabel, auditStatusLabel } from "@/lib/format";
import { useTenant } from "@/lib/tenant-context";
import { cn } from "@/lib/utils";

const ALL = "all";

/**
 * Actions worth filtering by.
 *
 * A fixed list rather than derived from the rows on screen: deriving it would
 * offer only the actions already visible, so filtering could never *find*
 * anything the current page did not already show. These are the action names
 * tools.py and governance.py actually write.
 */
const ACTIONS = [
  "release_shipment",
  "hold_shipment",
  "assign_analyst",
  "draft_sar",
  "notify_webhook",
  "publish_decision",
  "human_release",
  "human_block",
  "human_request_info",
  "agent_decision",
  "gate_denied",
  "publish_delegation_boundary",
  "revoke_delegation_boundary",
  "update_prefilter_rules",
];

const STATUSES = ["done", "denied", "skipped", "failed"];

export default function AuditTrailPage() {
  const { tenant } = useTenant();

  // Three mutually exclusive filters, mirroring the backend: the route applies
  // whichever it finds and combining them would need a composite index this
  // project does not declare. Choosing one clears the others, rather than
  // sending several and being silently given a partial result.
  const [caseIdInput, setCaseIdInput] = useState("");
  const [caseId, setCaseId] = useState<string | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);

  // Debounced, so typing a case id does not fire a query per keystroke against
  // an indexed Firestore read.
  useEffect(() => {
    const trimmed = caseIdInput.trim();
    const timer = setTimeout(() => {
      setCaseId(trimmed || null);
      setCursor(null);
    }, 350);
    return () => clearTimeout(timer);
  }, [caseIdInput]);

  const filter = useMemo(
    () => ({ caseId, action, status }),
    [caseId, action, status],
  );

  const trail = useQuery({
    queryKey: [
      ...queryKeys.auditTrail(tenant.id, filter),
      status ?? "",
      cursor ?? "first",
    ],
    queryFn: () => fetchAuditTrail({ ...filter, cursor, limit: 60 }),
    retry: false,
  });

  const rows = trail.data?.items ?? [];
  const hasFilter = Boolean(caseId || action || status);

  function chooseAction(next: string | null) {
    setAction(next);
    if (next) {
      setCaseIdInput("");
      setCaseId(null);
      setStatus(null);
    }
    setCursor(null);
  }

  function chooseStatus(next: string | null) {
    setStatus(next);
    if (next) {
      setCaseIdInput("");
      setCaseId(null);
      setAction(null);
    }
    setCursor(null);
  }

  function clearAll() {
    setCaseIdInput("");
    setCaseId(null);
    setAction(null);
    setStatus(null);
    setCursor(null);
  }

  return (
    <>
      <PageHeading title="Audit Trail">
        Every action the system took, including the ones it was refused. A denial
        is recorded exactly like a success — a system that silently drops
        refusals cannot be audited in the direction that matters.
      </PageHeading>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 sm:max-w-xs">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint"
            aria-hidden
          />
          <Input
            value={caseIdInput}
            onChange={(e) => {
              setCaseIdInput(e.target.value);
              if (e.target.value.trim()) {
                setAction(null);
                setStatus(null);
              }
            }}
            placeholder="Exact case id"
            aria-label="Filter by case id"
            className="h-8 border-white/10 bg-black/30 pl-8 text-[12.5px] placeholder:text-faint"
          />
        </div>

        <Select
          value={action ?? ALL}
          onValueChange={(v) => chooseAction(v === ALL ? null : v)}
        >
          <SelectTrigger
            className="h-8 w-[13rem] border-white/10 bg-black/30 text-[12.5px]"
            aria-label="Filter by action"
          >
            <SelectValue placeholder="Any action" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Any action</SelectItem>
            {ACTIONS.map((a) => (
              // value stays the raw identifier: it is the filter sent to the API.
              // Only the child text is humanised.
              <SelectItem key={a} value={a}>
                {actionLabel(a)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={status ?? ALL}
          onValueChange={(v) => chooseStatus(v === ALL ? null : v)}
        >
          <SelectTrigger
            className="h-8 w-[9.5rem] border-white/10 bg-black/30 text-[12.5px]"
            aria-label="Filter by status"
          >
            <SelectValue placeholder="Any status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Any status</SelectItem>
            {STATUSES.map((s) => (
              // As above: value raw, label humanised.
              <SelectItem key={s} value={s}>
                {auditStatusLabel(s)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {hasFilter && (
          <Button
            variant="ghost"
            size="sm"
            onClick={clearAll}
            className="h-8 text-[12px] text-dim"
          >
            <X className="mr-1 size-3.5" />
            Clear
          </Button>
        )}

        <Button
          variant="outline"
          size="sm"
          onClick={() => trail.refetch()}
          disabled={trail.isFetching}
          className="h-8 border-white/10 text-[12px]"
        >
          <RotateCw className={cn("mr-1 size-3.5", trail.isFetching && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {hasFilter && (
        <p className="mb-2 text-[11.5px] text-faint">
          Filters are mutually exclusive and applied server-side on an indexed
          field. Choosing one clears the others.
        </p>
      )}

      {trail.isError ? (
        <ErrorState error={trail.error} />
      ) : trail.isLoading ? (
        <Skeleton className="h-96 rounded-xl bg-white/[0.04]" />
      ) : rows.length === 0 ? (
        <EmptyState title="No audit records match">
          {hasFilter
            ? "Nothing recorded under that filter. An empty result here means the filter found nothing, not that nothing happened."
            : "Nothing has been recorded yet for this tenant."}
        </EmptyState>
      ) : (
        <div className="bento-card overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="border-white/[0.06] hover:bg-transparent">
                <TableHead className="h-9 text-[11px] uppercase tracking-wide text-faint">
                  When
                </TableHead>
                <TableHead className="h-9 text-[11px] uppercase tracking-wide text-faint">
                  Action
                </TableHead>
                <TableHead className="h-9 text-[11px] uppercase tracking-wide text-faint">
                  Case
                </TableHead>
                <TableHead className="h-9 text-[11px] uppercase tracking-wide text-faint">
                  Status
                </TableHead>
                <TableHead className="h-9 text-[11px] uppercase tracking-wide text-faint">
                  Detail
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow
                  key={r.audit_id}
                  className="border-white/[0.05] hover:bg-white/[0.03]"
                >
                  <TableCell className="whitespace-nowrap font-mono text-[11px] text-faint">
                    {formatWhen(r.at)}
                  </TableCell>
                  <TableCell className="text-[11.5px] text-white/90">
                    {actionLabel(r.action)}
                  </TableCell>
                  <TableCell className="font-mono text-[11px] text-dim">
                    {r.case_id === "-" ? (
                      <span className="text-faint">system</span>
                    ) : (
                      r.case_id
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={r.status} />
                  </TableCell>
                  <TableCell className="max-w-md">
                    <DetailCell detail={r.detail} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <div className="mt-3 flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!trail.data?.next_cursor || trail.isFetching}
          onClick={() => setCursor(trail.data?.next_cursor ?? null)}
          className="h-8 border-white/10 text-[12px]"
        >
          Next 60
        </Button>
        {cursor && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setCursor(null)}
            className="h-8 text-[12px] text-dim"
          >
            Start again
          </Button>
        )}
        <span className="ml-auto font-mono text-[11.5px] tabular-nums text-faint">
          {rows.length} record(s)
        </span>
      </div>
    </>
  );
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "done"
      ? "badge-clear"
      : status === "denied"
        ? "badge-critical"
        : status === "failed"
          ? "badge-critical"
          : "badge-neutral";

  const Icon =
    status === "done" ? Check : status === "skipped" ? SkipForward : Ban;

  return (
    <span className={cn("badge-risk", tone)}>
      <Icon className="size-3" aria-hidden />
      {auditStatusLabel(status)}
    </span>
  );
}

/**
 * The most useful line from a detail blob, with the rest behind a toggle.
 *
 * `detail` is free-form per action, so there is no schema to render against.
 * Rather than dumping JSON into a table cell, the fields that carry the reason
 * are looked for by name and shown first — those are the ones an auditor reads.
 */
function DetailCell({ detail }: { detail: Record<string, unknown> | null | undefined }) {
  const [open, setOpen] = useState(false);

  if (!detail || Object.keys(detail).length === 0) {
    return <span className="text-[11px] text-faint">—</span>;
  }

  const summary =
    pick(detail, "gate_reason") ??
    pick(detail, "reason") ??
    pick(detail, "note") ??
    pick(detail, "rationale") ??
    pick(detail, "disposition") ??
    pick(detail, "author");

  return (
    <div className="min-w-0">
      {summary && (
        <p className="truncate text-[11.5px] leading-relaxed text-dim">{summary}</p>
      )}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="text-[10.5px] text-faint underline-offset-2 hover:text-white hover:underline"
      >
        {open ? "Hide" : summary ? "Full record" : "Show record"}
      </button>
      {open && (
        <pre className="code-surface mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words px-2 py-1.5 text-[10.5px] text-white/75 scrollbar-thin">
          {JSON.stringify(detail, null, 2)}
        </pre>
      )}
    </div>
  );
}

function pick(obj: Record<string, unknown>, key: string): string | null {
  const value = obj[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" })} ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
}
