import type { MetadataRoute } from 'next';
import { ROUTES } from '../lib/routes';
import { SITE_URL } from '../lib/site';

// Served at /robots.txt. Crawlers may fetch the public pages; the signed-in
// app is off limits. Disallow rules are prefix matches, so "/playground" also
// covers every /playground/<sessionId> page.
//
// /login is intentionally NOT disallowed: it carries a `noindex` meta tag, and
// a crawler that is blocked by robots.txt can never see that tag.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        disallow: [
          ROUTES.dashboard,
          ROUTES.keys,
          ROUTES.playground,
          ROUTES.usage,
          ROUTES.account,
          ROUTES.admin,
          ROUTES.resetPassword,
        ],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
