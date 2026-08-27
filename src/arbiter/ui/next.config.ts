import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  basePath: "/ui",
  assetPrefix: "/ui",
  trailingSlash: true,
  poweredByHeader: false,
  generateBuildId: async () => "arbiter-ui-0.4.0",
};

export default nextConfig;
