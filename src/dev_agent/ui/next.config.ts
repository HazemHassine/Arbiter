import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  basePath: "/ui",
  assetPrefix: "/ui",
  trailingSlash: true,
  poweredByHeader: false,
};

export default nextConfig;
