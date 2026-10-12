"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";

import { HelpDot } from "@/components/help/HelpDot";
import { PageHeading } from "@/components/layout/PageHeading";
import { EmptyState, ErrorState } from "@/components/layout/States";
import { WorkCard } from "@/components/operations/WorkCard";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchWorklist, queryKeys } from "@/lib/api";
import { BUCKET_LABEL } from "@/lib/operations";
import { useTenant } from "@/lib/tenant-context";
import { WORK_BUCKETS, type WorkBucket, type WorkItem } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Today: every case waiting on someone, by what it is waiting for.
 *
 * The grouping is the API's (worklist.py) and so are the counts -- the whole
 * tenant's queue, not the page that loaded -- which is why this screen does not
 * re-derive anything from a list of cases. Each card says who holds the case and
 * the one thing to do next, and links to the case's own page, where it is done.
 */
export default function TodayPage() {
  const { tenant } = useTenant();
  const worklist = useQuery({
    queryKey: queryKeys.worklist(tenant.id),
    queryFn: fetchWorklist,
    refetchInterval: 30_000,
    retry: false,
  });

  const heading = (
    <PageHeading title="Today">
      Cases waiting on someone, grouped by what they are waiting for. Each card names
      who holds it and the next thing to do; open it to do it.
    </PageHeading>
  );

  if (worklist.isError) {
    return (
      <>
        {heading}
        <ErrorState error={worklist.error} />
      </>
    );
  }

  const data = worklist.data;
  // The execution group belongs to the verification loop. Until a case can be
  // approved without being executed in the same step it is always empty, and an
  // always-empty column reads as broken -- so it appears when it has work.
  const shown = WORK_BUCKETS.filter(
    (b) => b !== "awaiting_execution" || (data?.buckets[b]?.count ?? 0) > 0,
  );

  return (
    <>
      {heading}

      {data?.truncated && (
        <p className="mb-4 flex items-start gap-2 rounded-lg border border-risk-warn/30 bg-risk-warn/[0.07] px-3 py-2 text-[12px] text-risk-warn">
          <AlertTriangle className="mt-[1px] size-4 shrink-0" aria-hidden />
          More cases are waiting than one read covers ({data.scanned} read). The counts
          below are of those {data.scanned}, not of the whole queue.
        </p>
      )}

      <div className="mb-4 flex items-center gap-1.5 text-[12px] text-dim">
        {worklist.isLoading ? (
          <Skeleton className="h-4 w-40 bg-white/[0.04]" />
        ) : (
          <span>
            <span className="font-semibold tabular-nums text-white">{data?.total ?? 0}</span>{" "}
            {data?.total === 1 ? "case is" : "cases are"} waiting on someone
          </span>
        )}
        <HelpDot id="today.groups" />
      </div>

      <div
        className={cn(
          "grid gap-4",
          shown.length === 4 ? "xl:grid-cols-4 md:grid-cols-2" : "lg:grid-cols-3",
        )}
      >
        {shown.map((bucket) => (
          <BucketColumn
            key={bucket}
            bucket={bucket}
            loading={worklist.isLoading}
            count={data?.buckets[bucket]?.count ?? 0}
            items={data?.buckets[bucket]?.items ?? []}
          />
        ))}
      </div>
    </>
  );
}

function BucketColumn({
  bucket,
  loading,
  count,
  items,
}: {
  bucket: WorkBucket;
  loading: boolean;
  count: number;
  items: WorkItem[];
}) {
  const label = BUCKET_LABEL[bucket];
  return (
    <section aria-label={label.title} className="min-w-0">
      <div className="mb-2">
        <div className="flex items-center gap-2">
          <h2 className="text-[13px] font-medium text-white">{label.title}</h2>
          {!loading && (
            <span className="rounded-full bg-white/[0.07] px-2 py-0.5 text-[11px] tabular-nums text-white/80">
              {count}
            </span>
          )}
          <HelpDot id={`today.${bucket}`} />
        </div>
        <p className="mt-0.5 text-[11.5px] leading-relaxed text-faint">{label.blurb}</p>
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-lg bg-white/[0.04]" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState title="Nothing here">No case is waiting for this.</EmptyState>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.case_id}>
              <WorkCard item={item} />
            </li>
          ))}
          {count > items.length && (
            <li className="px-1 text-[11px] text-faint">
              Showing the {items.length} most urgent of {count}.
            </li>
          )}
        </ul>
      )}
    </section>
  );
}
