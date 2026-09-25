import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The production image (web/Dockerfile) runs the server Next traces into
  // .next/standalone: server.js and only the node_modules it uses, rather
  // than the whole install. `next dev` and `next start` ignore it.
  output: "standalone",
};

export default nextConfig;
