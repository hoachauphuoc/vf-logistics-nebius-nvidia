import { type Role, roleLabel } from "@/lib/identity";
import { cn } from "@/lib/utils";

const ROLE_TONE: Record<Role, string> = {
  viewer: "bg-white/[0.06] text-white/80 ring-white/[0.1]",
  reviewer: "bg-risk-clear/10 text-risk-clear ring-risk-clear/25",
  operator: "bg-risk-warn/10 text-risk-warn ring-risk-warn/25",
  governance_admin: "bg-brand/15 text-brand ring-brand/30",
};

/** A role, as a small labelled chip. `null` renders as "Public". */
export function RoleChip({ role, className }: { role: Role | string | null; className?: string }) {
  const tone =
    role && role in ROLE_TONE
      ? ROLE_TONE[role as Role]
      : "bg-white/[0.04] text-dim ring-white/[0.08]";
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-md px-1.5 py-0.5 text-[10.5px] font-medium ring-1",
        tone,
        className,
      )}
    >
      {roleLabel(role)}
    </span>
  );
}
