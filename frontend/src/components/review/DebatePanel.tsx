"use client";

import { ChevronDown, Gavel, Search, Sparkles, TrendingUp } from "lucide-react";
import { useState } from "react";

import type { DebateEffect } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The Senior Auditor's debate, readable.
 *
 * Replaces a `JSON.stringify` dump that was the only rendering of the one hop that
 * runs Nemotron Ultra -- CONFIRM and DISAGREE appeared nowhere else on screen. The
 * raw record is still here, collapsed: this panel is a reading of it, not a
 * replacement, and on a screen whose purpose is that a person can check the
 * machine the artefact has to stay one click away.
 *
 * Extraction is defensive rather than typed. `debate` is `Record<string, unknown>`
 * on the wire, the verdict has lived at two depths across versions (`verdict` and
 * `result.verdict`), and anything unrecognised renders as absent rather than as a
 * guess. A panel that invented a verdict would be worse than none.
 *
 * `effect` is what the verdict CHANGED (orchestrator._apply_debate_verdict), and
 * it is shown first because it is the new part: a confident, genuine DISAGREE
 * sends the case to deep investigation, and nothing else the debate says can move
 * a case at all.
 */

interface Verdict {
  verdict: "CONFIRM" | "DISAGREE";
  confidence: number | null;
  rationale: string | null;
  recommended: string | null;
  adjusted: number | null;
  forced: boolean;
  forcedReason: string | null;
}

interface TraceRow {
  round: number | null;
  label: string;
  detail: string | null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function readVerdict(debate: Record<string, unknown>): Verdict | null {
  const candidates = [debate.verdict, asRecord(debate.result)?.verdict];
  for (const candidate of candidates) {
    const v = asRecord(candidate);
    const name = v?.verdict;
    if (v && (name === "CONFIRM" || name === "DISAGREE")) {
      return {
        verdict: name,
        confidence: num(v.confidence),
        rationale: typeof v.rationale === "string" ? v.rationale : null,
        recommended: typeof v.recommended_action === "string" ? v.recommended_action : null,
        adjusted: num(v.adjusted_risk_score),
        forced: v.forced === true,
        forcedReason: typeof v.forced_reason === "string" ? v.forced_reason : null,
      };
    }
  }
  return null;
}

const FORCED_REASON: Record<string, string> = {
  no_tool_call: "the model answered without using its tools",
  rounds_exhausted: "the model used every round without rendering a verdict",
  unparseable_verdict: "the model's verdict could not be read",
};

function readTrace(debate: Record<string, unknown>): TraceRow[] {
  const raw = debate.debate_trace ?? asRecord(debate.result)?.debate_trace;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry): TraceRow[] => {
    const e = asRecord(entry);
    if (!e) return [];
    const round = num(e.round);
    const args = asRecord(e.arguments);
    switch (e.tool ?? e.type) {
      case "search_tavily":
        return [{ round, label: "Searched the web", detail: typeof args?.query === "string" ? args.query : null }];
      case "request_nano_reevaluation": {
        const focus = Array.isArray(args?.focus_areas) ? args.focus_areas.join(", ") : null;
        return [{ round, label: "Asked the junior analyst to look again", detail: focus }];
      }
      case "render_final_verdict":
        return [{ round, label: "Rendered the verdict", detail: e.arguments_unparseable ? "arguments were not valid JSON" : null }];
      case "no_tool_call":
        return [{ round, label: "Answered without using a tool", detail: null }];
      case "forced_verdict":
        return [{ round, label: "Verdict filled in by the system", detail: null }];
      default:
        return [{ round, label: String(e.tool ?? e.type ?? "step"), detail: null }];
    }
  });
}

