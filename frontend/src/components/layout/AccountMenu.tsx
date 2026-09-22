"use client";

import { useQuery } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/**
 * Who is signed in, and the way out.
 *
 * The email is shown rather than a generic "Account" because it is the value
 * written to the audit trail for every decision taken from this console. Someone
 * about to release a shipment should be able to see which name that release will
 * carry, without opening a menu.
 */
export function AccountMenu() {
  const [busy, setBusy] = useState(false);

  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: async () => {
      const response = await fetch("/api/auth/session", { cache: "no-store" });
      // 401 is the ordinary signed-out answer, not a fault, so it resolves to
      // null instead of throwing into an error state the header would have to
      // render.
      if (response.status === 401) return null;
      if (!response.ok) throw new Error(`session: ${response.status}`);
      return (await response.json()) as { email: string; exp: number };
    },
    retry: false,
    // Refetched so an expired session stops showing a name it no longer has. A
    // minute is far below the 12-hour TTL and costs one cheap request.
    refetchInterval: 60_000,
  });

  async function signOut() {
    setBusy(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      // A full navigation, not a router push: every cached query below belongs to
      // the session being ended, and a client transition would keep them.
      //
      // Built against window.location.origin rather than passed as "/login"
      // because next/next/no-location-assign-relative-destination rejects a bare
      // relative path here, and the fix it suggests -- useRouter().push -- is the
      // client transition this deliberately avoids.
      window.location.assign(new URL("/login", window.location.origin).toString());
    }
  }

  // Renders nothing at all when there is no session rather than an empty frame.
  // In local development with no VF_SESSION_SECRET there is no login, and a
  // "Sign out" button that signs nobody out would be a lie.
  if (!session.data) return null;

  return (
    <div className="flex items-center gap-1.5">
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="hidden max-w-[11rem] truncate text-[11px] text-dim sm:block">
            {session.data.email}
          </span>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="max-w-[20rem]">
          Decisions you record are written to the audit trail under this address.
        </TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-dim hover:text-white"
            onClick={signOut}
            disabled={busy}
            aria-label="Sign out"
          >
            <LogOut className="size-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom">Sign out</TooltipContent>
      </Tooltip>
    </div>
  );
}
