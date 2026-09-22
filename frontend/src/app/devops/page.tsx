"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileUp, Loader2, Play, Upload } from "lucide-react";
import { useRef, useState } from "react";

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
import {
  injectBulk,
  injectScriptedBatch,
  queryKeys,
  submitShipmentEvent,
  uploadDocument,
} from "@/lib/api";
import { HelpDot } from "@/components/help/HelpDot";
import { caseStateLabel, lowerFirst } from "@/lib/format";
import { useTenant } from "@/lib/tenant-context";
import { cn } from "@/lib/utils";

export default function DevOpsPage() {
  const { tenant } = useTenant();
  const queryClient = useQueryClient();

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

      {/*
        No "Clear board" control, unlike the old dashboard.

        POST /api/v1/orchestrator/reset deletes every case, event and audit record
        for the tenant with no undo. It exists so a demo can be reset from a
        terminal; a button for it on a page a customer can open is a button that
        eventually gets clicked, and the audit trail it destroys is the artefact
        this whole system exists to produce. It is also not proxied, so this
        console could not call it even if a button were added.
      */}

      <div className="grid gap-4 lg:grid-cols-2">
        <ScriptedBatch onDone={refreshBoard} />
        <BulkInject onDone={refreshBoard} />
        <DocumentUpload onDone={refreshBoard} />
        <CustomShipment onDone={refreshBoard} />
      </div>
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

function Result({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-3 flex items-start gap-2 rounded-md border border-risk-clear/25 bg-risk-clear/[0.06] px-2.5 py-2">
      <CheckCircle2 className="mt-[1px] size-3.5 shrink-0 text-risk-clear" aria-hidden />
      <div className="min-w-0 text-[11.5px] leading-relaxed text-risk-clear">
        {children}
      </div>
    </div>
  );
}

function ScriptedBatch({ onDone }: { onDone: () => void }) {
  const inject = useMutation({
    mutationFn: injectScriptedBatch,
    onSuccess: onDone,
  });

  return (
    <Panel
      helpId="devops.scripted-batch"
      title="Scripted batch"
      note="The rehearsed set that exercises each verifier branch: a sanctions hit, an export-control name, an HS mismatch, a clean low-value domestic parcel. Fixed rather than random, so two runs are comparable."
    >
      <Button
        size="sm"
        disabled={inject.isPending}
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

      {inject.isError && (
        <div className="mt-3">
          <ErrorState error={inject.error} />
        </div>
      )}
      {inject.data && (
        <Result>
          Queued {inject.data.injected} case(s). They advance in the background —
          watch them cross the Pipeline board.
        </Result>
      )}
    </Panel>
  );
}

function BulkInject({ onDone }: { onDone: () => void }) {
  const [count, setCount] = useState(10);
  const [confirm, setConfirm] = useState(false);

  const bulk = useMutation({
    mutationFn: () => injectBulk(count),
    onSuccess: onDone,
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
        <Button
          size="sm"
          disabled={bulk.isPending}
          onClick={() => setConfirm(true)}
          className="h-8 text-[12px]"
        >
          {bulk.isPending && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
          Queue them
        </Button>
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

function DocumentUpload({ onDone }: { onDone: () => void }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: (file: File) => uploadDocument(file),
    onSuccess: onDone,
  });

  function take(files: FileList | null) {
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
        <p className="text-[11px] text-dim/70">
          {ACCEPTED_LABEL}, up to {MAX_DOCUMENT_MB}&nbsp;MB. A PDF is read from
          its first page only.
        </p>
        <input
          ref={inputRef}
          type="file"
          className="sr-only"
          // Both extensions and MIME types: a file picker filters on one, a
          // drag source reports the other, and which you get varies by OS.
          accept={ACCEPTED_ATTR}
          onChange={(e) => take(e.target.files)}
        />
        {upload.isPending && (
          <p className="flex items-center gap-1.5 text-[11.5px] text-brand">
            <Loader2 className="size-3.5 animate-spin" />
            Screening, extracting and running the workflow. This takes longer than
            a read.
          </p>
        )}
      </div>

      {upload.isError && (
        <div className="mt-3">
          <ErrorState error={upload.error} />
        </div>
      )}
      {upload.data != null && (
        <Result>
          {upload.data.accepted === false ? (
            <>
              Refused:{" "}
              {String(upload.data.reason ?? upload.data.error ?? "see the case trace")}.
              A refusal is recorded as a case, not discarded.
            </>
          ) : (
            <>
              Created {String(upload.data.case_id ?? "a case")}
              {upload.data.state
                ? ` · now ${lowerFirst(caseStateLabel(String(upload.data.state)))}`
                : ""}.
            </>
          )}
        </Result>
      )}
    </Panel>
  );
}

/**
 * A hand-written shipment, submitted as Pub/Sub would.
 *
 * Posts to `events/shipment` rather than `simulate`: `simulate` ignores its body
 * entirely and injects the scripted batch, so a form that posted there would
 * silently discard everything typed into it and report success.
 */
function CustomShipment({ onDone }: { onDone: () => void }) {
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
    onSuccess: onDone,
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

      <Button
        size="sm"
        disabled={submit.isPending}
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

      {submit.isError && (
        <div className="mt-3">
          <ErrorState error={submit.error} />
        </div>
      )}
      {submit.data != null && (
        <Result>
          Created {String(submit.data.case_id ?? "a case")}
          {submit.data.state
            ? ` · now ${lowerFirst(caseStateLabel(String(submit.data.state)))}`
            : ""}.
        </Result>
      )}
    </Panel>
  );
}
