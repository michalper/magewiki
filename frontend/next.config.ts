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
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
