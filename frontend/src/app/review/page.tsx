"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

import { PageHeading } from "@/components/layout/PageHeading";
import { EmptyState, ErrorState } from "@/components/layout/States";
import { CaseCard } from "@/components/pipeline/CaseCard";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  decideReview,
  fetchCase,
  fetchReviewQueue,
  queryKeys,
  requestDeepReview,
  reviewDocumentUrl,
} from "@/lib/api";
import { HelpDot } from "@/components/help/HelpDot";
import {
  actionLabel,
  caseStateLabel,
  complianceStatusLabel,
  humaniseCode,
  lowerFirst,
} from "@/lib/format";
import { useTenant } from "@/lib/tenant-context";
import {
  HUMAN_ACTION_RESULT,
  type Case,
  type HumanAction,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const ACTION_LABEL: Record<HumanAction, string> = {
  release: "Release",
  block: "Block",
  request_info: "Request info",
};

export default function ReviewQueuePage() {
  const { tenant } = useTenant();
  const queryClient = useQueryClient();

  const [cursor, setCursor] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

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
    enabled: selectedId !== null,
    retry: false,
  });

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
      <PageHeading title="Review Queue">
        Cases the agent could not close on its own. Nothing leaves these states
        without a named reviewer and, for anything other than a plain release, a
        written reason.
      </PageHeading>

      <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
        <section className="min-w-0">
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
                  onOpen={setSelectedId}
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

        <section className="min-w-0">
          {selected === null ? (
            <EmptyState title="Pick a case">
              The decision form, the findings behind the score and the scanned
              paperwork appear here.
            </EmptyState>
          ) : (
            <ReviewPanel
              summary={selected}
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

/**
 * The archived paperwork, or a specific reason there is none.
 *
 * Decided from `provenance` on the case rather than by probing the endpoint: the
 * case already carries `uri`, `generated` and, when archiving failed, `reason`.
 * Fetching the PDF just to discover it is a 404 would download it twice on the
 * happy path.
 *
 * The distinction matters. "No document" and "the document was rendered but
 * DOCUMENT_BUCKET is not configured" are different facts with different owners --
 * the second is an operator's deployment gap, and an empty frame invites a
 * reviewer to conclude the shipment arrived with no paperwork.
 */
/**
 * CONFIRM or DISAGREE, legible without reading JSON.
 *
 * The debate payload was rendered only as a `JSON.stringify` dump, and grepping the
 * whole console for CONFIRM or DISAGREE returned nothing rendered anywhere -- so the
 * one hop that runs Nemotron Ultra, and the only hop whose verdict the deterministic
 * floor does not override, was the least readable thing on the screen.
 *
 * The dump stays. It is the honest artefact and this badge is a convenience over it,
 * which is also why extraction is defensive rather than typed: `debate` is
 * `Record<string, unknown>` on the wire, the verdict has lived at two different depths
 * across versions, and if none of the known shapes match this renders nothing at all
 * rather than guessing. A badge that invents a verdict would be worse than no badge on
 * a screen whose whole purpose is that a human can check the machine.
 */
function DebateVerdictBadge({ debate }: { debate: Record<string, unknown> }) {
  function pick(source: unknown): string | null {
    if (!source || typeof source !== "object") return null;
    const v = (source as Record<string, unknown>).verdict;
    if (typeof v === "string") return v;
    if (v && typeof v === "object") {
      const inner = (v as Record<string, unknown>).verdict;
      if (typeof inner === "string") return inner;
    }
    return null;
  }

  const verdict = pick(debate) ?? pick(debate.result);
  if (verdict !== "CONFIRM" && verdict !== "DISAGREE") return null;

  const confirmed = verdict === "CONFIRM";
  return (
    <span
      className={cn(
        "rounded border px-1.5 py-0.5 font-mono text-[10.5px] uppercase tracking-wide",
        confirmed
          ? "border-risk-clear/40 bg-risk-clear/[0.12] text-risk-clear"
          : "border-risk-critical/40 bg-risk-critical/[0.12] text-risk-critical",
      )}
      title={
        confirmed
          ? "The Senior Auditor agreed with the Junior Analyst's assessment."
          : "The Senior Auditor found something the Junior Analyst missed."
      }
    >
      {verdict}
    </span>
  );
}

function Paperwork({ case: c }: { case: Case }) {
  const provenance = (c.provenance ?? {}) as Record<string, unknown>;
  const uri = typeof provenance.uri === "string" ? provenance.uri : null;
  const generated = provenance.generated === true;
  const reason =
    typeof provenance.reason === "string" ? provenance.reason : null;
  const filename =
    typeof provenance.filename === "string" ? provenance.filename : null;

  return (
    <div className="bento-card overflow-hidden p-0">
      <h3 className="px-4 pb-2 pt-4 text-[12px] font-medium text-white">
        Paperwork
      </h3>

      {uri ? (
        <>
          <p className="px-4 pb-3 text-[11.5px] leading-relaxed text-dim">
            {generated ? (
              <>
                This case arrived as a structured event, so the document below is
                a{" "}
                <span className="text-risk-warn">rendered reconstruction</span>,
                not an original. It is flagged as generated so it is never read as
                scanned paperwork.
              </>
            ) : (
              <>The document this case was extracted from, as submitted.</>
            )}
          </p>
          {/*
            An <object> rather than an <iframe> with a PDF src: the proxy passes
            the upstream content type through, and an iframe pointed at a PDF is
            at the mercy of the browser's viewer settings. `key` forces a reload
            when the selection changes, which an iframe with a changed src does
            not reliably do.
          */}
          <object
            key={c.case_id}
            data={reviewDocumentUrl(c.case_id)}
            type="application/pdf"
            className="h-[28rem] w-full border-t border-white/[0.06] bg-black/40"
          >
            <p className="p-4 text-[12px] text-dim">
              Your browser would not render it inline.{" "}
              <a
                href={reviewDocumentUrl(c.case_id)}
                className="text-brand hover:underline"
                target="_blank"
                rel="noreferrer noopener"
              >
                Open it in a new tab
              </a>
              .
            </p>
          </object>
        </>
      ) : (
        <div className="border-t border-white/[0.06] px-4 py-5">
          <p className="text-[12px] leading-relaxed text-dim">
            {reason === "DOCUMENT_BUCKET not configured" ? (
              <>
                A bill of lading{filename ? ` (${filename})` : ""} was rendered
                for this case but could not be stored:{" "}
                <span className="font-mono text-risk-warn">
                  DOCUMENT_BUCKET is not configured
                </span>{" "}
                on this deployment. That is a deployment gap rather than a missing
                document — the shipment data itself is complete, and the findings
                above were computed from it.
              </>
            ) : reason ? (
              <>
                No archived document:{" "}
                <span className="font-mono text-white/80">{reason}</span>
              </>
            ) : (
              <>
                No archived document for this case. Every case is supposed to be
                reviewable against paperwork, so this is worth reporting rather
                than working around.
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}

function ReviewPanel({
  summary,
  detail,
  detailLoading,
  detailError,
  onDecided,
}: {
  summary: Case;
  detail: Case | undefined;
  detailLoading: boolean;
  detailError: unknown;
  onDecided: () => void;
}) {
  const c = detail ?? summary;
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<HumanAction | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [confirmDeep, setConfirmDeep] = useState(false);

  // Who this decision will be recorded as.
  //
  // This used to be a text input the reviewer typed, and the typed value was what
  // went onto the audit trail. That is worse than recording nothing: it reads as
  // accountability while being unverifiable, and nothing stopped someone entering a
  // colleague's name. The server now takes the address from the verified session and
  // ignores anything sent in the body, so this is display only -- shown because a
  // person about to release a shipment should see whose name it will carry.
  const identity = useQuery({
    queryKey: ["auth", "session"],
    queryFn: async () => {
      const response = await fetch("/api/auth/session", { cache: "no-store" });
      if (response.status === 401) return null;
      if (!response.ok) throw new Error(`session: ${response.status}`);
      return (await response.json()) as { email: string };
    },
    retry: false,
  });

  const decide = useMutation({
    mutationFn: (action: HumanAction) =>
      decideReview({ caseId: c.case_id, action, note }),
    onSuccess: (result) => {
      // The backend answers {ok: false, error} with a 400 for a refused
      // decision, which is a normal outcome rather than a transport failure. So
      // it lands in onSuccess and has to be checked, not assumed.
      if (!result.ok) {
        setFormError(result.error ?? "The decision was refused.");
        return;
      }
      setFormError(null);
      setNote("");
      onDecided();
    },
    onError: (error) => {
      setFormError(error instanceof Error ? error.message : String(error));
    },
  });

  const deep = useMutation({
    mutationFn: () => requestDeepReview(c.case_id),
    onSuccess: (result) => {
      if (!result.ok) setFormError(result.error ?? "Deep review was refused.");
      else onDecided();
    },
    onError: (error) => {
      setFormError(error instanceof Error ? error.message : String(error));
    },
  });

  const rec = c.reconciliation;
  // Read from the server, not re-derived. This computed
  //   Math.abs(effective_risk - model_risk) >= 15
  // which cannot express the rule: `effective_risk` is max(model, floor), so on any
  // case where the model scored ABOVE the floor the difference is zero and a genuine
  // dispute is invisible, while `Math.abs` would also fire on the impossible reverse
  // direction. verifier.reconcile() sets `score_disputed` as (floor - model) >= 15 --
  // deliberately one-directional, because only the model under-scoring against the
  // floor is a dispute worth a debate.
  const disputed = rec?.score_disputed === true;

  const findings = c.validation?.findings ?? [];

  function submit(action: HumanAction) {
    // Validated here as well as server-side, so the reviewer is told what is
    // missing before a round trip rather than after one.
    //
    // The reviewer's identity is no longer validated here because it is no longer
    // this screen's to supply: an unauthenticated caller never reaches the console
    // at all, and the server reads the name from the verified session.
    if (action !== "release" && !note.trim()) {
      setFormError(
        `A note is required to ${action.replace("_", " ")}. A refusal nobody has to justify is not a control.`,
      );
      return;
    }
    setFormError(null);
    setPending(action);
  }

  return (
    <div className="space-y-3">
      {disputed && (
        <div className="flex items-start gap-2 rounded-lg border border-risk-warn/30 bg-risk-warn/[0.07] px-3 py-2.5">
          <AlertTriangle className="mt-[1px] size-4 shrink-0 text-risk-warn" aria-hidden />
          <p className="text-[12px] leading-relaxed text-risk-warn">
            The model scored {rec?.model_risk} and the deterministic floor put
            this at {rec?.risk_floor}. The floor stands, so this case carries{" "}
            {rec?.effective_risk} — read the findings before deciding.
          </p>
        </div>
      )}

      <div className="bento-card p-4">
        <h2 className="font-mono text-[13px] text-white">
          {c.shipment_id || c.case_id}
        </h2>
        <p className="mt-0.5 text-[11.5px] text-dim">
          {caseStateLabel(c.state)}
          {c.requires_human && " · flagged for a person"}
        </p>

        {detailError ? (
          <div className="mt-3">
            <ErrorState error={detailError} />
          </div>
        ) : detailLoading ? (
          <Skeleton className="mt-3 h-24 rounded-lg bg-white/[0.04]" />
        ) : (
          <>
            {c.gate_denials && c.gate_denials.length > 0 && (
              <p className="mt-3 rounded-md border border-risk-critical/30 bg-risk-critical/[0.07] px-2.5 py-2 text-[11.5px] leading-relaxed text-risk-critical">
                The delegation boundary refused{" "}
                {c.gate_denials.map((d) => actionLabel(d.action)).join(", ")}, so
                the agent&rsquo;s proposed{" "}
                {c.proposed_outcome
                  ? complianceStatusLabel(c.proposed_outcome)
                  : "outcome"}{" "}
                was never executed.
              </p>
            )}

            {findings.length > 0 && (
              <ul className="mt-3 space-y-1.5">
                {findings.map((f, i) => (
                  <li
                    key={`${f.code}-${i}`}
                    className="rounded-md border border-white/[0.07] bg-black/25 px-2.5 py-2"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span className="text-[11.5px] font-medium text-white/90">
                          {humaniseCode(f.code)}
                        </span>
                        <HelpDot id={`finding:${f.code}`} />
                      </span>
                      <span className="shrink-0 font-mono text-[10.5px] tabular-nums text-faint">
                        floor {f.floor}
                      </span>
                    </div>
                    <p className="mt-0.5 text-[11.5px] leading-relaxed text-dim">
                      {f.detail}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      <div className="bento-card p-4">
        <div className="flex items-center gap-1.5">
          <h3 className="text-[12px] font-medium text-white">Decision</h3>
          <HelpDot id="review.decision" />
        </div>

        {/* Signed out: explain, do not offer.
            Reads are public on this deployment, so somebody can reach this panel
            with no session. Rendering the buttons anyway would mean their first
            information about the login is a 401 on a release they thought they had
            recorded -- and for a shipment release, believing you acted when you did
            not is the worst possible failure. `isLoading` is excluded so the panel
            does not flicker through this state on every load. */}
        {!identity.isLoading && !identity.data ? (
          <div className="mt-3 rounded-md border border-white/10 bg-black/20 p-3">
            <p className="text-[12px] leading-relaxed text-dim">
              You are viewing this queue read-only. Recording a decision needs a
              signed-in account, because the audit trail names the person who
              decided rather than the service that called the API.
            </p>
            <a
              href={`/login?next=${encodeURIComponent("/review")}`}
              className="mt-2.5 inline-flex h-8 items-center rounded-md border border-white/15 px-3 text-[12px] text-white/90 transition-colors hover:border-white/30"
            >
              Sign in to record a decision
            </a>
          </div>
        ) : (
        <div className="mt-3 space-y-3">
          <div>
            <Label className="text-[11.5px] text-dim">Recorded as</Label>
            <p className="mt-1 truncate rounded-md border border-white/10 bg-black/30 px-2.5 py-[7px] font-mono text-[12px] text-white/90">
              {identity.data?.email ?? "your signed-in account"}
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-faint">
              Taken from your session, not typed. The audit trail records this
              address and it cannot be overridden from this screen.
            </p>
          </div>

          <div>
            <Label htmlFor="note" className="text-[11.5px] text-dim">
              Reason{" "}
              <span className="text-faint">
                (required for block and request info)
              </span>
            </Label>
            <Textarea
              id="note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder="What you checked and what you concluded"
              className="mt-1 border-white/10 bg-black/30 text-[12.5px]"
            />
          </div>

          {formError && (
            <p className="rounded-md border border-risk-critical/30 bg-risk-critical/[0.07] px-2.5 py-2 text-[11.5px] leading-relaxed text-risk-critical">
              {formError}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            {(["release", "block", "request_info"] as HumanAction[]).map((action) => (
              // The dot sits beside the button, not inside it: nesting it would
              // put a second click target inside a control whose whole job is to
              // be pressed deliberately.
              <span key={action} className="inline-flex items-center gap-1">
                <Button
                  size="sm"
                  variant={action === "release" ? "default" : "outline"}
                  disabled={decide.isPending}
                  onClick={() => submit(action)}
                  className={cn(
                    "h-8 text-[12px]",
                    action === "block" &&
                      "border-risk-critical/40 text-risk-critical hover:bg-risk-critical/10",
                    action === "request_info" && "border-white/10",
                  )}
                >
                  {decide.isPending && pending === action && (
                    <Loader2 className="mr-1.5 size-3.5 animate-spin" />
                  )}
                  {ACTION_LABEL[action]}
                </Button>
                <HelpDot id={`action:${action}`} side="top" />
              </span>
            ))}

            <Button
              size="sm"
              variant="outline"
              // Guarded against a double submit as well as confirmed: this spends
              // Nemotron Super tokens, and a second click while the first is in
              // flight bills the tenant twice for the same answer.
              disabled={deep.isPending}
              onClick={() => setConfirmDeep(true)}
              className="ml-auto h-8 border-brand/40 text-[12px] text-brand hover:bg-brand/10"
            >
              {deep.isPending ? (
                <Loader2 className="mr-1.5 size-3.5 animate-spin" />
              ) : (
                <Sparkles className="mr-1.5 size-3.5" />
              )}
              Deep review
            </Button>
          </div>
        </div>
        )}
      </div>

      {detail?.debate != null && (
        <div className="bento-card p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[12px] font-medium text-white">
              Senior auditor debate
            </h3>
            <DebateVerdictBadge debate={detail.debate} />
          </div>
          <pre className="code-surface mt-2 max-h-64 overflow-auto whitespace-pre-wrap px-2.5 py-2 text-white/80 scrollbar-thin">
            {JSON.stringify(detail.debate, null, 2)}
          </pre>
        </div>
      )}

      <Paperwork case={c} />

      {/* Confirm on the decision, because it is not reversible from here. */}
      <AlertDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
      >
        <AlertDialogContent className="border-white/10 bg-slate-950">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px]">
              {pending ? ACTION_LABEL[pending] : ""} {c.shipment_id || c.case_id}?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[12.5px] leading-relaxed text-dim">
              This records{" "}
              <span className="text-white/85">
                {/* Lower-cased on purpose: this sits mid-sentence after "This
                    records", where the map's sentence-case label would read as a
                    stray capital. */}
                {pending ? lowerFirst(caseStateLabel(HUMAN_ACTION_RESULT[pending])) : ""}
              </span>{" "}
              against the case under your name, writes two audit records, and
              cannot be undone from this console.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-white/10 text-[12.5px]">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="text-[12.5px]"
              onClick={() => {
                if (pending) decide.mutate(pending);
                setPending(null);
              }}
            >
              Confirm
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Confirm on deep review, because it spends money. */}
      <AlertDialog open={confirmDeep} onOpenChange={setConfirmDeep}>
        <AlertDialogContent className="border-white/10 bg-slate-950">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px]">
              Run a deep review?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[12.5px] leading-relaxed text-dim">
              Nemotron Super re-reads the junior analyst&rsquo;s assessment and
              may run further searches. It is the most expensive operation in the
              system and it is billed to this tenant.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-white/10 text-[12.5px]">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="text-[12.5px]"
              onClick={() => {
                setConfirmDeep(false);
                deep.mutate();
              }}
            >
              Run it
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
