"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  ExternalLink,
  Loader2,
  Plus,
  ShieldOff,
  Trash2,
  X,
} from "lucide-react";
import { useState } from "react";

import { PageHeading } from "@/components/layout/PageHeading";
import { EmptyState, ErrorState } from "@/components/layout/States";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  fetchAgentReadiness,
  fetchBoundaries,
  fetchDrift,
  fetchPrefilterRules,
  publishBoundary,
  queryKeys,
  revokeBoundary,
  savePrefilterRules,
  simulateBoundary,
  verifyEntity,
} from "@/lib/api";
import { HelpDot } from "@/components/help/HelpDot";
import { actionLabel, humaniseCode } from "@/lib/format";
import { useTenant } from "@/lib/tenant-context";
import type { DelegationBoundary, PrefilterRules } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function GovernancePage() {
  const { tenant } = useTenant();

  // Two queries, not one. `/governance/agent` answers "may the agent act" and
  // `/governance/drift` answers "does the traffic still look like what that
  // permission was written for" -- the drift route returns only the drift object,
  // so readiness has to be asked for separately.
  const agentQuery = useQuery({
    queryKey: queryKeys.agent(tenant.id),
    queryFn: fetchAgentReadiness,
    retry: false,
  });

  const driftQuery = useQuery({
    queryKey: queryKeys.drift(tenant.id),
    queryFn: fetchDrift,
    retry: false,
  });

  if (agentQuery.isError) {
    return (
      <>
        <PageHeading title="Governance">
          What the agent is permitted to do on its own.
        </PageHeading>
        <ErrorState error={agentQuery.error} />
      </>
    );
  }

  const agent = agentQuery.data;
  const suspended = agent != null && agent.state !== "READY";
  const drift = driftQuery.data;
  const material = drift?.material === true;
  // A failed drift read is not "no drift". Both leave `material === false`, so without
  // this the banner is simply absent and the screen looks like a clean bill of health on
  // a check that never ran -- the same shape as the three field-name bugs where a guarded
  // read rendered nothing and every test passed.
  const driftUnknown = driftQuery.isError;

  return (
    <>
      <PageHeading title="Governance">
        What the agent is permitted to do on its own, and whether the traffic
        still looks like what that permission was written for.
      </PageHeading>

      {/*
        The readiness banner, first and unmissable.

        With no published boundary the agent is SUSPENDED, every outcome stays a
        proposal, and nothing auto-clears. That is correct fail-closed behaviour
        and it is also the single most confusing thing about the system if it is
        not stated: an operator otherwise watches a pipeline where every case
        lands on a human and concludes the agents are broken.
      */}
      {agentQuery.isLoading ? (
        <Skeleton className="h-20 rounded-xl bg-white/[0.04]" />
      ) : (
        <div
          className={cn(
            "mb-4 flex items-start gap-3 rounded-xl border px-4 py-3",
            suspended
              ? "border-risk-critical/30 bg-risk-critical/[0.07]"
              : "border-risk-clear/25 bg-risk-clear/[0.05]",
          )}
        >
          <span className="mt-[2px] shrink-0">
            {suspended ? (
              <ShieldOff className="size-4 text-risk-critical" aria-hidden />
            ) : (
              <Check className="size-4 text-risk-clear" aria-hidden />
            )}
          </span>
          <div className="min-w-0">
            <p
              className={cn(
                "text-[13px] font-medium",
                suspended ? "text-risk-critical" : "text-risk-clear",
              )}
            >
              {suspended ? "Agent suspended" : `Operating under ${agent?.boundary?.boundary_id}`}
            </p>
            <p className="mt-0.5 text-[12px] leading-relaxed text-dim">
              {agent?.reason}
            </p>
            {suspended && (
              <p className="mt-1.5 text-[12px] leading-relaxed text-dim">
                Analysis still runs and every finding is still recorded. What
                stops is execution: each outcome stays a proposal and the case
                goes to a person instead.
              </p>
            )}
          </div>
        </div>
      )}

      {driftUnknown && (
        <div className="mb-4 flex items-start gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3">
          <AlertTriangle className="mt-[2px] size-4 shrink-0 text-dim" aria-hidden />
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-white">
              Drift could not be checked
            </p>
            <p className="mt-0.5 text-[12px] leading-relaxed text-dim">
              The drift read failed, so the absence of a warning below is not a
              statement that the traffic still matches what this boundary was published
              for. Re-check before relying on it.
            </p>
          </div>
        </div>
      )}

      {material && drift && (
        <div className="mb-4 flex items-start gap-3 rounded-xl border border-risk-warn/30 bg-risk-warn/[0.07] px-4 py-3">
          <AlertTriangle className="mt-[2px] size-4 shrink-0 text-risk-warn" aria-hidden />
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-risk-warn">
              Material drift from what this boundary was published for
            </p>
            <p className="mt-0.5 text-[12px] leading-relaxed text-dim">
              {drift.reason ?? drift.reasons?.join(" ") ?? "No reason given."}
            </p>
            {drift.metrics && (
              <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] tabular-nums text-dim">
                <Metric label="sample" value={drift.metrics.sample} />
                <Metric
                  label="auto-release"
                  value={pct(drift.metrics.auto_release_rate)}
                />
                <Metric label="veto" value={pct(drift.metrics.veto_rate)} />
                <Metric
                  label="injection"
                  value={pct(drift.metrics.injection_rate)}
                />
              </dl>
            )}
            <p className="mt-2 text-[12px] leading-relaxed text-dim">
              Suspending on drift is not a fault. It is the system declining to
              keep exercising authority granted for circumstances that no longer
              apply.
            </p>
          </div>
        </div>
      )}

      <Tabs defaultValue="boundary">
        <TabsList className="bg-white/[0.04]">
          <TabsTrigger value="boundary" className="text-[12.5px]">
            Delegation boundary
          </TabsTrigger>
          <TabsTrigger value="prefilter" className="text-[12.5px]">
            Pre-filter rules
          </TabsTrigger>
          <TabsTrigger value="verify" className="text-[12.5px]">
            Verify an entity
          </TabsTrigger>
        </TabsList>

        <TabsContent value="boundary" className="mt-4">
          <BoundaryTab />
        </TabsContent>
        <TabsContent value="prefilter" className="mt-4">
          <PrefilterTab />
        </TabsContent>
        <TabsContent value="verify" className="mt-4">
          <VerifyTab />
        </TabsContent>
      </Tabs>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-faint">{label}</dt>
      <dd className="text-white/85">{value}</dd>
    </div>
  );
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

