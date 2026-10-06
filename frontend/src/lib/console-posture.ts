"use client";

import { useQuery } from "@tanstack/react-query";

/**
 * The console's own access posture (app/api/auth/posture), for the screens that
 * offer a way in: the login page and the Start here strip.
 */
export interface ConsolePosture {
  auth: {
    login_required: boolean;
    public_reads: boolean;
    session: { email: string; exp: number; amr: "password" | "one_click" | null } | null;
    /** Whether the one-click judge button is switched on (lib/one-click.ts). */
    one_click_judge: boolean;
  };
}

export function useConsolePosture() {
  return useQuery<ConsolePosture | null>({
    queryKey: ["auth", "posture"],
    queryFn: async () => {
      const response = await fetch("/api/auth/posture", { cache: "no-store" });
      if (!response.ok) return null;
      return (await response.json()) as ConsolePosture;
    },
    retry: false,
    staleTime: 60_000,
  });
}

/**
 * Sign in as the guest judge, then go to `next` with a full navigation -- every
 * cached query belongs to the signed-out visitor. Returns an error message, or
 * never returns because the page is navigating away.
 */
export async function signInAsGuestJudge(next: string = "/"): Promise<string> {
  try {
    const response = await fetch("/api/auth/judge", { method: "POST" });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: string };
      return body.error ?? "One-click sign-in failed.";
    }
  } catch {
    return "Could not reach the server.";
  }
  window.location.assign(new URL(next, window.location.origin).toString());
  return "";
}
