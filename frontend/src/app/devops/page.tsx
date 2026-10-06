"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  FileUp,
  Loader2,
  Lock,
  Play,
  ShieldAlert,
  Trash2,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { Gated } from "@/components/layout/Gated";
import { PageHeading } from "@/components/layout/PageHeading";
import { ErrorState } from "@/components/layout/States";
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
import { useToast } from "@/components/ui/toaster";
import {
  fetchMetrics,
  injectBulk,
  injectScriptedBatch,
  queryKeys,
  resetBoard,
  submitShipmentEvent,
  uploadDocument,
  type UploadResult,
} from "@/lib/api";
import { HelpDot } from "@/components/help/HelpDot";
import { caseHref } from "@/lib/case-links";
import { caseStateLabel, lowerFirst } from "@/lib/format";
import { lockReason, passwordLockReason, useIdentity } from "@/lib/identity";
import { useTenant } from "@/lib/tenant-context";
import { cn } from "@/lib/utils";

export default function DevOpsPage() {
  const { tenant } = useTenant();
  const queryClient = useQueryClient();
  const identity = useIdentity().data;
  // Every panel here is an operator write upstream: each one creates cases and
  // spends tokens. Computed once and passed down, so the four cannot disagree.
  const lock = lockReason(identity, "operator");

  const refreshBoard = () => {
    queryClient.invalidateQueries({ queryKey: ["snapshot", tenant.id] });
    queryClient.invalidateQueries({ queryKey: queryKeys.reviewQueue(tenant.id) });
  };

  return (
    <>
      <PageHeading title="DevOps">
        Put work into the real pipeline. Everything here runs the same screening,
        governance gate and audit trail as a production shipment — there is no
        test path.
      </PageHeading>

      {lock && (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3">
          <Lock className="mt-[2px] size-4 shrink-0 text-dim" aria-hidden />
          <p className="text-[12px] leading-relaxed text-dim">
            Read-only for you. {lock} Every control on this page creates cases and
            spends model tokens, so the API reserves them for operators.
          </p>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <ScriptedBatch onDone={refreshBoard} lock={lock} />
        <BulkInject onDone={refreshBoard} lock={lock} />
        <DocumentUpload onDone={refreshBoard} lock={lock} />
        <CustomShipment onDone={refreshBoard} lock={lock} />
      </div>

      <ClearBoard
        // Everything on the board changes, so everything cached is stale.
        onDone={() => queryClient.invalidateQueries()}
        lock={lock ?? passwordLockReason(identity)}
        needsPassword={lock === null && passwordLockReason(identity) !== null}
      />
    </>
  );
}

function Panel({
  title,
  note,
  helpId,
  children,
}: {
  title: string;
  note: string;
  helpId?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bento-card p-4">
      <div className="flex items-center gap-1.5">
        <h3 className="text-[12px] font-medium text-white">{title}</h3>
        {helpId && <HelpDot id={helpId} />}
      </div>
      <p className="mt-1 text-[11.5px] leading-relaxed text-dim">{note}</p>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function Result({
  children,
  tone = "clear",
}: {
  children: React.ReactNode;
  /** "warn" for an outcome that is an answer, not a success: a blocked or unreadable upload. */
  tone?: "clear" | "warn";
}) {
  const warn = tone === "warn";
  const Icon = warn ? AlertTriangle : CheckCircle2;
  return (
    <div
      role="status"
      className={cn(
        "mt-3 flex items-start gap-2 rounded-md border px-2.5 py-2",
        warn
          ? "border-risk-warn/30 bg-risk-warn/[0.06]"
          : "border-risk-clear/25 bg-risk-clear/[0.06]",
      )}
    >
      <Icon
        className={cn("mt-[1px] size-3.5 shrink-0", warn ? "text-risk-warn" : "text-risk-clear")}
        aria-hidden
      />
      <div
        className={cn(
          "min-w-0 text-[11.5px] leading-relaxed",
          warn ? "text-risk-warn" : "text-risk-clear",
        )}
      >
        {children}
      </div>
    </div>
  );
}

/** "Open CASE-123", linking to the case trace on the board. */
function CaseLink({ caseId }: { caseId: string }) {
  return (
    <Link href={caseHref(caseId)} className="font-medium underline underline-offset-2 hover:text-white">
      {caseId}
    </Link>
  );
}

function ScriptedBatch({ onDone, lock }: { onDone: () => void; lock: string | null }) {
  const toast = useToast();
  const inject = useMutation({
    mutationFn: injectScriptedBatch,
    onSuccess: (data) => {
      onDone();
      toast({
        title: `Queued ${data.injected} case(s)`,
        description: "They advance in the background.",
        action: { label: "Watch them on the Pipeline board", href: "/" },
      });
    },
  });

  // The note below is kept honest against `simulator.scripted_shipments`, which returns
  // three cases: CLEAN, MID, DIRTY. It used to promise four branches that do not exist --
  // "a sanctions hit, an export-control name, an HS mismatch, a clean low-value domestic
  // parcel". There is no HS mismatch in the batch, and the clean case is an international
  // sailing worth USD 9,600, not a low-value domestic parcel. This is the panel a judge
  // clicks first, so it has to describe the cases that actually load. If you change the
  // batch, change this note in the same commit.
  return (
    <Panel
      helpId="devops.scripted-batch"
      title="Scripted batch"
      note="Three cases, one per outcome, fixed rather than random so two runs are comparable. A settled shipper on a direct sailing to Singapore, which should clear itself. Furniture to Busan with clean paperwork but freight under the route average from a shipper with nine prior shipments, which compliance clears and fraud still sends to a human. And frequency converters to Karachi declared as agricultural, from a company registered eleven days ago with no tax ID, at 14% of the route's normal freight, with two transhipments added after booking."
    >
      <Gated reason={lock}>
        <Button
          size="sm"
          disabled={inject.isPending || lock !== null}
          onClick={() => inject.mutate()}
          className="h-8 text-[12px]"
        >
          {inject.isPending ? (
            <Loader2 className="mr-1.5 size-3.5 animate-spin" />
          ) : (
            <Play className="mr-1.5 size-3.5" />
          )}
          Inject the batch
        </Button>
      </Gated>

      {inject.isError && (
        <div className="mt-3">
          <ErrorState error={inject.error} />
        </div>
      )}
      {inject.data && (
        <Result>
          Queued {inject.data.injected} case(s). They advance in the background —{" "}
          <Link href="/" className="font-medium underline underline-offset-2 hover:text-white">
            watch them cross the Pipeline board
          </Link>
          .
        </Result>
      )}
    </Panel>
  );
}

function BulkInject({ onDone, lock }: { onDone: () => void; lock: string | null }) {
  const [count, setCount] = useState(10);
  const [confirm, setConfirm] = useState(false);
  const toast = useToast();

  const bulk = useMutation({
    mutationFn: () => injectBulk(count),
    onSuccess: (data) => {
      onDone();
      toast({
        title: `Queued ${data.queued} case(s)`,
        description: data.note,
        action: { label: "Open the Pipeline board", href: "/" },
      });
    },
  });

  return (
    <Panel
      helpId="devops.bulk-load"
      title="Bulk load"
      note="Randomised shipments, for watching the board under load and for seeing what the cost per case actually is at volume. Every one that reaches an agent spends tokens."
    >
      <div className="flex items-end gap-2">
        <div>
          <Label htmlFor="bulk-count" className="text-[11.5px] text-dim">
            How many
          </Label>
          <Input
            id="bulk-count"
            type="number"
            min={1}
            max={100}
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(100, Number(e.target.value))))}
            className="mt-1 h-8 w-24 border-white/10 bg-black/30 text-[12.5px] tabular-nums"
          />
        </div>
        <Gated reason={lock}>
          <Button
            size="sm"
            disabled={bulk.isPending || lock !== null}
            onClick={() => setConfirm(true)}
            className="h-8 text-[12px]"
          >
            {bulk.isPending && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
            Queue them
          </Button>
        </Gated>
      </div>

      {bulk.isError && (
        <div className="mt-3">
          <ErrorState error={bulk.error} />
        </div>
      )}
      {bulk.data && (
        <Result>
          Queued {bulk.data.queued} case(s).
          {bulk.data.note && <span className="block text-faint">{bulk.data.note}</span>}
        </Result>
      )}

      {/* Confirmed because it costs money, and the amount scales with the number
          in the box next to the button. */}
      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent className="border-white/10 bg-slate-950">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px]">
              Queue {count} shipment{count === 1 ? "" : "s"}?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[12.5px] leading-relaxed text-dim">
              Each one that is not resolved by the deterministic pre-filter will
              call at least two models, and the spend is billed to this tenant.
              The pre-filter typically absorbs most of a random batch, but not all
              of it.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-white/10 text-[12.5px]">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="text-[12.5px]"
              onClick={() => {
                setConfirm(false);
                bulk.mutate();
              }}
            >
              Queue them
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Panel>
  );
}

/**
 * What the document route accepts, mirroring SUPPORTED_MIME in
 * agents/document_agent.py (pinned there by tests/test_document_upload.py).
 *
 * Duplicated rather than fetched from /api/v1/config, because the cost of drift
 * is small and bounded: `accept` is a filter, not a control -- drag-and-drop
 * ignores it and so does "All files" in the picker -- and the backend answers a
 * rejected type with its own authoritative list, which the error surfaces. A
 * stale entry here means one wasted round trip, not a wrong verdict.
 */
const ACCEPTED_EXTENSIONS = [".pdf", ".png", ".jpg", ".jpeg", ".webp"] as const;
const ACCEPTED_MIME = [
  "application/pdf",
  "image/png",
  "image/jpeg",
  "image/webp",
] as const;
const ACCEPTED_ATTR = [...ACCEPTED_EXTENSIONS, ...ACCEPTED_MIME].join(",");
const ACCEPTED_LABEL = "PDF, PNG, JPG or WebP";

// Matches MAX_DOCUMENT_MB, the backend's default. Shown so the 413 is something
// the user can avoid rather than only discover.
const MAX_DOCUMENT_MB = 20;

function DocumentUpload({ onDone, lock }: { onDone: () => void; lock: string | null }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const upload = useMutation({
    mutationFn: (file: File) => uploadDocument(file),
    onSuccess: (data) => {
      onDone();
      const outcome = uploadOutcome(data);
      toast({
        title: outcome.title,
        tone: outcome.tone === "warn" ? "warn" : "success",
        action: data.case_id ? { label: `Open ${data.case_id}`, href: caseHref(data.case_id) } : undefined,
      });
    },
  });

  function take(files: FileList | null) {
    // The drop zone stays visible when locked, so a dropped file must be refused
    // here as well as the picker being disabled.
    if (lock) return;
    const file = files?.[0];
    if (file) upload.mutate(file);
  }

  return (
    <Panel
      helpId="devops.upload"
      title="Upload a document"
      note="A real bill of lading or invoice. It goes through Model Armor and injection screening before any model reads it, then through extraction and the full workflow."
    >
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          take(e.dataTransfer.files);
        }}
        className={cn(
          "flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-6 text-center transition-colors",
          dragging
            ? "border-brand/60 bg-brand/[0.06]"
            : "border-white/15 bg-black/20",
        )}
      >
        <FileUp className="size-5 text-dim" aria-hidden />
        {lock ? (
          <p className="flex items-center gap-1.5 text-[12px] text-dim">
            <Lock className="size-3.5" aria-hidden />
            {lock}
          </p>
        ) : (
          <p className="text-[12px] text-dim">
            Drop a file here, or{" "}
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="text-brand hover:underline"
            >
              choose one
            </button>
          </p>
        )}
        <p className="text-[11px] text-dim/70">
          {ACCEPTED_LABEL}, up to {MAX_DOCUMENT_MB}&nbsp;MB. A PDF is read from
          its first page only.
        </p>
        <input
          ref={inputRef}
          type="file"
          className="sr-only"
          disabled={lock !== null}
          // Both extensions and MIME types: a file picker filters on one, a
          // drag source reports the other, and which you get varies by OS.
          accept={ACCEPTED_ATTR}
          onChange={(e) => take(e.target.files)}
        />
        {upload.isPending && (
          <p className="flex items-center gap-1.5 text-[11.5px] text-brand" role="status">
            <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />
            Screening, extracting and running the workflow. Usually 30–60 seconds —
            the case is created even if you leave this page.
          </p>
        )}
      </div>

      {upload.isError && (
        <div className="mt-3">
          <ErrorState error={upload.error} />
        </div>
      )}
      {upload.data != null && <UploadOutcome data={upload.data} />}
    </Panel>
  );
}

