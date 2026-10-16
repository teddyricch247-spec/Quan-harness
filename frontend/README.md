# Quancis frontend

Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, Supabase
JS for auth, Three.js for the landing hero. Deployed by Vercel (project
"quancis") on every push to `main`. It talks to the backend only through
`src/lib/api.ts`; the only thing it asks Supabase for directly is
authentication (`supabase.auth.*`). It never queries database tables.

Read `../AGENTS.md` first. Backend behavior: `../backend/README.md`.

## Setup

```
npm install
npm run dev      # local dev
npm run lint     # tsc --noEmit (type check)
npm run build    # the real check; Vercel runs this
```

Environment (public): `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_BASE_URL`. See
`.env.example`. Missing values break login and every API call.

## Structure

```
src/app/                    Next.js routes; each page.tsx is a thin wrapper
src/app/sitemap.ts          /sitemap.xml (public pages only), built from ROUTES
src/app/robots.ts           /robots.txt (blocks the signed-in app), points at the sitemap
src/components/pages/       the real page implementations
src/components/layout/      AppShell, Navbar (glass drawer), Footer, LegalBar
src/components/three/       HeroCanvas.tsx (WebGL hero, fails quietly without WebGL)
src/components/             RequireAuth, HomeGate, BrandMark, providers
src/context/AppContext.tsx  auth state, profile, billing, stats, notification prefs
src/lib/api.ts              typed client for every backend call; ApiError
src/lib/supabase.ts         Supabase client (auth only)
src/lib/routes.ts           ROUTES map, normalizePathname, playground session paths
src/lib/site.ts             SITE_URL, the public origin used by sitemap/robots
src/types.ts
src/app/globals.css         the whole design system (tokens + shared classes)
```

## Pages

| Route | Page | Notes |
|---|---|---|
| `/` | HomePage (via HomeGate) | Landing. Logged-in users are redirected to `/dashboard` |
| `/login` | LoginPage | Standalone (no navbar/footer). Email+password, Google, GitHub |
| `/reset-password` | ResetPasswordPage | |
| `/auth/confirm` | AuthConfirmPage | Landing page for the confirm-signup and reset emails when the backend runs `AUTH_LINK_MODE=confirm_page`. Reads `token_hash` and `type` from the URL and spends the one-time token only when the button is pressed (`supabase.auth.verifyOtp`), so email scanners that pre-fetch links can't burn it |
| `/dashboard` | DashboardPage | Overview |
| `/playground`, `/playground/[sessionId]` | PlaygroundPage | Playground conversations; each has its own URL |
| `/keys` | ApiKeysPage | Create and revoke API keys (secret shown once) |
| `/usage` | UsagePage | Spend, token chart, balance, "Add Prepaid Credits" (Coming Soon stub) |
| `/account` | AccountPage | Profile, password, notification prefs |
| `/admin` | AdminPage | Stats, users, credit, suspend, "Run check" (billing integrity); shown only to admins |
| `/pricing` | PricingPage | Public. A price card with both models (Kael Beta and Kael Pro Beta), plus a comparison table that lists both against GPT-6 Astra/Sol, Claude Opus 5.5, Claude Fable 5.1 and Kimi K3 |
| `/docs` | DocsPage (slug `overview`) | Public docs overview |
| `/docs/[slug]` | DocsPage | The other 21 docs pages (quickstart, endpoints, thinking levels, pricing, errors, console guides, and so on). `/docs/overview` redirects to `/docs` |
| `/terms-of-service`, `/privacy-policy` | TermsPage, PrivacyPage | Bare documents. `/terms` and `/privacy` redirect here |

## Behavior worth knowing

- **Links to the Kael demos:** the playable demos live on the public www
  site, a separate repo. This app links only to the demos **hub**, never to
  one demo, so adding a demo there needs no change here. The URL is
  `EXTERNAL.wwwDemos` in `src/lib/routes.ts` (one place to change it). It is
  linked from the navbar drawer ("Kael Demos", signed in or out), the footer
  (Developers column), the home hero ("See what Kael can build") and the docs
  sidebar ("See Kael In Action"). They are plain `<a>` links, not `<Link>`,
  because they leave this app.
