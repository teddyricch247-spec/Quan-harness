// Public origin of the deployed frontend. Used by app/sitemap.ts and
// app/robots.ts. Hardcoded (not an env var) because there is exactly one
// production domain; if a custom domain is ever swapped in, change it here.
// No trailing slash: build URLs as `${SITE_URL}${ROUTES.x}`.
export const SITE_URL = 'https://platform.quancis.space';
