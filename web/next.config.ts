import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export", // pure static site — zero-config on Vercel or any static host
  images: { unoptimized: true },
  trailingSlash: true,
};

export default nextConfig;
