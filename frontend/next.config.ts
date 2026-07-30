import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces .next/standalone for a minimal, self-contained Docker image.
  // The multi-stage Dockerfile copies from there instead of shipping the
  // whole node_modules tree.
  output: "standalone",
};

export default nextConfig;
