"use client";

import { ArrowLeft, Loader2, ShieldCheck } from "lucide-react";
import Link from "next/link";
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
 *
 * That short-circuit left the page with NO navigation at all, which made it a dead
 * end: a visitor who followed "Sign in" out of curiosity had no way back to the
 * board except editing the URL. Worse, it implied signing in was required to see
 * anything, when reads are public by design. Both are fixed below -- the way out is
 * a link, and the reason you may not need to sign in at all is stated.
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
    <div className="flex min-h-svh flex-col items-center justify-center gap-3 px-4 py-12">
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
              Sign in to record decisions
            </p>
          </div>
        </div>

        {/* In the FRAME, not in the form, and that placement is the point.
            
            LoginForm sits inside a Suspense boundary because useSearchParams needs one
            to prerender, so the static HTML contains the fallback and the form arrives
            on hydration. A note telling a visitor they are in the wrong place is
            useless if it only appears after the form does -- and this text depends on
            no form state, so nothing keeps it there.
            
            The board, every case trace, the audit trail and the cost figures are all
            readable anonymously: VF_PUBLIC_READS on the console and ANONYMOUS_ROLE on
            the backend govern it, and the split is on the HTTP method rather than a
            path list, so reads are public and writes never are. */}
        <p className="mt-5 rounded-md border border-sky-500/20 bg-sky-500/[0.07] px-2.5 py-2 text-[11px] leading-relaxed text-sky-100/80">
          <span className="font-medium text-sky-100">
            You do not need an account to look around.
          </span>{" "}
          The board, every case trace, the audit trail and the cost figures are public.
          Signing in is only required to <em>record</em> a review decision, because the
          audit trail names the person who made it.
        </p>

        {children}

        {/* Where an account comes from, without printing one.
            
            Reviewer accounts live in VF_OPERATORS as PBKDF2-SHA256 records, so there is
            no self-service sign-up and no password to show here -- a login screen
            displaying working credentials would make the audit trail's attribution
            meaningless. What was missing was any statement of where to ASK, which left
            the form looking like a wall with no door. */}
        <p className="mt-4 border-t border-white/[0.06] pt-3 text-[11px] leading-relaxed text-faint">
          Reviewer accounts are issued by the operator, not self-service. If you are
          assessing this submission, the reviewer address and password are in the private
          testing-instructions field that came with it; if you are running your own
          deployment, see <span className="text-dim">Signing in</span> in the README.
        </p>
      </div>

      {/* Outside the card, and deliberately so: this is a way out of the page, not
          a step in the form. */}
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-[12px] text-dim transition-colors hover:text-white"
      >
        <ArrowLeft className="size-3.5" />
        Back to the board
      </Link>
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
    <form onSubmit={submit} className="mt-5 space-y-4">
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
