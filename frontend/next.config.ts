import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Lean, self-contained build output (server.js + only the deps it
  // actually needs) — used by the Docker quickstart (see
  // ../docker-compose.yml, ./Dockerfile). Irrelevant to `npm run dev` or a
  // Vercel deploy, both ignore this.
  output: "standalone",
};

export default nextConfig;
