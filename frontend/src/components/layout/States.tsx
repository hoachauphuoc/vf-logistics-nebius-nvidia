"use client";

import { AlertTriangle, Inbox, PlugZap, ServerCog } from "lucide-react";

import { ApiError, DemoModeUnavailable } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * How a screen reports that it has nothing to show, and why.
 *
 * Deliberately four distinct states rather than one empty message. "The API is
 * unreachable", "this needs the live API", "you are not permitted to see this"
 * and "there is genuinely nothing here" lead an operator to four different
 * actions, and a single grey "No data" collapses all four into the one that is
 * least likely to be true.
 */

export function ErrorState({
  error,
  className,
}: {
  error: unknown;
  className?: string;
}) {
  const api = error instanceof ApiError ? error : null;

  if (error instanceof DemoModeUnavailable) {
    return (
      <Shell className={className} tone="neutral" icon={PlugZap} title="Needs the live API">
        <p>
          This screen reads the operational pipeline, which has no demo fixture.
          Inventing one would mean rendering a pipeline, a delegation boundary or
          an audit trail that never existed — the same liability the demo pill
          exists to prevent.
        </p>
        <p className="mt-2 font-mono text-[11px] text-faint">
          NEXT_PUBLIC_DEMO_MODE=false, with FLASK_API_BASE pointing at a running
          API. Note this is inlined at build time, so it needs a rebuild rather
          than an env-var update.
        </p>
      </Shell>
    );
  }

  if (api?.kind === "unreachable") {
    return (
      <Shell
        className={className}
        tone="critical"
        icon={ServerCog}
        title="The audit API is unreachable"
      >
        <p>
          Nothing below is stale — it is absent. An empty table here would read
          as “no findings”, which is the opposite of what is true.
        </p>
        <p className="mt-2 font-mono text-[11px] text-faint">{api.message}</p>
      </Shell>
    );
  }

  if (api?.status === 401 || api?.status === 403) {
    return (
      <Shell
        className={className}
        tone="warn"
        icon={AlertTriangle}
        title="Your role does not include this view"
      >
        <p>
          The API refused the read rather than returning a filtered version of
          it. Ask an operator to grant the role this section needs.
        </p>
        <p className="mt-2 font-mono text-[11px] text-faint">{api.message}</p>
      </Shell>
    );
  }

  return (
    <Shell
      className={className}
      tone="critical"
      icon={AlertTriangle}
      title="That request failed"
    >
      <p className="font-mono text-[11px] text-faint">
        {error instanceof Error ? error.message : String(error)}
      </p>
    </Shell>
  );
}

export function EmptyState({
  title,
  children,
  className,
}: {
  title: string;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <Shell className={className} tone="neutral" icon={Inbox} title={title}>
      {children}
    </Shell>
  );
}

function Shell({
  icon: Icon,
  title,
  children,
  tone,
  className,
}: {
  icon: React.ElementType;
  title: string;
  children?: React.ReactNode;
  tone: "critical" | "warn" | "neutral";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "bento-card flex flex-col items-center px-6 py-10 text-center",
        className,
      )}
    >
      <span
        className={cn(
          "mb-3 grid size-9 place-items-center rounded-xl ring-1",
          tone === "critical" && "bg-risk-critical/10 text-risk-critical ring-risk-critical/30",
          tone === "warn" && "bg-risk-warn/10 text-risk-warn ring-risk-warn/30",
          tone === "neutral" && "bg-white/[0.05] text-dim ring-white/10",
        )}
      >
        <Icon className="size-4" aria-hidden />
      </span>
      <h3 className="text-[14px] font-medium text-white">{title}</h3>
      <div className="mt-1.5 max-w-lg text-[12.5px] leading-relaxed text-dim">
        {children}
      </div>
    </div>
  );
}
