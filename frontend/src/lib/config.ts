/**
 * Runtime configuration.
 *
 * Demo mode exists because the tenant switcher cannot work against the real
 * API: `_tenant()` in app.py reads the tenant from the authenticated identity,
 * so with IAP disabled there is exactly one tenant and with IAP enabled the
 * tenant is fixed by a verified claim. Switching tenants therefore means
 * switching identity, not sending a different string -- and a dropdown that
 * sent a different string would be the caller-chosen tenant the isolation
 * tests exist to prevent.
 *
 * So: demo mode drives the switcher from fixtures. Live mode shows the one
 * tenant the session actually belongs to, and disables the control.
 *
 * Inlined at build time, because it is NEXT_PUBLIC_ and the client needs it.
 * See .env.production -- setting this as a Cloud Run runtime variable has no
 * effect on an already-built bundle.
 */
export const DEMO_MODE =
  (process.env.NEXT_PUBLIC_DEMO_MODE ?? "true").toLowerCase() !== "false";

/**
 * Where the Flask API lives. Server-side only; never sent to the browser.
 *
 * A function rather than a module-level constant so the value is read from the
 * environment when a request is handled rather than when the module is first
 * evaluated. That keeps it a genuine runtime setting: the URL can be changed
 * with `gcloud run services update --update-env-vars` without rebuilding the
 * image, and there is no chance of the bundler folding in whatever happened to
 * be set on the build machine.
 */
export function flaskBase(): string {
  const raw = process.env.FLASK_API_BASE ?? "http://127.0.0.1:9090";
  return raw.replace(/\/+$/, "");
}

export const REVIEW_THRESHOLD = 40;
