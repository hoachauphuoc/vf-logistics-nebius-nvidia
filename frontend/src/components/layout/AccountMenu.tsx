"use client";

import { useQuery } from "@tanstack/react-query";
import { LogIn, LogOut } from "lucide-react";
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

  // No session. Offer the way in rather than rendering nothing.
  //
  // Rendering nothing was right while the console was wall-to-wall private: there
  // was no way to be here unauthenticated, so a control would have been dead
  // weight. With reads public, an anonymous reader is an ordinary visitor and
  // needs to be told that writing is possible and how -- otherwise the first thing
  // they learn about the login is a 401 on a button they already pressed.
  //
  // `isLoading` is distinguished from "signed out" so the header does not flash a
  // Sign in link for one frame on every page load for someone who is signed in.
  if (!session.data) {
    if (session.isLoading) return null;
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <a
            href="/login"
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-white/10 px-2.5 text-[11.5px] text-dim transition-colors hover:border-white/20 hover:text-white"
          >
            <LogIn className="size-3.5" />
            Sign in
          </a>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="max-w-[20rem]">
          You are viewing read-only. Sign in to record a review decision; the
          audit trail records the signed-in account.
        </TooltipContent>
      </Tooltip>
    );
  }

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
