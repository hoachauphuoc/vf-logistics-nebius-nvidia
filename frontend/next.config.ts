import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next 16 refuses to serve dev resources (including the client chunks and
  // HMR) to an origin it was not started for. Reaching the dev server on
  // 127.0.0.1 rather than localhost therefore leaves the page server-rendered
  // and never hydrated, which looks exactly like a stuck loading state and is
  // not one. Development only; has no effect on a production build.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
