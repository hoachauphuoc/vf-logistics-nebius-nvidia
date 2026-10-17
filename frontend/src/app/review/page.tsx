"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Suspense, useCallback, useMemo, useRef, useState } from "react";

import { HelpDot } from "@/components/help/HelpDot";
import { PageHeading } from "@/components/layout/PageHeading";
import { EmptyState, ErrorState } from "@/components/layout/States";
import { CaseCard } from "@/components/pipeline/CaseCard";
import { ReviewPanel } from "@/components/review/ReviewPanel";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchCase, fetchReviewQueue, queryKeys } from "@/lib/api";
import { caseRefetchMs } from "@/lib/operations";
import { useTenant } from "@/lib/tenant-context";
import { CaseParamListener, writeCaseParam } from "@/lib/url-state";

export default function ReviewQueuePage() {
  const { tenant } = useTenant();
  const queryClient = useQueryClient();

  const [cursor, setCursor] = useState<string | null>(null);
  // Mirrored into ?case=, so a case can be linked to from the board, a toast or
  // the audit trail, and survives a refresh.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const panelRef = useRef<HTMLElement>(null);

  const select = useCallback((caseId: string) => {
    setSelectedId(caseId);
    writeCaseParam(caseId);
    // On a phone the panel is below the whole queue, so picking a case appeared
    // to do nothing. Scrolled into view only when the layout is one column.
    if (window.matchMedia("(max-width: 1023px)").matches) {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      requestAnimationFrame(() =>
        panelRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" }),
      );
    }
  }, []);

  const queue = useQuery({
    queryKey: [...queryKeys.reviewQueue(tenant.id), cursor ?? "first"],
    queryFn: () => fetchReviewQueue({ cursor, limit: 40 }),
    retry: false,
  });

  // Memoised together so the `?? []` fallback does not produce a fresh array
  // reference on every render, which would defeat the lookup memo below.
  const { cases, selected } = useMemo(() => {
    const items = queue.data?.items ?? [];
    return {
      cases: items,
      // The selected case is resolved from the current page rather than stored,
      // for the same reason the Risk Radar sheet does it: a stored case object
      // would survive a tenant switch and put one tenant's case above another's
      // queue.
      selected: items.find((c) => c.case_id === selectedId) ?? null,
    };
  }, [queue.data, selectedId]);

  // The full document, for the findings and the paperwork. The queue returns
  // whole cases already, but not reliably the fat fields, so this is fetched per
  // selection rather than assumed present.
  const detail = useQuery({
    queryKey: queryKeys.case(tenant.id, selectedId ?? ""),
    queryFn: () => fetchCase(selectedId as string),
    // The panel shows this document, and an execution ends on the server without anyone asking this page (N08).
    refetchInterval: (query) => caseRefetchMs(query.state.data?.state),
    enabled: selectedId !== null,
    retry: false,
  });

  // A case linked to by id may not be on the page of the queue that is loaded --
  // or may no longer be awaiting anyone. The fetched document stands in for the
  // summary then, and the panel says what state the case is in.
  const shown =
    selected ?? (detail.data && detail.data.case_id === selectedId ? detail.data : null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.reviewQueue(tenant.id) });
    queryClient.invalidateQueries({ queryKey: ["case", tenant.id] });
    queryClient.invalidateQueries({ queryKey: queryKeys.snapshot(tenant.id, true) });
  };

  if (queue.isError) {
    return (
      <>
        <PageHeading title="Review Queue">
          Cases the agent could not close on its own.
        </PageHeading>
        <ErrorState error={queue.error} />
      </>
    );
  }

  return (
    <>
      <Suspense fallback={null}>
        <CaseParamListener onChange={setSelectedId} />
      </Suspense>

      <PageHeading title="Review Queue">
        Cases the agent could not close on its own. Nothing leaves these states
        without a named reviewer and, for anything other than a plain release, a
        written reason.
      </PageHeading>

      <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
        <section className="min-w-0" aria-label="Cases awaiting a decision">
          <div className="mb-2 flex items-center gap-1.5">
            <h2 className="text-[12px] font-medium text-white">
              Waiting on a person
            </h2>
            <HelpDot id="review.queue" />
          </div>
          {queue.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-28 rounded-lg bg-white/[0.04]" />
              ))}
            </div>
          ) : cases.length === 0 ? (
            <EmptyState title="The queue is empty">
              Every case has either cleared on the rules, cleared through the
              agents, or been disposed of by a reviewer.
            </EmptyState>
          ) : (
            <div className="space-y-2">
              {cases.map((c) => (
                <CaseCard
                  key={c.case_id}
                  case={c}
                  onOpen={select}
                  selected={c.case_id === selectedId}
                />
              ))}
            </div>
          )}

          {/*
            Forward-only paging. The cursor API gives no previous token, so a
            "Back" button would have to re-walk from the start -- and a control
            that silently jumps to page one is worse than no control. "Start
            again" says what it does.
          */}
          <div className="mt-3 flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!queue.data?.next_cursor || queue.isFetching}
              onClick={() => setCursor(queue.data?.next_cursor ?? null)}
              className="h-8 border-white/10 text-[12px]"
            >
              Next 40
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
          </div>
        </section>

        <section className="min-w-0 scroll-mt-20" ref={panelRef} aria-label="Selected case">
          {shown === null ? (
            selectedId !== null && detail.isLoading ? (
              <Skeleton className="h-48 rounded-xl bg-white/[0.04]" />
            ) : selectedId !== null && detail.isError ? (
              <ErrorState error={detail.error} />
            ) : (
              <EmptyState title="Pick a case">
                The decision form, the findings behind the score and the scanned
                paperwork appear here.
              </EmptyState>
            )
          ) : (
            <ReviewPanel
              key={shown.case_id}
              summary={shown}
              detail={detail.data}
              detailLoading={detail.isLoading}
              detailError={detail.error}
              onDecided={invalidate}
            />
          )}
        </section>
      </div>
    </>
  );
}

