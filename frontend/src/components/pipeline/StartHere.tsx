"use client";

import { ArrowRight, Loader2, MousePointerClick, X } from "lucide-react";
import Link from "next/link";
import { useState, useSyncExternalStore } from "react";

import { signInAsGuestJudge, useConsolePosture } from "@/lib/console-posture";
import { setHelpMode, useHelpMode } from "@/lib/help-mode";

/**
 * The three-step path through the product, for someone seeing it for the first
 * time -- usually a judge with a few minutes.
 *
 * Every screen is detailed and the sidebar has ten entries, and nothing said
 * where to begin. This strip does, once: it is dismissible, and the dismissal is
 * remembered in the same small external-store shape as help mode (see
 * lib/help-mode.ts for why it is not useState plus an effect).
 *
 * Shown to a signed-out visitor with the one-click button when it is switched
 * on, because signing in is the step that unlocks the other two.
 */

const STORAGE_KEY = "vf.console.start-here.dismissed";

let dismissedCache: boolean | null = null;
const listeners = new Set<() => void>();

function getSnapshot(): boolean {
  if (dismissedCache === null) {
    dismissedCache =
      typeof window !== "undefined" && window.localStorage.getItem(STORAGE_KEY) === "1";
  }
  return dismissedCache;
}

// Dismissed on the server, so the strip appears on hydration rather than
// flashing for a returning visitor who already closed it.
function getServerSnapshot(): boolean {
  return true;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function dismiss(): void {
  dismissedCache = true;
  window.localStorage.setItem(STORAGE_KEY, "1");
  for (const listener of listeners) listener();
}

const STEPS: Array<{ title: string; body: string; href: string; cta: string }> = [
  {
    title: "Put work in",
    body: "DevOps \u2192 Inject the batch: three shipments, one per outcome. Or upload a bill of lading.",
    href: "/devops",
    cta: "Open DevOps",
  },
  {
    title: "Decide what the agent would not",
    body: "Review Queue: the findings, the paperwork, and Release, Block or Request info under your name.",
    href: "/review",
    cta: "Open the queue",
  },
  {
    title: "See it on the record",
    body: "Audit Trail: every action, who took it, and every action the boundary refused.",
    href: "/audit",
    cta: "Open the trail",
  },
];

export function StartHere() {
  const dismissed = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const posture = useConsolePosture().data;
  const [helpOn] = useHelpMode();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (dismissed) return null;

  const signedOut = posture ? posture.auth.session === null : false;
  const offerOneClick = signedOut && posture?.auth.one_click_judge === true;

  async function oneClick() {
    setBusy(true);
    setError(null);
    const message = await signInAsGuestJudge("/");
    // Only reached on failure; success navigates away.
    setError(message || null);
    setBusy(false);
  }

  return (
    <section
      aria-labelledby="start-here-title"
      className="relative mb-4 rounded-xl border border-brand/20 bg-brand/[0.04] p-4"
    >
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss the getting-started guide"
        className="absolute right-2.5 top-2.5 rounded p-1 text-dim transition-colors hover:text-white focus-visible:outline-2 focus-visible:outline-brand"
      >
        <X className="size-3.5" aria-hidden />
      </button>

      <h2 id="start-here-title" className="text-[13px] font-medium text-white">
        Start here
      </h2>
      <p className="mt-0.5 max-w-3xl text-[11.5px] leading-relaxed text-dim">
        Floorline&rsquo;s agents run on NVIDIA Nemotron 3 via Nebius Token Factory and
        screen each shipment for fraud, sanctions and misdeclared goods. Rules set a risk
        floor they may raise but never lower. They act only inside a boundary a person
        published, and stop for a person on anything else. Three steps show the whole
        loop.
      </p>

      {offerOneClick && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={oneClick}
            disabled={busy}
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-brand px-3 text-[12px] font-medium text-brand-ink transition-colors hover:bg-brand-dim disabled:opacity-60"
          >
            {busy ? (
              <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
            ) : (
              <MousePointerClick className="size-3.5" aria-hidden />
            )}
            Continue as guest judge
          </button>
          <span className="text-[11px] text-dim">
            One click, no password. Everything except clearing the board.
          </span>
          {error && (
            <span role="alert" className="text-[11px] text-risk-critical">
              {error}
            </span>
          )}
        </div>
      )}

      <ol className="mt-3 grid gap-2 md:grid-cols-3">
        {STEPS.map((step, i) => (
          <li key={step.href} className="rounded-lg border border-white/[0.07] bg-black/25 p-3">
            <p className="text-[11px] text-faint">Step {i + 1}</p>
            <p className="mt-0.5 text-[12px] font-medium text-white">{step.title}</p>
            <p className="mt-1 text-[11.5px] leading-relaxed text-dim">{step.body}</p>
            <Link
              href={step.href}
              className="mt-2 inline-flex items-center gap-1 text-[11.5px] text-brand hover:underline"
            >
              {step.cta}
              <ArrowRight className="size-3" aria-hidden />
            </Link>
          </li>
        ))}
      </ol>

      {!helpOn && (
        <p className="mt-3 text-[11px] text-dim">
          New to a screen?{" "}
          <button
            type="button"
            onClick={() => setHelpMode(true)}
            className="text-brand hover:underline"
          >
            Turn on help
          </button>{" "}
          for a question mark beside every number and control.
        </p>
      )}
    </section>
  );
}
