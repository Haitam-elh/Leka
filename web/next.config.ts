import type { NextConfig } from "next";

/**
 * leka-core.com is one site: Karim's pages and the application.
 *
 * The site is static — its HTML, its stylesheet, its two scripts — in
 * public/, served as files at the addresses it has always had
 * (/connecteurs.html, /demo.html…). The application keeps its own
 * (/overview, /sources…). Three rules join them, and nothing else:
 *
 * - "/" is the site's home page. It used to redirect into the application;
 *   someone signed in now goes on from the site's "Se connecter".
 * - /index.html goes to "/": the site's own links point at it, and one
 *   address per page is what a bookmark and a search engine want. The
 *   rewrite below does not bounce back through it — redirects are matched
 *   on the address asked for, once, before any rewrite.
 * - /login.html, the site's own sign-in that could not sign anyone in,
 *   goes to the application's.
 */
const nextConfig: NextConfig = {
  // The production image (web/Dockerfile) runs the server Next traces into
  // .next/standalone: server.js and only the node_modules it uses, rather
  // than the whole install. `next dev` and `next start` ignore it.
  output: "standalone",

  async redirects() {
    return [
      { source: "/index.html", destination: "/", permanent: true },
      { source: "/login.html", destination: "/login", permanent: true },
    ];
  },

  async rewrites() {
    return {
      beforeFiles: [{ source: "/", destination: "/index.html" }],
      afterFiles: [],
      fallback: [],
    };
  },
};

export default nextConfig;