/**
 * The three things an upload can come back with, in words. See UploadResult.
 *
 * A blocked document is not a failure: it is the screening doing its job, and the
 * refusal is recorded as a case. It used to render in the same green box as a
 * clean result, saying "Created CASE-...", which hid the most interesting outcome
 * the panel has.
 */
function uploadOutcome(data: UploadResult): { title: string; tone: "clear" | "warn" } {
  if (!data.accepted) {
    return {
      title: `Could not read this document: ${String(data.error ?? data.reason ?? "no shipment found in it")}. Nothing was created.`,
      tone: "warn",
    };
  }
  if (data.blocked) {
    return {
      title: `Blocked at intake: ${data.case_id ?? "the case"} was stopped by Model Armor before any model read it. No tokens spent.`,
      tone: "warn",
    };
  }
  const state = data.state ? ` · now ${lowerFirst(caseStateLabel(String(data.state)))}` : "";
  return { title: `Created ${data.case_id ?? "a case"}${state}.`, tone: "clear" };
}

function UploadOutcome({ data }: { data: UploadResult }) {
  const outcome = uploadOutcome(data);
  return (
    <Result tone={outcome.tone}>
      {outcome.title}
      {data.case_id && (
        <>
          {" "}
          <CaseLink caseId={data.case_id} />
        </>
      )}
    </Result>
  );
}

