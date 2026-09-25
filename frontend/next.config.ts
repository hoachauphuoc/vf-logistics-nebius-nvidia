import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],

  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains",
          },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          {
            // ENFORCING. It shipped as Report-Only first, and that caught a real bug:
            // this policy was adapted from the backend's, where the legacy dashboard
            // pulls Google Fonts over the network (static/index.html uses
            // `@import url('https://fonts.googleapis.com/...')`). The console does NOT --
            // layout.tsx imports `next/font/google`, which downloads the files at build
            // time and serves them from /_next/static/media on this origin. So
            // `font-src https://fonts.gstatic.com` without 'self' would have blocked
            // every font on the console while reporting nothing as broken.
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              // 'unsafe-inline' is required: Next injects inline hydration scripts and
              // has no nonce hook that survives static prerendering. Removing it means
              // moving off inline bootstrap entirely, which is a larger change than a
              // header.
              "script-src 'self' 'unsafe-inline'",
              // Tailwind and next/font both emit inline <style>. No external stylesheet
              // origin is needed, unlike the backend.
              "style-src 'self' 'unsafe-inline'",
              // Self-hosted by next/font. This is the line the Report-Only pass earned.
              "font-src 'self'",
              "img-src 'self' data:",
              "connect-src 'self'",
              "frame-src 'none'",
              "frame-ancestors 'none'",
              // Neither of these inherits from default-src, so omitting them is a gap
              // even with a restrictive default: base-uri stops an injected <base> tag
              // re-pointing every relative URL, form-action constrains where forms post.
              "base-uri 'none'",
              "form-action 'self'",
              // 'self', NOT 'none'. review/page.tsx renders the archived bill of lading
              // in an <object data=...>, which object-src governs -- 'none' would blank
              // the Paperwork panel, which is one of the things the demo shows. The
              // backend already pins that response to an image/PDF allow-list, so a
              // same-origin object here cannot be an HTML document.
              "object-src 'self'",
            ].join("; "),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
