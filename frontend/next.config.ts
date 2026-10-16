import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // Deployed on Vercel, which runs Next.js natively (no static-export
  // workaround needed to get a real per-route HTML file, and no host-side
  // rewrite rule needed for dynamic routes like /playground/<sessionId> —
  // Vercel renders those on demand). output: 'export' used to be set here
  // for generic static hosting; removed since it actively fights dynamic
  // routes on a platform that doesn't need it.

  // No next/image usage in this app (avatars etc. are plain <img> tags).
  // Vercel's Image Optimization API is available now that this isn't a
  // static export, but unoptimized: true is left on since nothing here
  // uses next/image yet — flip it off if that changes.
  images: {
    unoptimized: true,
  },

  // /terms and /privacy were the original slugs; permanently redirected
  // to /terms-of-service and /privacy-policy so old links/bookmarks still
  // resolve. These exact new slugs are also what's registered as the
  // Terms of Service / Privacy Policy links on the Google Cloud Console
  // OAuth consent screen — don't rename them again without updating that
  // too.
  async redirects() {
    return [
      { source: '/terms', destination: '/terms-of-service', permanent: true },
      { source: '/privacy', destination: '/privacy-policy', permanent: true },
      // The docs overview is /docs; there is no separate /docs/overview page.
      { source: '/docs/overview', destination: '/docs', permanent: true },
      // "How Kael works" became "About Kael" (2026-10-08): the docs no longer describe Kael's internals.
      { source: '/docs/how-it-works', destination: '/docs/about', permanent: true },
    ];
  },
};

export default nextConfig;
