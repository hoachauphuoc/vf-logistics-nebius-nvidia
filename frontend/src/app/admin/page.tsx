"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Check,
  ChevronRight,
  Eye,
  Lock,
  Shield,
  ShieldCheck,
  User,
  X,
} from "lucide-react";

import { PageHeading } from "@/components/layout/PageHeading";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface Posture {
  auth: {
    login_required: boolean;
    public_reads: boolean;
    session: { email: string; expires: number } | null;
  };
  roles: Array<{ role: string; includes: string[] }>;
  proxy: {
    reads: string[];
    writes: string[];
  };
}

export default function AdminPage() {
  const query = useQuery<Posture>({
    queryKey: ["auth", "posture"],
    queryFn: async () => {
      const res = await fetch("/api/auth/posture");
      if (!res.ok) throw new Error(`${res.status}`);
      return res.json();
    },
  });

  const posture = query.data;

  return (
    <div className="space-y-6">
      <PageHeading title="Access Control">
        Authentication posture, role hierarchy, and proxy allow-list.
      </PageHeading>

      {query.isLoading && (
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-xl bg-white/[0.04]" />
          ))}
        </div>
      )}

      {posture && (
        <div className="grid gap-3 sm:grid-cols-2">
          <AuthPostureCard posture={posture} />
          <SessionCard posture={posture} />
          <RoleCard posture={posture} />
          <ProxyCard posture={posture} />
        </div>
      )}
    </div>
  );
}

function AuthPostureCard({ posture }: { posture: Posture }) {
  const items = [
    {
      label: "Login required",
      value: posture.auth.login_required,
      desc: "Write operations require a signed session",
    },
    {
      label: "Public reads",
      value: posture.auth.public_reads,
      desc: "Anonymous GET requests pass without a session",
    },
  ];

  return (
    <div className="bento-card p-4">
      <div className="flex items-center gap-2">
        <Lock className="size-3.5 text-brand" aria-hidden />
        <h3 className="text-[11px] font-medium uppercase tracking-wider text-dim">
          Auth posture
        </h3>
      </div>
      <ul className="mt-3 space-y-2">
        {items.map((item) => (
          <li key={item.label} className="flex items-start gap-2">
            <span
              className={cn(
                "mt-0.5 grid size-4 shrink-0 place-items-center rounded",
                item.value
                  ? "bg-risk-clear/15 text-risk-clear"
                  : "bg-risk-critical/15 text-risk-critical",
              )}
            >
              {item.value ? (
                <Check className="size-2.5" />
              ) : (
                <X className="size-2.5" />
              )}
            </span>
            <span>
              <span className="block text-[12px] text-white/90">
                {item.label}
              </span>
              <span className="block text-[11px] text-faint">{item.desc}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SessionCard({ posture }: { posture: Posture }) {
  const session = posture.auth.session;
  const expiry = session
    ? new Date(session.expires * 1000).toLocaleString()
    : null;

  return (
    <div className="bento-card p-4">
      <div className="flex items-center gap-2">
        <User className="size-3.5 text-brand" aria-hidden />
        <h3 className="text-[11px] font-medium uppercase tracking-wider text-dim">
          Active session
        </h3>
      </div>
      {session ? (
        <div className="mt-3 space-y-1.5">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11.5px] text-faint">Email</span>
            <span className="font-mono text-[12px] text-white/90">
              {session.email}
            </span>
          </div>
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11.5px] text-faint">Expires</span>
            <span className="font-mono text-[12px] text-white/90">{expiry}</span>
          </div>
        </div>
      ) : (
        <p className="mt-3 text-[12px] text-faint">
          No active session. Sign in to see your identity here.
        </p>
      )}
    </div>
  );
}

function RoleCard({ posture }: { posture: Posture }) {
  return (
    <div className="bento-card p-4">
      <div className="flex items-center gap-2">
        <ShieldCheck className="size-3.5 text-brand" aria-hidden />
        <h3 className="text-[11px] font-medium uppercase tracking-wider text-dim">
          Role hierarchy
        </h3>
      </div>
      <div className="mt-3 flex items-center gap-1">
        {posture.roles.map((r, i) => (
          <span key={r.role} className="flex items-center gap-1">
            <span
              className={cn(
                "rounded-md px-2 py-1 text-[11px] font-medium",
                i === posture.roles.length - 1
                  ? "bg-brand/15 text-brand ring-1 ring-brand/30"
                  : "bg-white/[0.06] text-white/80 ring-1 ring-white/[0.08]",
              )}
            >
              {r.role.replace(/_/g, " ")}
            </span>
            {i < posture.roles.length - 1 && (
              <ChevronRight className="size-3 text-faint" aria-hidden />
            )}
          </span>
        ))}
      </div>
      <p className="mt-2.5 text-[11px] text-faint">
        Each higher role includes all permissions of lower roles.
        Governance admin has full access.
      </p>
    </div>
  );
}

function ProxyCard({ posture }: { posture: Posture }) {
  return (
    <div className="bento-card p-4">
      <div className="flex items-center gap-2">
        <Shield className="size-3.5 text-brand" aria-hidden />
        <h3 className="text-[11px] font-medium uppercase tracking-wider text-dim">
          Proxy allow-list
        </h3>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3">
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-[10.5px] uppercase tracking-wide text-faint">
            <Eye className="size-3" aria-hidden />
            Reads ({posture.proxy.reads.length})
          </p>
          <ul className="space-y-0.5">
            {posture.proxy.reads.map((r) => (
              <li key={r} className="truncate font-mono text-[10.5px] text-white/70">
                {r}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-[10.5px] uppercase tracking-wide text-faint">
            <Lock className="size-3" aria-hidden />
            Writes ({posture.proxy.writes.length})
          </p>
          <ul className="space-y-0.5">
            {posture.proxy.writes.map((w) => (
              <li key={w} className="truncate font-mono text-[10.5px] text-white/70">
                {w}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
