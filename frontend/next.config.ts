import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Only affects `next build`'s output shape (a minimal self-contained
  // server directory) -- `next dev` (the local docker-compose workflow)
  // is unaffected. Lets the Fly production Dockerfile copy just that
  // directory instead of the full node_modules tree.
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    // The repo root's own package.json/package-lock.json (for the Neon
    // integration) makes Next.js see two lockfiles and guess at the
    // workspace root -- pin it explicitly to silence that warning.
    root: process.cwd(),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
