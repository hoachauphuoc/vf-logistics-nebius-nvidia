"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { AuditDetailSheet } from "@/components/dashboard/AuditDetailSheet";
import { AuditLogsTable } from "@/components/dashboard/AuditLogsTable";
import { KpiCards } from "@/components/dashboard/KpiCards";
import { HelpDot } from "@/components/help/HelpDot";
import { PageHeading } from "@/components/layout/PageHeading";
import { fetchAudits, fetchUsage, queryKeys } from "@/lib/api";
import { useIdentity } from "@/lib/identity";
import { displayTenant, useTenant } from "@/lib/tenant-context";

export default function RiskRadarPage() {
  const { tenant } = useTenant();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // The tenant id is part of every query key, so a switch discards the previous
  // tenant's cache rather than showing its rows under a new name.
  const audits = useQuery({
    queryKey: queryKeys.audits(tenant.id),
    queryFn: () => fetchAudits(tenant.id),
  });

  const usage = useQuery({
    queryKey: queryKeys.usage(tenant.id),
    queryFn: () => fetchUsage(tenant.id),
    // Billing is operator upstream, so a visitor's 403 is the answer, not a fault
    // to retry three times while the spend tiles sit on skeletons.
    retry: false,
  });

  const rows = audits.data ?? [];
  const identity = useIdentity();

  // The tenant used for cache keys and the tenant shown to the reader are not
  // the same thing in live mode: the key is a local label, the display name has
  // to be whatever the API says the authenticated session resolves to. Read from
  // whoami rather than billing, which only an operator may see.
  const display = displayTenant(tenant, identity.data?.tenant_id, identity.isError);

  // Derived, not stored. Holding the audit object in state would need an effect
  // to clear it when the tenant changes, and forgetting that effect would leave
  // one tenant's audit open above another tenant's table -- the one cross-tenant
  // leak a client-side console can create by itself. Resolving the id against
  // the current rows makes that impossible: rows for another tenant simply do
  // not contain it.
  const selected = rows.find((a) => a.audit_id === selectedId) ?? null;

  return (
    <>
      <PageHeading title="Risk Radar">
        Import and export declarations screened for{" "}
        <span className="text-white/85">{display.name}</span>: sanctions
        exposure, dual-use classification and adverse media, each with the
        provenance to defend it.
      </PageHeading>

      <div className="space-y-3">
        <KpiCards
          audits={rows}
          usage={usage.data}
          loading={audits.isLoading || usage.isLoading}
          usageError={usage.error}
        />

        <div className="flex items-center gap-1.5">
          <h2 className="text-[12px] font-medium text-white">Completed audits</h2>
          <HelpDot id="radar.audits" />
        </div>
        <AuditLogsTable
          audits={rows}
          loading={audits.isLoading}
          error={audits.error}
          selectedId={selectedId}
          onSelect={(audit) => setSelectedId(audit.audit_id)}
        />
      </div>

      <AuditDetailSheet
        audit={selected}
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null);
        }}
      />
    </>
  );
}