// --------------------------------------------------------------------------
// Boundary
// --------------------------------------------------------------------------

function BoundaryTab() {
  const { tenant } = useTenant();
  const queryClient = useQueryClient();

  const boundaries = useQuery({
    queryKey: queryKeys.boundaries(tenant.id),
    queryFn: fetchBoundaries,
    retry: false,
  });

  const [author, setAuthor] = useState("");
  const [note, setNote] = useState("");
  const [json, setJson] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [simulation, setSimulation] = useState<Record<string, unknown> | null>(null);
  const [confirmPublish, setConfirmPublish] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState(false);

  const active = boundaries.data?.boundaries.find((b) => b.status === "ACTIVE") ?? null;
  const template = boundaries.data?.proposed_template;

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.boundaries(tenant.id) });
    queryClient.invalidateQueries({ queryKey: queryKeys.drift(tenant.id) });
    queryClient.invalidateQueries({ queryKey: queryKeys.agent(tenant.id) });
    queryClient.invalidateQueries({ queryKey: ["snapshot", tenant.id] });
  };

  /**
   * The permissions object, parsed from the textarea.
   *
   * A raw JSON editor rather than a form of checkboxes, deliberately. The
   * permissions schema is open-ended -- `auto_release` alone carries value caps,
   * risk caps, HS prefix lists and destination lists, and governance.check reads
   * keys a form would have to enumerate. A form that silently dropped an
   * unrecognised key would narrow a boundary without saying so, which is the one
   * failure mode this control cannot have. The template below is the starting
   * point, so nobody has to type it from memory.
   */
  function parsePermissions(): Record<string, unknown> | null {
    try {
      const parsed = JSON.parse(json) as unknown;
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setJsonError("Permissions must be a JSON object.");
        return null;
      }
      if (Object.keys(parsed).length === 0) {
        setJsonError(
          "An empty object is refused upstream. To remove the agent's authority, revoke instead.",
        );
        return null;
      }
      setJsonError(null);
      return parsed as Record<string, unknown>;
    } catch (error) {
      setJsonError(error instanceof Error ? error.message : "Invalid JSON.");
      return null;
    }
  }

  const simulate = useMutation({
    mutationFn: (permissions: Record<string, unknown>) => simulateBoundary(permissions),
    onSuccess: setSimulation,
    onError: (e) => setFormError(e instanceof Error ? e.message : String(e)),
  });

  const publish = useMutation({
    mutationFn: (permissions: Record<string, unknown>) =>
      publishBoundary({ permissions, author, note }),
    onSuccess: () => {
      setFormError(null);
      setSimulation(null);
      invalidate();
    },
    onError: (e) => setFormError(e instanceof Error ? e.message : String(e)),
  });

  const revoke = useMutation({
    mutationFn: () => revokeBoundary({ author, note }),
    onSuccess: () => {
      setFormError(null);
      invalidate();
    },
    onError: (e) => setFormError(e instanceof Error ? e.message : String(e)),
  });

  if (boundaries.isError) return <ErrorState error={boundaries.error} />;
  if (boundaries.isLoading) {
    return <Skeleton className="h-64 rounded-xl bg-white/[0.04]" />;
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-4">
        <div className="bento-card p-4">
          <div className="flex items-center gap-1.5">
            <h3 className="text-[12px] font-medium text-white">Publish a boundary</h3>
            <HelpDot id="governance.boundary" />
          </div>
          <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
            This is the only operation in the system that grants the agent
            authority, which is why it takes a name.
          </p>

          <div className="mt-3 space-y-3">
            <div>
              <Label htmlFor="gov-author" className="text-[11.5px] text-dim">
                Published by
              </Label>
              <Input
                id="gov-author"
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
                placeholder="Your name"
                className="mt-1 h-8 border-white/10 bg-black/30 text-[12.5px]"
              />
            </div>

            <div>
              <Label htmlFor="gov-note" className="text-[11.5px] text-dim">
                Why
              </Label>
              <Textarea
                id="gov-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={2}
                placeholder="What changed and on what basis"
                className="mt-1 border-white/10 bg-black/30 text-[12.5px]"
              />
            </div>

            <div>
              <div className="flex items-center justify-between gap-2">
                <Label htmlFor="gov-json" className="text-[11.5px] text-dim">
                  Permissions
                </Label>
                {template && (
                  <button
                    type="button"
                    onClick={() => {
                      setJson(JSON.stringify(template, null, 2));
                      setJsonError(null);
                    }}
                    className="text-[11px] text-brand hover:underline"
                  >
                    Load the conservative template
                  </button>
                )}
              </div>
              <Textarea
                id="gov-json"
                value={json}
                onChange={(e) => setJson(e.target.value)}
                rows={14}
                spellCheck={false}
                placeholder='{ "allowed_actions": [...], "auto_release": { ... } }'
                className="mt-1 border-white/10 bg-black/40 font-mono text-[11.5px] scrollbar-thin"
              />
              {jsonError && (
                <p className="mt-1 text-[11.5px] text-risk-critical">{jsonError}</p>
              )}
            </div>

            {formError && (
              <p className="rounded-md border border-risk-critical/30 bg-risk-critical/[0.07] px-2.5 py-2 text-[11.5px] leading-relaxed text-risk-critical">
                {formError}
              </p>
            )}

            <div className="flex flex-wrap gap-2">
              {/*
                Simulate first, and it is free: check() is pure, so nothing is
                written and no action is executed. A boundary is abstract until
                someone can see which cases stop being automatic, and publishing
                one blind is how an auto-release cap gets tightened by an order of
                magnitude by accident.
              */}
              <Button
                variant="outline"
                size="sm"
                disabled={simulate.isPending}
                onClick={() => {
                  const permissions = parsePermissions();
                  if (permissions) simulate.mutate(permissions);
                }}
                className="h-8 border-white/10 text-[12px]"
              >
                {simulate.isPending && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
                Simulate
              </Button>

              <Button
                size="sm"
                disabled={publish.isPending || !author.trim()}
                onClick={() => {
                  if (!author.trim()) {
                    setFormError("A name is required to grant authority.");
                    return;
                  }
                  if (parsePermissions()) setConfirmPublish(true);
                }}
                className="h-8 text-[12px]"
              >
                {publish.isPending && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
                Publish
              </Button>

              <Button
                variant="outline"
                size="sm"
                disabled={revoke.isPending || active === null}
                onClick={() => {
                  if (!author.trim()) {
                    setFormError("A name is required to revoke authority.");
                    return;
                  }
                  if (!note.trim()) {
                    setFormError("A reason is required to revoke authority.");
                    return;
                  }
                  setConfirmRevoke(true);
                }}
                className="ml-auto h-8 border-risk-critical/40 text-[12px] text-risk-critical hover:bg-risk-critical/10"
              >
                {revoke.isPending && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
                Revoke
              </Button>
            </div>
          </div>
        </div>

        {simulation && <SimulationResult result={simulation} onDismiss={() => setSimulation(null)} />}
      </div>

      <div className="bento-card p-4">
        <div className="flex items-center gap-1.5">
          <h3 className="text-[12px] font-medium text-white">History</h3>
          <HelpDot id="governance.history" />
        </div>
        <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
          Including superseded and revoked versions, because &ldquo;what was the
          agent allowed to do in March&rdquo; is a question an auditor asks.
        </p>

        {boundaries.data?.boundaries.length === 0 ? (
          <div className="mt-3">
            <EmptyState title="No boundary has ever been published">
              The agent has never held authority in this tenant. Every outcome so
              far will have gone to a human.
            </EmptyState>
          </div>
        ) : (
          <ol className="mt-3 space-y-2">
            {boundaries.data?.boundaries.map((b) => (
              <BoundaryRow key={b.boundary_id} boundary={b} />
            ))}
          </ol>
        )}
      </div>

      <AlertDialog open={confirmPublish} onOpenChange={setConfirmPublish}>
        <AlertDialogContent className="border-white/10 bg-slate-950">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px]">
              Grant the agent this authority?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[12.5px] leading-relaxed text-dim">
              From the moment this is published the agent may execute the actions
              it permits without asking anyone, including releasing shipments if
              the permissions allow it. It supersedes{" "}
              {active ? active.boundary_id : "nothing"} and is recorded against
              your name.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-white/10 text-[12.5px]">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="text-[12.5px]"
              onClick={() => {
                const permissions = parsePermissions();
                setConfirmPublish(false);
                if (permissions) publish.mutate(permissions);
              }}
            >
              Publish it
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirmRevoke} onOpenChange={setConfirmRevoke}>
        <AlertDialogContent className="border-white/10 bg-slate-950">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px]">
              Revoke the agent&rsquo;s authority?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[12.5px] leading-relaxed text-dim">
              This is the kill switch. Afterwards there is no active boundary, the
              agent reports SUSPENDED, and every protected action is denied —
              every case will land on a human until a new boundary is published.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-white/10 text-[12.5px]">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="text-[12.5px]"
              onClick={() => {
                setConfirmRevoke(false);
                revoke.mutate();
              }}
            >
              Revoke it
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function BoundaryRow({ boundary }: { boundary: DelegationBoundary }) {
  const [open, setOpen] = useState(false);
  const tone =
    boundary.status === "ACTIVE"
      ? "badge-clear"
      : boundary.status === "REVOKED"
        ? "badge-critical"
        : "badge-neutral";

  return (
    <li className="rounded-lg border border-white/[0.07] bg-black/25 px-2.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate font-mono text-[11.5px] text-white/90">
          {boundary.boundary_id}
        </span>
        <span className={cn("badge-risk shrink-0", tone)}>
          {humaniseCode(boundary.status)}
        </span>
      </div>
      <p className="mt-0.5 text-[11px] text-dim">
        {boundary.published_by ? `by ${boundary.published_by}` : "author unknown"}
        {boundary.published_at && ` · ${new Date(boundary.published_at).toLocaleString("en-GB")}`}
      </p>
      {boundary.note && (
        <p className="mt-0.5 text-[11px] leading-relaxed text-faint">{boundary.note}</p>
      )}
      {boundary.revocation_note && (
        <p className="mt-0.5 text-[11px] leading-relaxed text-risk-critical">
          revoked: {boundary.revocation_note}
        </p>
      )}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="mt-1 text-[10.5px] text-faint underline-offset-2 hover:text-white hover:underline"
      >
        {open ? "Hide permissions" : "Show permissions"}
      </button>
      {open && (
        <pre className="code-surface mt-1 max-h-56 overflow-auto whitespace-pre-wrap px-2 py-1.5 text-[10.5px] text-white/75 scrollbar-thin">
          {JSON.stringify(boundary.permissions, null, 2)}
        </pre>
      )}
    </li>
  );
}

function SimulationResult({
  result,
  onDismiss,
}: {
  result: Record<string, unknown>;
  onDismiss: () => void;
}) {
  const counts = (result.counts ?? {}) as Record<string, number>;
  const flipped = Array.isArray(result.flipped) ? result.flipped : [];
  const evaluated = typeof result.cases_evaluated === "number" ? result.cases_evaluated : null;
  const flippedCount =
    typeof result.flipped_count === "number" ? result.flipped_count : flipped.length;

  return (
    <div className="bento-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-[12px] font-medium text-white">
            What this boundary would change
          </h3>
          <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
            Replayed against {evaluated ?? "recent"} case(s) for{" "}
            <span>{actionLabel(String(result.action ?? "release_shipment"))}</span>
            . Nothing was written and no action ran.
          </p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss simulation"
          className="shrink-0 text-faint hover:text-white"
        >
          <X className="size-3.5" />
        </button>
      </div>

      <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] tabular-nums">
        {Object.entries(counts).map(([key, value]) => (
          <div key={key} className="flex items-baseline gap-1.5">
            <dt className="text-faint">{humaniseCode(key)}</dt>
            <dd
              className={cn(
                // now_denied is a tightening: work moves to humans. now_allowed is
                // a loosening: the agent would act on cases it previously could
                // not, which is the direction that deserves the louder colour.
                key === "now_denied" && value > 0 && "text-risk-warn",
                key === "now_allowed" && value > 0 && "text-risk-critical",
                !["now_denied", "now_allowed"].includes(key) && "text-white/85",
              )}
            >
              {value}
            </dd>
          </div>
        ))}
      </dl>

      {flippedCount > 0 && (
        <>
          <p className="mt-3 text-[11.5px] text-dim">
            {flippedCount} case(s) would be decided differently
            {flipped.length < flippedCount && `, first ${flipped.length} shown`}:
          </p>
          <ul className="mt-1.5 space-y-1">
            {flipped.slice(0, 10).map((f, i) => {
              const row = f as Record<string, unknown>;
              // `was` / `becomes`, which is what the backend calls them. An
              // earlier version read `before` / `after` and rendered every row as
              // "? → ?" -- a simulation that says nothing changed is worse than
              // no simulation, because it invites publishing.
              return (
                <li
                  key={String(row.case_id ?? i)}
                  className="rounded border border-white/[0.06] px-2 py-1.5"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="min-w-0 truncate font-mono text-[11px] text-white/85">
                      {String(row.shipment_id ?? row.case_id ?? "?")}
                    </span>
                    <span className="shrink-0 font-mono text-[10.5px] text-dim">
                      {String(row.was ?? "?")} → {String(row.becomes ?? "?")}
                    </span>
                  </div>
                  {typeof row.after_reason === "string" && (
                    <p className="mt-0.5 text-[10.5px] leading-relaxed text-faint">
                      {row.after_reason}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {flippedCount === 0 && (
        <p className="mt-3 text-[11.5px] text-dim">
          No case in the sample would be decided differently. That is a real
          answer, but a small sample is a weak one — it does not mean the change
          is inconsequential.
        </p>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Pre-filter rules
// --------------------------------------------------------------------------

/**
 * The pre-AI screening lists.
 *
 * State lives in React, not in the DOM. The old dashboard read the current lists
 * back out of the rendered markup and rebuilt them by splitting each row's text
 * on " → ", which meant a company name containing that sequence corrupted the
 * list, and a re-render mid-edit silently discarded pending changes.
 */
function PrefilterTab() {
  const { tenant } = useTenant();
  const queryClient = useQueryClient();

  const rules = useQuery({
    queryKey: queryKeys.prefilter(tenant.id),
    queryFn: fetchPrefilterRules,
    retry: false,
  });

  const [draft, setDraft] = useState<PrefilterRules | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (patch: Partial<PrefilterRules>) => savePrefilterRules(patch),
    onSuccess: () => {
      setError(null);
      setDraft(null);
      queryClient.invalidateQueries({ queryKey: queryKeys.prefilter(tenant.id) });
    },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });

  if (rules.isError) return <ErrorState error={rules.error} />;
  if (rules.isLoading || !rules.data) {
    return <Skeleton className="h-64 rounded-xl bg-white/[0.04]" />;
  }

  const current = draft ?? rules.data;
  const dirty = draft !== null;

  function edit(patch: Partial<PrefilterRules>) {
    setDraft({ ...current, ...patch });
  }

  return (
    <div className="space-y-4">
      <div className="bento-card p-4">
        <h3 className="text-[12px] font-medium text-white">
          Pre-AI screening rules
        </h3>
        <p className="mt-1 max-w-2xl text-[11.5px] leading-relaxed text-dim">
          These decide which shipments never reach a model: a blacklist match is
          an immediate floor of 100, a VIP match with a matching tax ID can skip
          AI entirely. They are stored per tenant — editing them here does not
          touch any other customer&rsquo;s screening.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ListEditor
          title="Blacklisted companies"
          note="An exact, normalised name match forces a floor of 100 and auto-rejects without calling a model."
          values={current.blacklist_companies}
          onChange={(blacklist_companies) => edit({ blacklist_companies })}
          placeholder="company name"
        />

        <ListEditor
          title="Blacklisted tax IDs"
          note="Checked independently of the company name, so a known-bad identifier cannot be laundered through a new trading name."
          values={current.blacklist_tax_ids}
          onChange={(blacklist_tax_ids) => edit({ blacklist_tax_ids })}
          placeholder="0123456789"
        />

        <div className="bento-card p-4">
          <h4 className="text-[12px] font-medium text-white">
            Low-value threshold
          </h4>
          <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
            Below this, a domestic shipment on a safe route can auto-clear with no
            model call. It also switches off the freight-ratio check, because a
            lane baseline is the wrong yardstick for a parcel.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <span className="text-[12px] text-faint">USD</span>
            <Input
              type="number"
              min={0}
              value={current.low_value_threshold_usd}
              onChange={(e) =>
                edit({ low_value_threshold_usd: Number(e.target.value) })
              }
              className="h-8 w-32 border-white/10 bg-black/30 text-[12.5px] tabular-nums"
            />
          </div>
        </div>

        <div className="bento-card p-4">
          <h4 className="text-[12px] font-medium text-white">VIP registry</h4>
          <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
            Matched on company <em>and</em> tax ID together. A half-right claim —
            the right name with the wrong number — is treated as worse than no
            match at all, because it means one of the two was deliberately reused.
          </p>
          <ul className="mt-2 space-y-1">
            {current.vip_registry.map((entry, i) => (
              <li
                key={`${entry.company}-${i}`}
                className="flex items-center gap-2 rounded border border-white/[0.06] px-2 py-1.5"
              >
                <span className="min-w-0 flex-1 truncate text-[11.5px] text-white/85">
                  {entry.company}
                </span>
                <span className="shrink-0 font-mono text-[11px] tabular-nums text-faint">
                  {entry.tax_id || "name only"}
                </span>
                <button
                  type="button"
                  aria-label={`Remove ${entry.company}`}
                  onClick={() =>
                    edit({
                      vip_registry: current.vip_registry.filter((_, j) => j !== i),
                    })
                  }
                  className="shrink-0 text-faint hover:text-risk-critical"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {error && (
        <p className="rounded-md border border-risk-critical/30 bg-risk-critical/[0.07] px-2.5 py-2 text-[11.5px] leading-relaxed text-risk-critical">
          {error}
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          disabled={!dirty || save.isPending}
          onClick={() => {
            if (!draft) return;
            // Only the keys that changed. The backend leaves an absent key as it
            // was, so sending the whole object would clobber a concurrent edit to
            // a list this screen did not touch.
            const patch: Partial<PrefilterRules> = {};
            const base = rules.data;
            if (draft.blacklist_companies !== base.blacklist_companies) {
              patch.blacklist_companies = draft.blacklist_companies;
            }
            if (draft.blacklist_tax_ids !== base.blacklist_tax_ids) {
              patch.blacklist_tax_ids = draft.blacklist_tax_ids;
            }
            if (draft.vip_registry !== base.vip_registry) {
              patch.vip_registry = draft.vip_registry;
            }
            if (draft.low_value_threshold_usd !== base.low_value_threshold_usd) {
              patch.low_value_threshold_usd = draft.low_value_threshold_usd;
            }
            save.mutate(patch);
          }}
          className="h-8 text-[12px]"
        >
          {save.isPending && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
          Save changes
        </Button>
        {dirty && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setDraft(null);
              setError(null);
            }}
            className="h-8 text-[12px] text-dim"
          >
            Discard
          </Button>
        )}
        <span className="ml-auto text-[11.5px] text-faint">
          {dirty ? "Unsaved changes" : "Saved"}
        </span>
      </div>
    </div>
  );
}

function ListEditor({
  title,
  note,
  values,
  onChange,
  placeholder,
}: {
  title: string;
  note: string;
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
}) {
  const [entry, setEntry] = useState("");

  function add() {
    const value = entry.trim();
    if (!value) return;
    // Duplicates are dropped rather than rejected: the backend normalises into a
    // set anyway, so refusing here would be a rule the server does not have.
    if (!values.includes(value)) onChange([...values, value]);
    setEntry("");
  }

  return (
    <div className="bento-card p-4">
      <h4 className="text-[12px] font-medium text-white">{title}</h4>
      <p className="mt-1 text-[11.5px] leading-relaxed text-dim">{note}</p>

      <div className="mt-2 flex gap-2">
        <Input
          value={entry}
          onChange={(e) => setEntry(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
          className="h-8 border-white/10 bg-black/30 text-[12.5px]"
        />
        <Button
          variant="outline"
          size="sm"
          onClick={add}
          className="h-8 shrink-0 border-white/10 px-2"
          aria-label={`Add to ${title}`}
        >
          <Plus className="size-3.5" />
        </Button>
      </div>

      <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto scrollbar-thin">
        {values.length === 0 ? (
          <li className="py-2 text-[11.5px] text-faint">Empty.</li>
        ) : (
          values.map((value) => (
            <li
              key={value}
              className="flex items-center gap-2 rounded border border-white/[0.06] px-2 py-1.5"
            >
              <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-white/85">
                {value}
              </span>
              <button
                type="button"
                aria-label={`Remove ${value}`}
                onClick={() => onChange(values.filter((v) => v !== value))}
                className="shrink-0 text-faint hover:text-risk-critical"
              >
                <Trash2 className="size-3.5" />
              </button>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}

// --------------------------------------------------------------------------
// Entity verification
// --------------------------------------------------------------------------

function VerifyTab() {
  const [type, setType] = useState<"company" | "tax_id">("company");
  const [value, setValue] = useState("");

  const verify = useMutation({
    mutationFn: () => verifyEntity({ type, value: value.trim() }),
  });

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="bento-card p-4">
        <h3 className="text-[12px] font-medium text-white">
          Does this counterparty exist?
        </h3>
        <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
          A live web search, run on demand. Useful before adding an entry to the
          VIP registry: a name that returns nothing is a name nobody should be
          fast-tracking.
        </p>

        <div className="mt-3 flex gap-2">
          <Button
            variant={type === "company" ? "default" : "outline"}
            size="sm"
            onClick={() => setType("company")}
            className="h-8 border-white/10 text-[12px]"
          >
            Company
          </Button>
          <Button
            variant={type === "tax_id" ? "default" : "outline"}
            size="sm"
            onClick={() => setType("tax_id")}
            className="h-8 border-white/10 text-[12px]"
          >
            Tax ID
          </Button>
        </div>

        <div className="mt-2 flex gap-2">
          <Input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && value.trim()) verify.mutate();
            }}
            placeholder={type === "company" ? "Company name" : "0123456789"}
            className="h-8 border-white/10 bg-black/30 text-[12.5px]"
          />
          <Button
            size="sm"
            disabled={!value.trim() || verify.isPending}
            onClick={() => verify.mutate()}
            className="h-8 shrink-0 text-[12px]"
          >
            {verify.isPending && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
            Search
          </Button>
        </div>
      </div>

      <div className="bento-card p-4">
        <h3 className="text-[12px] font-medium text-white">Result</h3>
        {verify.isError ? (
          <div className="mt-2">
            <ErrorState error={verify.error} />
          </div>
        ) : verify.data ? (
          <>
            <p
              className={cn(
                "mt-2 text-[12.5px]",
                verify.data.verified ? "text-risk-clear" : "text-risk-warn",
              )}
            >
              {verify.data.verified ? "Found" : "Not established"} ·{" "}
              {verify.data.confidence} confidence
            </p>
            <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
              {verify.data.summary}
            </p>
            <ul className="mt-2 space-y-1.5">
              {verify.data.results.map((r) => (
                <li key={r.url} className="rounded border border-white/[0.06] px-2 py-1.5">
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="flex items-center gap-1 text-[11.5px] text-brand hover:underline"
                  >
                    <ExternalLink className="size-3 shrink-0" aria-hidden />
                    <span className="truncate">{r.title}</span>
                  </a>
                  <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-faint">
                    {r.snippet}
                  </p>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="mt-2 text-[11.5px] text-faint">
            Nothing searched yet.
          </p>
        )}
      </div>
    </div>
  );
}
