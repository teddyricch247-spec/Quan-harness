import type { MetadataRoute } from 'next';
import { DOCS_PAGES } from '../components/docs/nav';
import { ROUTES, docsPath } from '../lib/routes';
import { SITE_URL } from '../lib/site';

// Served at /sitemap.xml. Public, indexable pages only — signed-in pages
// (dashboard, keys, playground, usage, account, admin) are deliberately absent
// and are also disallowed in app/robots.ts.
//
// No lastModified: this file is evaluated at build time, so `new Date()` would
// claim every page changed on every deploy, which is worse than saying nothing.
//
// /login is NOT listed: app/login/page.tsx sets robots `noindex`, and a
// sitemap should only contain URLs you want indexed (Search Console reports
// "submitted URL marked noindex" otherwise).
export default function sitemap(): MetadataRoute.Sitemap {
  const publicRoutes = [
    ROUTES.home,
    ROUTES.pricing,
    // /docs plus every /docs/<slug> (the list is components/docs/nav.ts).
    ...DOCS_PAGES.map((p) => docsPath(p.slug)),
    ROUTES.terms,
    ROUTES.privacy,
  ];
  // next.config.ts sets no `trailingSlash`, so these paths are already the
  // canonical (non-redirecting) URLs; "/" becomes "https://.../".
  return publicRoutes.map((route) => ({ url: `${SITE_URL}${route}` }));
}