export function DebatePanel({
  debate,
  effect,
  automatic,
}: {
  debate: Record<string, unknown>;
  effect?: DebateEffect | null;
  automatic: boolean;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const verdict = readVerdict(debate);
  const trace = readTrace(debate);
  const disagreed = verdict?.verdict === "DISAGREE";

  return (
    <div className="bento-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Gavel className="size-3.5 text-brand" aria-hidden />
        <h3 className="text-[12px] font-medium text-white">Senior auditor debate</h3>
        {verdict && (
          <span
            className={cn(
              "rounded border px-1.5 py-0.5 font-mono text-[10.5px] uppercase tracking-wide",
              disagreed
                ? "border-risk-critical/40 bg-risk-critical/[0.12] text-risk-critical"
                : "border-risk-clear/40 bg-risk-clear/[0.12] text-risk-clear",
            )}
            title={
              disagreed
                ? "The Senior Auditor found something the Junior Analyst missed."
                : "The Senior Auditor agreed with the Junior Analyst's assessment."
            }
          >
            {verdict.verdict}
          </span>
        )}
        {verdict?.confidence != null && (
          <span className="font-mono text-[10.5px] tabular-nums text-dim">
            {Math.round(verdict.confidence * 100)}% confident
          </span>
        )}
        <span className="text-[10.5px] uppercase tracking-wide text-faint">
          {automatic ? "fired automatically" : "requested by a reviewer"}
        </span>
      </div>

      {effect && (
        <div
          className={cn(
            "mt-3 flex items-start gap-2 rounded-md border px-2.5 py-2",
            effect.escalated
              ? "border-risk-critical/30 bg-risk-critical/[0.07]"
              : "border-white/[0.07] bg-black/25",
          )}
        >
          <TrendingUp
            className={cn("mt-[2px] size-3.5 shrink-0", effect.escalated ? "text-risk-critical" : "text-faint")}
            aria-hidden
          />
          <p className="text-[11.5px] leading-relaxed text-dim">
            {effect.escalated ? (
              <>
                <span className="font-medium text-risk-critical">Escalated this case</span> to
                deep investigation
                {effect.risk_after > effect.risk_before &&
                  `, and raised its risk ${effect.risk_before} → ${effect.risk_after}`}
                . {effect.reason}.
              </>
            ) : (
              <>
                <span className="font-medium text-white/85">Changed nothing</span>: {effect.reason}.
                The debate can only escalate, on a genuine DISAGREE at{" "}
                {Math.round(effect.threshold * 100)}% confidence or more.
              </>
            )}
          </p>
        </div>
      )}

      {verdict?.forced && (
        <p className="mt-2 text-[11.5px] leading-relaxed text-risk-warn">
          This is a default, not a judgement:{" "}
          {FORCED_REASON[verdict.forcedReason ?? ""] ?? "no usable verdict was rendered"}.
        </p>
      )}

      {verdict?.rationale && (
        <blockquote className="mt-3 border-l-2 border-white/10 pl-3 text-[12px] leading-relaxed text-white/85">
          {verdict.rationale}
        </blockquote>
      )}

      {(verdict?.recommended || verdict?.adjusted != null) && (
        <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px]">
          {verdict?.recommended && (
            <div className="flex gap-1.5">
              <dt className="text-faint">recommends</dt>
              <dd className="text-white/85">{verdict.recommended}</dd>
            </div>
          )}
          {verdict?.adjusted != null && (
            <div className="flex gap-1.5">
              <dt className="text-faint">auditor&rsquo;s score</dt>
              <dd className="font-mono tabular-nums text-white/85">{Math.round(verdict.adjusted)}</dd>
            </div>
          )}
        </dl>
      )}

      {trace.length > 0 && (
        <ol className="mt-3 space-y-1">
          {trace.map((row, i) => (
            <li key={i} className="flex items-start gap-2 text-[11.5px]">
              <span className="mt-[1px] w-12 shrink-0 font-mono text-[10.5px] text-faint">
                {row.round != null ? `round ${row.round}` : ""}
              </span>
              {row.label.startsWith("Searched") ? (
                <Search className="mt-[2px] size-3 shrink-0 text-dim" aria-hidden />
              ) : (
                <Sparkles className="mt-[2px] size-3 shrink-0 text-dim" aria-hidden />
              )}
              <span className="min-w-0 text-dim">
                {row.label}
                {row.detail && <span className="text-white/75">: {row.detail}</span>}
              </span>
            </li>
          ))}
        </ol>
      )}

      {!verdict && (
        <p className="mt-2 text-[11.5px] text-faint">
          No verdict in a recognised shape. The raw record is below.
        </p>
      )}

      <button
        type="button"
        onClick={() => setShowRaw(!showRaw)}
        aria-expanded={showRaw}
        className="mt-3 inline-flex items-center gap-1 text-[11px] text-faint hover:text-white"
      >
        <ChevronDown className={cn("size-3 transition-transform", showRaw && "rotate-180")} aria-hidden />
        {showRaw ? "Hide the raw debate record" : "Show the raw debate record"}
      </button>
      {showRaw && (
        <pre className="code-surface mt-2 max-h-64 overflow-auto whitespace-pre-wrap px-2.5 py-2 text-[11px] text-white/80 scrollbar-thin">
          {JSON.stringify(debate, null, 2)}
        </pre>
      )}
    </div>
  );
}
