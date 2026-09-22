"use client";

import { Loader2, ShieldCheck } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * The console's sign-in screen.
 *
 * Renders outside the app shell -- AppShell short-circuits on this path -- because
 * a sidebar full of links that all bounce back here is worse than no sidebar.
 */
export default function LoginPage() {
  return (
    // useSearchParams needs a Suspense boundary to prerender. Without one the
    // build fails rather than degrading, so the fallback is the page's own frame
    // with the form omitted.
    <Suspense fallback={<Frame />}>
      <Frame>
        <LoginForm />
      </Frame>
    </Suspense>
  );
}

function Frame({ children }: { children?: React.ReactNode }) {
  return (
    <div className="flex min-h-svh items-center justify-center px-4 py-12">
      <div className="bento-card w-full max-w-sm p-7">
        <div className="flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-lg bg-indigo-500/10 text-indigo-300">
            <ShieldCheck className="size-4" />
          </span>
          <div className="min-w-0">
            <h1 className="truncate text-[15px] font-semibold tracking-display text-white">
              Trade Compliance Auditor
            </h1>
            <p className="truncate text-[11px] text-faint">
              Sign in to continue
            </p>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}

function LoginForm() {
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /**
   * Where to land after signing in.
   *
   * Only a same-site absolute path is honoured. An attacker-supplied `next` of
   * `https://elsewhere/` would otherwise turn this form into an open redirect
   * that looks like it belongs to us -- and `//elsewhere` is protocol-relative,
   * so checking for a leading `/` alone is not enough.
   */
  const next = (() => {
    const raw = params.get("next");
    if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return "/";
    return raw;
  })();

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as {
          error?: string;
        };
        setError(body.error ?? "Sign-in failed.");
        setBusy(false);
        return;
      }

      // A full navigation rather than router.push: the cookie was just set, and
      // every screen behind this one reads server state that depends on it. A
      // client transition would reuse the React tree that was rendered while
      // signed out.
      window.location.assign(next);
    } catch {
      setError("Could not reach the server.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-6 space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="email" className="text-[12px] text-dim">
          Email
        </Label>
        <Input
          id="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          disabled={busy}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="password" className="text-[12px] text-dim">
          Password
        </Label>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={busy}
        />
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-md border border-rose-500/25 bg-rose-500/10 px-2.5 py-2 text-[12px] text-rose-200"
        >
          {error}
        </p>
      )}

      <Button type="submit" className="w-full" disabled={busy || !email || !password}>
        {busy && <Loader2 className="size-3.5 animate-spin" />}
        {busy ? "Signing in" : "Sign in"}
      </Button>

      <p className="text-[11px] leading-relaxed text-faint">
        Every decision you record here is written to the audit trail under this
        address. By signing in you accept the{" "}
        <a href="/legal" className="text-brand hover:underline">
          terms and data handling policy
        </a>
        .
      </p>
    </form>
  );
}
