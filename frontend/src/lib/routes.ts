// Central map of app "pages" to their Next.js route paths.
// Mirrors the old PageType keys 1:1 so nothing else has to change shape.
export const ROUTES = {
  home: '/',
  login: '/login',
  resetPassword: '/reset-password',
  dashboard: '/dashboard',
  keys: '/keys',
  playground: '/playground',
  docs: '/docs',
  pricing: '/pricing',
  usage: '/usage',
  account: '/account',
  admin: '/admin',
  terms: '/terms-of-service',
  privacy: '/privacy-policy',
} as const;

export type RouteKey = keyof typeof ROUTES;

// next.config.ts does NOT set `trailingSlash` (Next.js default: false), so
// today usePathname() reports paths like "/login", not "/login/". This
// helper is kept as a safeguard anyway: every ROUTES value above is written
// WITHOUT a trailing slash, and a pathname that does end in one ("/login/")
// silently never matches `pathname === ROUTES.x` — that mismatch is exactly
// what once let the navbar show up on /login (isStandalone compared
// "/login/" to "/login" and always got false). Compare pathnames through
// this first, and it keeps working if trailing slashes ever appear.
export const normalizePathname = (pathname: string | null | undefined): string => {
  if (!pathname) return '/';
  if (pathname === '/') return '/';
  return pathname.endsWith('/') ? pathname.slice(0, -1) : pathname;
};

// Links to the public marketing site (www.quancis.space), a separate repo and
// Vercel project, so these are plain external URLs, not Next.js routes.
// `wwwDemos` is the Kael demos HUB on purpose: link here, never to an
// individual demo, so a new demo needs no change in this repo.
export const EXTERNAL = {
  wwwDemos: 'https://www.quancis.space/kael/demo',
  // Holding page for Quan Harness / Quan Chat while they are not public.
  wwwNotAvailable: 'https://www.quancis.space/not-available',
} as const;

// /playground/<sessionId> — each playground conversation gets its own URL so the
// address bar always reflects which conversation is on screen (and so a
// direct link/refresh/back-button lands on that one conversation instead
// of a generic playground shell). Backed by
// app/playground/[sessionId]/page.tsx.
export const playgroundSessionPath = (sessionId: string) =>
  `${ROUTES.playground}/${encodeURIComponent(sessionId)}`;

// /docs is the docs overview; every other docs page is /docs/<slug>. The list
// of slugs lives in components/docs/nav.ts (one entry per page). Link to a
// docs page through this helper so a slug is never typed twice.
export const docsPath = (slug: string) =>
  slug === 'overview' ? ROUTES.docs : `${ROUTES.docs}/${encodeURIComponent(slug)}`;
