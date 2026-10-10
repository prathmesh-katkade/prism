import type { NextConfig } from "next";

// The desktop build (apps/desktop-shell) needs a static export it can hand
// to Tauri's frontendDist -- there's no Node server inside the shipped app,
// only the FastAPI sidecar. The Render/staging web deployment keeps its
// normal server build (`next start`); this only switches to `output:
// "export"` when PRISM_BUILD_TARGET=desktop is set, so nothing about the
// existing web deployment changes.
const isDesktopBuild = process.env.PRISM_BUILD_TARGET === "desktop";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@prism/api-contracts", "@prism/design-system"],
  allowedDevOrigins: ["127.0.0.1"],
  experimental: { externalDir: true },
  ...(isDesktopBuild
    ? {
        output: "export" as const,
        images: { unoptimized: true },
        // Baked in at build time so the desktop build needs only
        // PRISM_BUILD_TARGET=desktop, not a second env var to remember.
        // NEXT_PUBLIC_PRISM_API_URL still wins if a packager ever needs to
        // override the sidecar port -- apiUrl() in src/config/api.ts reads
        // process.env, not this file, so an explicit env var always takes
        // precedence over this default.
        env: { NEXT_PUBLIC_PRISM_API_URL: process.env.NEXT_PUBLIC_PRISM_API_URL ?? "http://127.0.0.1:8000" }
      }
    : {})
};

export default nextConfig;
