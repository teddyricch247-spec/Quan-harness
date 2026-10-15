/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Phase Convert (C6): routes that no longer have a page. Temporary (not permanent) redirects so a
  // browser never caches them past a rollback. Everything else keeps its URL — in particular
  // /connections/github and the other Settings pages, which OAuth callbacks (the backend's
  // `…/connections/github?connected=…` redirect) land on.
  async redirects() {
    return [
      { source: "/projects/new", destination: "/projects", permanent: false },
      { source: "/connections", destination: "/settings", permanent: false },
      { source: "/projects/:id/sessions", destination: "/projects/:id", permanent: false },
    ];
  },
};

module.exports = nextConfig;