/**
 * A hand-written shipment, submitted as Pub/Sub would.
 *
 * Posts to `events/shipment` rather than `simulate`: `simulate` ignores its body
 * entirely and injects the scripted batch, so a form that posted there would
 * silently discard everything typed into it and report success.
 */
function CustomShipment({ onDone, lock }: { onDone: () => void; lock: string | null }) {
  const [form, setForm] = useState({
    shipment_id: "",
    shipper_company: "",
    shipper_tax_id: "",
    origin: "",
    destination: "",
    goods_description: "",
    hs_code: "",
    declared_value: "",
    shipping_cost: "",
  });
  const toast = useToast();

  const submit = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(form)) {
        const trimmed = value.trim();
        if (!trimmed) continue;
        // Numbers sent as numbers. A declared value arriving as the string
        // "50000" fails the schema's type check, and the resulting finding reads
        // as a data-quality problem with the shipment rather than with this form.
        payload[key] =
          key === "declared_value" || key === "shipping_cost"
            ? Number(trimmed)
            : trimmed;
      }
      return submitShipmentEvent(payload);
    },
    onSuccess: (data) => {
      onDone();
      const caseId = data.case_id ? String(data.case_id) : null;
      toast({
        title: `Created ${caseId ?? "a case"}`,
        action: caseId ? { label: `Open ${caseId}`, href: caseHref(caseId) } : undefined,
      });
    },
  });

  const fields: Array<[keyof typeof form, string, string]> = [
    ["shipment_id", "Shipment id", "leave blank to generate one"],
    ["shipper_company", "Shipper", "Acme Trading Ltd"],
    ["shipper_tax_id", "Tax ID", "0301234567"],
    ["origin", "Origin", "ho chi minh city"],
    ["destination", "Destination", "hanoi"],
    ["goods_description", "Goods", "cotton shirts"],
    ["hs_code", "HS code", "6205.20"],
    ["declared_value", "Declared value (USD)", "50000"],
    ["shipping_cost", "Freight (USD)", "1500"],
  ];

  return (
    <Panel
      helpId="devops.submit"
      title="Submit one by hand"
      note="Useful for reproducing a specific finding: an unknown counterparty, a dual-use HS prefix, a freight charge far below the lane baseline. Blank fields are omitted rather than sent empty, because an absent field and an empty one produce different findings."
    >
      <div className="grid gap-2 sm:grid-cols-2">
        {fields.map(([key, label, placeholder]) => (
          <div key={key}>
            <Label htmlFor={`f-${key}`} className="text-[11px] text-dim">
              {label}
            </Label>
            <Input
              id={`f-${key}`}
              value={form[key]}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              placeholder={placeholder}
              className="mt-1 h-8 border-white/10 bg-black/30 text-[12px]"
            />
          </div>
        ))}
      </div>

      <Gated reason={lock}>
        <Button
          size="sm"
          disabled={submit.isPending || lock !== null}
          onClick={() => submit.mutate()}
          className="mt-3 h-8 text-[12px]"
        >
          {submit.isPending ? (
            <Loader2 className="mr-1.5 size-3.5 animate-spin" />
          ) : (
            <Upload className="mr-1.5 size-3.5" />
          )}
          Submit
        </Button>
      </Gated>

      {submit.isError && (
        <div className="mt-3">
          <ErrorState error={submit.error} />
        </div>
      )}
      {submit.data != null && (
        <Result>
          Created{" "}
          {submit.data.case_id ? <CaseLink caseId={String(submit.data.case_id)} /> : "a case"}
          {submit.data.state
            ? ` · now ${lowerFirst(caseStateLabel(String(submit.data.state)))}`
            : ""}.
        </Result>
      )}
    </Panel>
  );
}