- **Auth model:** the Supabase session lives in localStorage, not a cookie,
  so Next.js middleware cannot see it. `RequireAuth` is a client-side
  guard. Real enforcement is the backend (`require_login` /
  `require_admin` on every API call).
- **Pathnames:** `next.config.ts` has no `trailingSlash` setting, so paths do
  not end in `/`. Comparing through `normalizePathname()` is still the safe
  habit.
- **Legal URLs:** `/terms` and `/privacy` permanently redirect to
  `/terms-of-service` and `/privacy-policy` (`next.config.ts`). The new slugs
  are registered on the Google Cloud OAuth consent screen: do not rename.
- **Admin link:** shown when `GET /api/me` says `is_admin`; not a
  client-side email check.
- **Streaming:** `streamChatSessionMessage` reads SSE `delta.content` for the
  answer and `delta.reasoning_content` for the backend's "thinking titles".
  Every title is kept on the message (`thinking`): the latest one replaces
  "Thinking…" until the first answer token, and afterwards a collapsed
  "Thinking · N steps" row expands to the full list. The backend saves the
  titles with the reply, so they survive a reload. These are the short titles
  Kael streams through its API, not raw reasoning. An in-stream
  `{"error": ...}` frame and an empty reply surface as errors (red notice with
  a Retry button), not as an empty bubble. There is no Stop button on purpose:
  the backend keeps generating, bills and saves the reply after a client
  disconnects, so a client-side stop would only hide a reply that still
  arrives.
- **Offline / reload mid-reply:** a stream that ends without `[DONE]`, or a
  request that fails at the network level, is `CONNECTION_LOST`, not an error.
  `followPendingReply` (`AppContext.tsx`) then polls `GET /api/chat/sessions/{id}`
  every 2 seconds (immediately on `online` / tab visible) and shows the
  `pending` reply until it is saved; opening a chat whose reply is still
  running does the same. If the server has neither a running reply nor the
  saved exchange, the message never arrived and the user gets Retry.
- **Model and thinking level:** the Playground's settings panel has a **model**
  picker (Kael Beta or Kael Pro Beta) and a **thinking** control. The model is
  chosen before a conversation's first message and then locked: the backend
  keeps a conversation on the model it started with, so the picker is disabled
  once a conversation exists (`modelLocked` in `PlaygroundPage.tsx`). Each model
  has its own thinking levels and its own remembered choice: Kael Beta has Low /
  High / Max (default Low), Kael Pro Beta has z-low / z-high (default z-low).
  The level is Kael's `reasoning_effort`, sent with each message, and only the
  active model's levels are shown; sending a level the model does not accept is a
  400. Both choices live in `localStorage` (`quan_playground_model`,
  `quan_playground_thinking_levels`, a JSON map from model id to level; the old
  single `quan_playground_thinking_level` is read once as Kael Beta's level and
  never written again). The two models and their levels are listed once, in
  `MODELS` in `src/lib/api.ts`. There is no "off": Kael always thinks.
- **Pictures:** the Playground's box has a paperclip button; pictures can also
  be pasted into it or dropped on it. Each is shrunk in the browser first
  (`src/lib/images.ts`: longest side 1568 px, JPEG), up to 4 per message and 20
  per conversation (both limits mirror `backend/app/chat_history.py`). A sent
  picture shows in the message and opens large on click; one loaded from a saved
  conversation is fetched with the login token when shown (`fetchChatImage`). A
  message with pictures has no Retry after a reload, because the pictures are no
  longer in the browser. Needs migration `0015` (table `chat_message_images`) to persist.
