"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "framer-motion";
import { useState } from "react";

import { ToastProvider } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";

export function Providers({ children }: { children: React.ReactNode }) {
  // Created in state so the client survives re-renders but is never shared
  // between users on the server.
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      {/* Tenant selection lives in an external store (lib/tenant-context), not
          a provider, so it needs no wrapper here.

          reducedMotion="user": every framer-motion animation honours the
          operating system's "reduce motion" setting, rather than each component
          having to remember to. */}
      <MotionConfig reducedMotion="user">
        <TooltipProvider delayDuration={200}>
          <ToastProvider>{children}</ToastProvider>
        </TooltipProvider>
      </MotionConfig>
    </QueryClientProvider>
  );
}