/**
 * Clear board: delete every case and event on this tenant, so a demo starts clean.
 *
 * Back after being left out of this console on purpose, because it now has the
 * two things it lacked. It cannot destroy the record: the audit trail is
 * append-only and survives a reset, which is itself written to the trail under
 * the person who did it. And the public judge button cannot reach it: it needs a
 * PASSWORD sign-in on top of the operator role, enforced by the BFF and again by
 * the API (auth.require_password_session). A one-click session sees the button
 * locked, with the reason and the way to unlock it.
 */
function ClearBoard({
  onDone,
  lock,
  needsPassword,
}: {
  onDone: () => void;
  lock: string | null;
  /** The role is fine and only the sign-in method is missing: offer the password sign-in. */
  needsPassword: boolean;
}) {
  const { tenant } = useTenant();
  const [confirm, setConfirm] = useState(false);
  const toast = useToast();

  // Counted when the dialog opens, so the question names what it will delete.
  const metrics = useQuery({
    queryKey: queryKeys.metrics(tenant.id),
    queryFn: fetchMetrics,
    enabled: confirm,
    staleTime: 0,
  });
  const total = metrics.data
    ? Object.values(metrics.data.counts ?? {}).reduce((sum, n) => sum + (n ?? 0), 0)
    : null;

  const reset = useMutation({
    mutationFn: resetBoard,
    onSuccess: (data) => {
      onDone();
      toast({
        title: `Cleared ${data.cleared} case(s) from the board`,
        description: "The audit trail is kept, and this reset is recorded in it under your name.",
        action: { label: "Open the audit trail", href: "/audit" },
      });
    },
  });

  return (
    <div className="mt-4 rounded-xl border border-risk-critical/25 bg-risk-critical/[0.03] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-2xl">
          <h3 className="flex items-center gap-1.5 text-[12px] font-medium text-white">
            <ShieldAlert className="size-3.5 text-risk-critical" aria-hidden />
            Clear the board
          </h3>
          <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
            Deletes every case and event on this tenant so a demo starts clean. The
            audit trail is not deleted, and the reset is written to it under your
            name. Needs the Operator role and a password sign-in: the one-click judge
            session can do everything else, but not this.
          </p>
          {lock && (
            <p className="mt-2 flex items-start gap-1.5 text-[11.5px] text-dim">
              <Lock className="mt-[2px] size-3.5 shrink-0" aria-hidden />
              <span>
                {lock}{" "}
                {needsPassword && (
                  <a href="/login?next=/devops" className="text-brand hover:underline">
                    Sign in with a password
                  </a>
                )}
              </span>
            </p>
          )}
        </div>
        <Gated reason={lock}>
          <Button
            size="sm"
            variant="destructive"
            disabled={reset.isPending || lock !== null}
            onClick={() => setConfirm(true)}
            className="h-8 text-[12px]"
          >
            {reset.isPending ? (
              <Loader2 className="mr-1.5 size-3.5 animate-spin motion-reduce:animate-none" />
            ) : (
              <Trash2 className="mr-1.5 size-3.5" />
            )}
            Clear board
          </Button>
        </Gated>
      </div>

      {reset.isError && (
        <div className="mt-3">
          <ErrorState error={reset.error} />
        </div>
      )}

      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent className="border-white/10 bg-slate-950">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px]">
              {total === null
                ? "Clear every case on the board?"
                : `Clear ${total} case${total === 1 ? "" : "s"} from the board?`}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[12.5px] leading-relaxed text-dim">
              Cases and their events are deleted for everyone using this tenant, and
              there is no undo. The audit trail stays, and records that you cleared
              the board.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-white/10 text-[12.5px]">Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-[12.5px] text-white hover:bg-destructive/90"
              onClick={() => {
                setConfirm(false);
                reset.mutate();
              }}
            >
              Clear board
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
