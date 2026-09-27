"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, Eye, KeyRound, Lock, LogIn, ShieldCheck, User, Users } from "lucide-react";
import { useMemo, useState } from "react";

import { HelpDot } from "@/components/help/HelpDot";
import { PageHeading } from "@/components/layout/PageHeading";
import { RoleChip } from "@/components/layout/RoleChip";
import { ErrorState } from "@/components/layout/States";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type AccessPolicy,
  type Identity,
  roleLabel,
  usePolicy,
  useIdentity,
} from "@/lib/identity";
import { cn } from "@/lib/utils";

/**
 * Access Control: who you are, what you may do, and why -- all read from the
 * services that enforce it.
 *
 * Three sources, none of them written down here:
 *
 * - `/api/proxy/auth/whoami`: the API's own verdict on the caller.
 * - `/api/proxy/auth/policy`: every route with the role its decorator enforces,
 *   introspected from the running API (auth.route_policy).
 * - `/api/auth/posture`: the console's half -- sign-in, public reads, and what its
 *   BFF forwards, from lib/proxy-policy.ts, which the BFF itself enforces.
 *
 * An earlier version of this screen hand-copied the role hierarchy and the proxy
 * allow-list, and was already wrong on the day it shipped (three forwarded read
 * routes missing). It also drew a hierarchy nobody was subject to: every signed-in
 * person was a governance admin. Both problems are fixed at the source; this
 * screen now only reports.
 */

interface Posture {
  auth: {
    login_required: boolean;
    public_reads: boolean;
    session: { email: string; exp: number } | null;
  };
  proxy: {
    reads: string[];
    writes: Array<{ method: "POST" | "PUT"; path: string }>;
  };
}

const AUTH_METHOD_LABEL: Record<Identity["authenticated_by"], string> = {
  console_session: "Console sign-in",
  api_key: "API key (service)",
  iap: "Google IAP",
  anonymous: "Not signed in",
};

export default function AccessControlPage() {
  const identity = useIdentity();
  const policy = usePolicy();
  const posture = useQuery<Posture>({
    queryKey: ["auth", "posture"],
    queryFn: async () => {
      const res = await fetch("/api/auth/posture", { cache: "no-store" });
      if (!res.ok) throw new Error(`posture: HTTP ${res.status}`);
      return res.json();
    },
    retry: false,
  });

  return (
    <>
      <PageHeading title="Access Control">
        Who you are to the API, what that lets you do, and the policy behind it —
        read from the running services, not written down on this page.
      </PageHeading>

      <div className="grid gap-3 lg:grid-cols-3">
        <Section loading={identity.isLoading} error={identity.error}>
          {identity.data !== undefined && (
            <YouCard identity={identity.data} posture={posture.data} />
          )}
        </Section>
        <Section loading={posture.isLoading} error={posture.error}>
          {posture.data && <PostureCard posture={posture.data} policy={policy.data ?? null} />}
        </Section>
        <Section loading={policy.isLoading} error={policy.error}>
          {policy.data !== undefined && <RolesCard policy={policy.data} />}
        </Section>
      </div>

      <div className="mt-3">
        <Section loading={policy.isLoading || posture.isLoading} error={policy.error ?? posture.error}>
          {policy.data && posture.data && (
            <AccessMatrix
              policy={policy.data}
              posture={posture.data}
              identity={identity.data ?? null}
            />
          )}
        </Section>
      </div>
    </>
  );
}

function Section({
  loading,
  error,
  children,
}: {
  loading: boolean;
  error: unknown;
  children: React.ReactNode;
}) {
  if (error) return <ErrorState error={error} />;
  if (loading) return <Skeleton className="h-48 rounded-xl bg-white/[0.04]" />;
  return <>{children}</>;
}

function CardTitle({
  icon: Icon,
  children,
  help,
}: {
  icon: React.ElementType;
  children: React.ReactNode;
  help?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="size-3.5 text-brand" aria-hidden />
      <h3 className="text-[11px] font-medium uppercase tracking-wider text-dim">{children}</h3>
      {help && <HelpDot id={help} />}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="shrink-0 text-[11.5px] text-faint">{label}</span>
      <span className="min-w-0 truncate text-right text-[12px] text-white/90">{children}</span>
    </div>
  );
}

