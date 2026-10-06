"use client";

import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * A small notification stack, for saying that an action worked.
 *
 * WHY IT EXISTS. Several of the actions a judge is invited to try -- record a
 * decision, publish a boundary, upload a document -- succeeded silently: the case
 * dropped out of a list, a panel refreshed, and nothing said "done". A visitor
 * cannot tell that from "nothing happened".
 *
 * Built here rather than pulled in as a dependency: it is forty lines, and the
 * console already avoids adding packages it can do without. The stack is one
 * polite live region, so a screen reader announces each message once, without
 * interrupting.
 */

type Tone = "success" | "warn";

export interface ToastInput {
  title: string;
  description?: string;
  tone?: Tone;
  /** An in-app link, e.g. to the case that was just created. */
  action?: { label: string; href: string };
}

type Toast = ToastInput & { id: number };

const ToastContext = createContext<((toast: ToastInput) => void) | null>(null);

/** Six seconds: long enough to read two lines, short enough not to pile up. */
const DISMISS_AFTER_MS = 6_000;

function noop() {}

/** Push a notification. Outside the provider (a unit test) it does nothing. */
export function useToast(): (toast: ToastInput) => void {
  return useContext(ToastContext) ?? noop;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((all) => all.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback((input: ToastInput) => {
    const id = nextId.current++;
    // At most three on screen; the oldest goes first.
    setToasts((all) => [...all.slice(-2), { ...input, id }]);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        aria-label="Notifications"
        className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[22rem] max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(toast.id), DISMISS_AFTER_MS);
    return () => clearTimeout(timer);
  }, [toast.id, onDismiss]);

  const warn = toast.tone === "warn";
  const Icon = warn ? AlertTriangle : CheckCircle2;

  return (
    <div
      role="status"
      className={cn(
        "pointer-events-auto flex items-start gap-2.5 rounded-lg border bg-slate-950/95 px-3 py-2.5 shadow-bento backdrop-blur",
        warn ? "border-risk-warn/35" : "border-risk-clear/30",
      )}
    >
      <Icon
        className={cn("mt-[2px] size-4 shrink-0", warn ? "text-risk-warn" : "text-risk-clear")}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p className="text-[12.5px] font-medium text-white">{toast.title}</p>
        {toast.description && (
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-dim">{toast.description}</p>
        )}
        {toast.action && (
          <Link
            href={toast.action.href}
            className="mt-1 inline-block text-[11.5px] text-brand hover:underline"
          >
            {toast.action.label}
          </Link>
        )}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss notification"
        className="rounded p-0.5 text-dim transition-colors hover:text-white focus-visible:outline-2 focus-visible:outline-brand"
      >
        <X className="size-3.5" aria-hidden />
      </button>
    </div>
  );
}
