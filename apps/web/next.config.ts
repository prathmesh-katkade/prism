import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@prism/api-contracts", "@prism/design-system"],
  allowedDevOrigins: ["127.0.0.1"],
  experimental: { externalDir: true }
};

export default nextConfig;