- **Files, voice, HTML preview, history line:** the same paperclip also takes text
  and code files, PDF and Word (.docx) files (up to 3 per message; limits mirror
  `backend/app/chat_files.py`). They are read in the browser (`src/lib/textFiles.ts`,
  `src/lib/docs/`, no library; the file is not uploaded) and their text goes into the
  message inside `<attached_file>` blocks. A document too long for one attachment is
  cut at a page or paragraph and the cut is named. Unsent attachments are dropped
  when another chat is opened. The microphone button records up to 2 minutes, sends
  the audio to `POST /api/chat/transcribe` and puts the text in the box
  (`src/lib/voice.ts`). An HTML code block in a reply has a Preview button
  (sandboxed iframe, `src/lib/htmlPreview.ts`). Once a conversation passes the history
  budget, a line shows where Kael's view starts (`src/lib/historyWindow.ts`). Checks:
  `npx tsx scripts/test-docs.ts`.
- **Admin balance:** the Admin page's Overview tab has an "Add to my balance"
  card (quick amounts and a custom amount), and the admin's own row in the
  Developers table has Credit buttons (no Suspend).
- **Playground layout:** `AppShell` gives the Playground its own full-height
  shell (one viewport tall, 82px navbar offset, one-line `LegalBar compact`,
  no page scroll). The page fills `h-full`; do not reintroduce a calc() height.
  The input is a multi-line textarea (16px on phones so iOS doesn't zoom),
  Enter sends on desktop, newline on touch.
- **Docs (`/docs`, `/docs/<slug>`):** one page per topic, in a persistent
  frame. Files, all under `src/components/docs/` unless noted:
  `nav.ts` is the table of contents and the page registry (slug, sidebar
  title, H1, and the description that is both the lead paragraph and the meta
  description); `content.tsx` maps each slug to its body; `pages/*.tsx` hold
  the bodies (`start`, `build`, `platform`, `console`, `help`);
  `primitives.tsx` is the kit (callouts, tables, tabbed code blocks with a
  copy button, steps); `highlight.tsx` is a small dependency-free syntax
  highlighter (colors are `--color-code-*` tokens in `globals.css`);
  `DocsShell.tsx` is the frame (sidebar, mobile section picker, "On this
  page") mounted by `app/docs/layout.tsx`, so it stays mounted between pages;
  `components/pages/DocsPage.tsx` renders one page by slug; `facts.ts` holds
  every price, limit and contact detail the pages quote. To add a page: add
  its entry in `nav.ts`, write the body in `pages/`, register it in
  `content.tsx`. Link between pages with `docsPath(slug)` from
  `lib/routes.ts` (or `docsHref` in `nav.ts`), never a typed path. "On this
  page" is built from the `<H2 id>` headings in the page. The page text was
  written from the backend code, not from the old docs: when an endpoint,
  limit, error code or console page changes, change the matching docs page in
  the same change. Never name the upstream models or providers in docs (the
  rule in `AGENTS.md`), and never describe how Kael produces an answer
  (steps, passes, call counts): the "About Kael" page was rewritten for that
  reason on 2026-10-08, and the stream's filler titles use neutral wording.
- **Prices and model facts.** `backend/app/models/kael/config.py` is the source
  of truth (the backend also serves the numbers at `GET /api/config`). The
  frontend reads them from **one file**, `components/docs/facts.ts` (`BETA`,
  `PRO_BETA`, and the shared `KAEL` limits), and every page that quotes a
  price imports from it: all the docs pages, `PricingPage.tsx` (price card
  and both comparison rows), `HomePage.tsx`'s price card, `UsagePage.tsx`'s
  top-up estimate, and the `app/page.tsx` and `app/pricing/page.tsx` metadata.
  **To change a price: change the backend, then `facts.ts`. Nothing else.**
  Two exceptions still hold their own copy: `TermsPage.tsx` (legal text; the
  owner reviews every wording change, and it currently states only Kael Beta's
  price) and the competitor rows in `PricingPage.tsx`. The model list for the
  Playground (`MODELS` in `src/lib/api.ts`) repeats the ids, names and levels
  but no prices; keep it in step with `facts.ts`.
- **Describe what a model is for, never how it works.** Customer-facing text
  (docs, pricing, the Playground, the public `GET /api/config` catalog) must not
  mention drafts, fusion, review passes or how many model calls a request makes.
  Kael Pro Beta is "the most thorough model, for the hardest problems, priced
  higher per token", nothing more.
- **Competitor prices on `/pricing` go stale by themselves.** The rows for
  GPT-6 Astra/Sol, Claude Opus 5.5, Claude Fable 5.1 and Kimi K3 are published
  list prices checked on 2026-09-28 (dated in the page copy). Nobody updates
  them automatically. Re-check each provider's own pricing page and change the
  `COMPARISON` array and the date in `PricingPage.tsx` together, or the page
  ends up quoting a competitor's old price.
- **Sitemap and robots:** the sitemap lists `/`, `/pricing`, `/docs` and every
  `/docs/<slug>` (generated from `components/docs/nav.ts`), the two legal
  pages and `/login`. `/login` is also `noindex`, so Search Console can report
  "submitted URL marked noindex" for it; drop it from `sitemap.ts` if that
  is unwanted. `robots.ts` deliberately does not disallow `/login`, because a
  blocked crawler can never see its `noindex` tag.
- **Dead payment UI:** the top-up button does nothing; no payment
  processor exists.

## Design system (`src/app/globals.css`)

- Tokens (Tailwind theme colors): `bg`, `ink`, `ink-2`, `ink-3`, `line`,
  `line-soft`, `surface`, `surface-2`, `hero`, `code-bg`, `accent-blue`
  (+ hover/soft/border), `accent-red`, `danger`, `success`, `warning`
  (each with soft/border). Font: Inter (sans), JetBrains Mono (mono).
  Use tokens, not raw hex or old slate/blue palette classes.
- Shared component classes (in `@layer components`, so Tailwind utilities
  override them): `.page-eyebrow`, `.page-title`, `.page-lead`, `.stat-card`,
  `.table-card`, `.data-table`, `.badge-pill`, `.tab-group`, pill buttons
  (`.btn-pill`, `.btn-pill-light`), the conic glow focus ring, glass
  header/drawer blur.
- Typography is near-universally weight 500; avoid heavy weights.
- Corner radii are generous (`rounded-2xl` for cards, `rounded-xl` for
  controls).
- **Brand mark:** `BrandMark.tsx` is a 4x4 grid of black shapes with one red
  cell, sitting before the wordmark "uancis" so they read "Quancis". The
  black shapes use `currentColor` (turns white on the dark hero); the red is
  a fixed color. Do not replace it with a letter "Q". The transactional
  emails rebuild the same mark from table cells (`backend/app/auth_email.py`).
- **Navbar:** transparent over the home hero, frosted-glass pill once scrolled
  and always on inner pages. Fixed position, so page layouts offset for it
  (`AppShell` does this; the Playground uses a smaller offset, see above).
- **Hero:** `HeroCanvas.tsx` is an instanced Three.js box grid with wave
  motion and pointer lift, occasional red boxes echoing the logo. Wrapped in
  try/catch; without WebGL the hero shows its flat dark background.
  **Pointer tracking is attached to `window`, not the canvas**, with a bounds
  check against the hero. The canvas sits behind the hero text (`-z-10`), so
  listeners on it never saw pointers over the headline, paragraph, buttons
  or nav. Listeners are passive and never `preventDefault`, so scrolling,
  clicks and text selection are untouched. Mouse leaving the hero or window
  releases the lift at once; touch fades out over about 1.2 s. On touch the
  browser may take a vertical drag for page scroll (`pointercancel`); that is
  intended, the hero must stay scrollable.
- Known visual inconsistency: the Playground got only a color remap, not the
  full card/table styling that the console pages (Dashboard, API Keys, Admin,
  Usage, Account) have.

## Brand assets

`src/app/icon.svg` (favicon), `apple-icon.png`, `opengraph-image.png` all
show the current brand mark.
