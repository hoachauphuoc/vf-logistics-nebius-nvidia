"use client";

import { useEffect } from "react";

/**
 * Last-resort boundary: catches failures in the root layout itself.
 *
 * Distinct from `error.tsx` and not redundant with it. A route boundary renders INSIDE
 * the layout, so it cannot catch a throw from the layout, the providers, or the app
 * shell -- and those are precisely the failures that would otherwise be a white page
 * with no navigation to escape by.
 *
 * Because it replaces the layout, it has to supply its own <html> and <body>. That also
 * means none of the app's CSS variables or Tailwind classes are guaranteed to be
 * available, so the styling here is inline and deliberately primitive: a boundary that
 * depends on the thing that just failed is not a boundary.
 */
export default function GlobalError({
  error,
}: {
  error: Error & { digest?: string };
}) {
  useEffect(() => {
    console.error("[global-error]", error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "#0a0c10",
          color: "#e6e8ec",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
          padding: "2rem",
        }}
      >
        <div style={{ maxWidth: "34rem", textAlign: "center" }}>
          <h1 style={{ fontSize: "1rem", fontWeight: 500, margin: "0 0 0.5rem" }}>
            The console failed to start
          </h1>
          <p
            style={{
              fontSize: "0.8125rem",
              lineHeight: 1.6,
              color: "#9aa3b2",
              margin: "0 0 1rem",
            }}
          >
            This is a failure in the application shell rather than in one screen, so
            reloading is the only recovery from here. No case data was written.
          </p>
          <p
            style={{
              fontFamily: "ui-monospace, Consolas, monospace",
              fontSize: "0.6875rem",
              color: "#6b7280",
              margin: "0 0 1.25rem",
              wordBreak: "break-word",
            }}
          >
            {error.message || "No message on the error object."}
            {error.digest ? ` · digest ${error.digest}` : null}
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              fontSize: "0.8125rem",
              padding: "0.5rem 0.875rem",
              borderRadius: "0.5rem",
              border: "1px solid rgba(255,255,255,0.14)",
              background: "rgba(255,255,255,0.04)",
              color: "#e6e8ec",
              cursor: "pointer",
            }}
          >
            Reload the console
          </button>
        </div>
      </body>
    </html>
  );
}