function YouCard({ identity, posture }: { identity: Identity | null; posture?: Posture }) {
  if (!identity) {
    return (
      <div className="bento-card h-full p-4">
        <CardTitle icon={User}>You</CardTitle>
        <p className="mt-3 text-[12px] leading-relaxed text-dim">
          The API did not say who you are — this build is in demo mode, so there is
          no live API to ask.
        </p>
      </div>
    );
  }

  const anonymous = identity.authenticated_by === "anonymous";
  const exp = posture?.auth.session?.exp;

  return (
    <div className="bento-card h-full p-4">
      <CardTitle icon={User} help="access.you">You, as the API sees you</CardTitle>
      <div className="mt-3 space-y-1.5">
        <Row label="Identity">
          <span className="font-mono">{anonymous ? "Anonymous visitor" : identity.email}</span>
        </Row>
        <Row label="Signed in with">{AUTH_METHOD_LABEL[identity.authenticated_by]}</Row>
        <Row label="Role">
          <RoleChip role={identity.role} />
        </Row>
        <Row label="Because">
          <span className="font-mono text-[11px] text-dim">{identity.role_source}</span>
        </Row>
        {exp && (
          <Row label="Session ends">
            {new Date(exp * 1000).toLocaleString("en-GB", {
              day: "2-digit",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </Row>
        )}
      </div>

      <p className="mt-3 text-[11px] uppercase tracking-wide text-faint">Grants</p>
      <div className="mt-1 flex flex-wrap gap-1">
        {identity.grants.map((r) => (
          <RoleChip key={r} role={r} />
        ))}
      </div>

      {anonymous && (
        <a
          href="/login?next=/admin"
          className="mt-4 inline-flex h-8 items-center gap-1.5 rounded-md border border-white/10 px-2.5 text-[11.5px] text-dim transition-colors hover:border-white/20 hover:text-white"
        >
          <LogIn className="size-3.5" aria-hidden />
          Sign in to act
        </a>
      )}
    </div>
  );
}

function PostureCard({ posture, policy }: { posture: Posture; policy: AccessPolicy | null }) {
  // Tone follows the SAFETY of each setting, not whether it is switched on:
  // public reads on is the weaker posture, and a green tick on it read as a
  // recommendation.
  const items: Array<{ label: string; detail: string; tone: "safe" | "open" }> = [
    posture.auth.login_required
      ? { label: "Sign-in required for writes", detail: "Every action goes through a signed session.", tone: "safe" }
      : { label: "No sign-in configured", detail: "Development only: VF_SESSION_SECRET is unset.", tone: "open" },
    posture.auth.public_reads
      ? {
          label: "Anyone can read",
          detail: "Screens load without signing in (VF_PUBLIC_READS). Deliberate for the judging window.",
          tone: "open",
        }
      : { label: "Reads need sign-in", detail: "Anonymous visitors are sent to the login page.", tone: "safe" },
  ];

  return (
    <div className="bento-card h-full p-4">
      <CardTitle icon={Lock} help="access.posture">Sign-in posture</CardTitle>
      <ul className="mt-3 space-y-2.5">
        {items.map((item) => (
          <li key={item.label} className="flex items-start gap-2">
            <span
              className={cn(
                "mt-0.5 grid size-4 shrink-0 place-items-center rounded",
                item.tone === "safe" ? "bg-risk-clear/15 text-risk-clear" : "bg-risk-warn/15 text-risk-warn",
              )}
            >
              {item.tone === "safe" ? <Check className="size-2.5" /> : <Eye className="size-2.5" />}
            </span>
            <span>
              <span className="block text-[12px] text-white/90">{item.label}</span>
              <span className="block text-[11px] leading-relaxed text-faint">{item.detail}</span>
            </span>
          </li>
        ))}
        {policy && (
          <li className="flex items-start gap-2">
            <span className="mt-0.5 grid size-4 shrink-0 place-items-center rounded bg-white/[0.06] text-dim">
              <User className="size-2.5" />
            </span>
            <span>
              <span className="block text-[12px] text-white/90">
                A visitor is a {roleLabel(policy.anonymous_role).toLowerCase()}
              </span>
              <span className="block text-[11px] leading-relaxed text-faint">
                The console lends its API key only to a signed-in session, so an
                anonymous request reaches the API as ANONYMOUS_ROLE.
              </span>
            </span>
          </li>
        )}
      </ul>
    </div>
  );
}

function RolesCard({ policy }: { policy: AccessPolicy | null }) {
  if (!policy) {
    return (
      <div className="bento-card h-full p-4">
        <CardTitle icon={ShieldCheck}>Roles</CardTitle>
        <p className="mt-3 text-[12px] text-dim">No live API in demo mode.</p>
      </div>
    );
  }
  const accounts = new Map(policy.role_assignment.map((a) => [a.role, a]));

  return (
    <div className="bento-card h-full p-4">
      <CardTitle icon={ShieldCheck} help="access.roles">Roles and who holds them</CardTitle>
      <ol className="mt-3 space-y-1.5">
        {[...policy.roles].reverse().map((role) => {
          const assignment = accounts.get(role);
          return (
            <li key={role} className="flex items-center justify-between gap-2">
              <RoleChip role={role} />
              <span className="text-right font-mono text-[10.5px] text-faint">
                {assignment
                  ? `${assignment.variable} · ${assignment.accounts} account${assignment.accounts === 1 ? "" : "s"}`
                  : role === policy.anonymous_role
                    ? "everyone, incl. visitors"
                    : "everyone signed in"}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-[11px] leading-relaxed text-faint">
        Each role includes the ones below it. Roles are assigned by email on the
        API, never taken from a token, and a signed-in session can only narrow
        what the console&rsquo;s key grants ({roleLabel(policy.api_key_grant)}).
      </p>
    </div>
  );
}

/** `/api/v1/review/<case_id>/decide` -> `review/<id>/decide`, the proxy's spelling. */
function normalise(path: string): string {
  return path.replace(/^\/api\/v1\//, "").replace(/<[^>]+>/g, "<id>");
}

function AccessMatrix({
  policy,
  posture,
  identity,
}: {
  policy: AccessPolicy;
  posture: Posture;
  identity: Identity | null;
}) {
  const [filter, setFilter] = useState("");

  const rows = useMemo(() => {
    const reads = new Set(posture.proxy.reads);
    const writes = new Set(posture.proxy.writes.map((w) => `${w.method} ${w.path}`));
    const needle = filter.trim().toLowerCase();

    return policy.routes
      .filter((r) => r.path.startsWith("/api/v1/"))
      .flatMap((r) =>
        r.methods.map((method) => {
          const key = normalise(r.path);
          const viaConsole = method === "GET" ? reads.has(key) : writes.has(`${method} ${key}`);
          const role = r.required_role;
          const allowed =
            identity === null
              ? null
              : role === null
                ? true
                : role === "authenticated"
                  ? identity.authenticated_by !== "anonymous"
                  : identity.grants.includes(role) &&
                    (method === "GET" || !viaConsole || identity.authenticated_by !== "anonymous");
          return { method, path: r.path, role, viaConsole, allowed };
        }),
      )
      .filter((row) => !needle || `${row.method} ${row.path} ${row.role ?? "public"}`.toLowerCase().includes(needle));
  }, [policy, posture, identity, filter]);

  return (
    <div className="bento-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle icon={KeyRound} help="access.matrix">Effective access</CardTitle>
        <Input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter routes or roles"
          aria-label="Filter routes"
          className="h-8 w-56 border-white/10 bg-black/30 text-[12px]"
        />
      </div>
      <p className="mt-1.5 max-w-3xl text-[11.5px] leading-relaxed text-dim">
        Every API route with the role its code enforces. <em>Console</em> marks the
        routes a screen reaches through the console&rsquo;s proxy; the rest are
        reachable only with an API key at <span className="font-mono">/api/v1/*</span>.
        The last column is what you, as the API sees you now, would be allowed.
      </p>

      <div className="mt-3 max-h-[26rem] overflow-auto rounded-lg border border-white/[0.06] scrollbar-thin">
        <table className="w-full min-w-[40rem] border-collapse text-left">
          <thead className="sticky top-0 bg-slate-950/95 backdrop-blur">
            <tr className="text-[10.5px] uppercase tracking-wide text-faint">
              <th className="px-3 py-2 font-medium">Method</th>
              <th className="px-3 py-2 font-medium">Route</th>
              <th className="px-3 py-2 font-medium">Requires</th>
              <th className="px-3 py-2 font-medium">Console</th>
              <th className="px-3 py-2 text-center font-medium">You</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.method} ${row.path}`} className="border-t border-white/[0.05]">
                <td className="px-3 py-1.5 font-mono text-[10.5px] text-dim">{row.method}</td>
                <td className="px-3 py-1.5 font-mono text-[11px] text-white/85">{row.path}</td>
                <td className="px-3 py-1.5">
                  {row.role === "authenticated" ? (
                    <span className="text-[11px] text-dim">Any sign-in</span>
                  ) : (
                    <RoleChip role={row.role} />
                  )}
                </td>
                <td className="px-3 py-1.5 text-[11px] text-dim">
                  {row.viaConsole ? (
                    <span className="inline-flex items-center gap-1 text-white/80">
                      <Users className="size-3" aria-hidden /> Console
                    </span>
                  ) : (
                    <span className="text-faint">API key only</span>
                  )}
                </td>
                <td className="px-3 py-1.5 text-center">
                  {row.allowed === null ? (
                    <span className="text-[11px] text-faint">?</span>
                  ) : row.allowed ? (
                    <Check className="mx-auto size-3.5 text-risk-clear" aria-label="allowed" />
                  ) : (
                    <Lock className="mx-auto size-3.5 text-faint" aria-label="not allowed" />
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-[12px] text-faint">
                  No route matches that filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
