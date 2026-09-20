# Deployment

Matches the spec's own tech stack (§2): orchestration backend on Render,
frontend on Vercel, Supabase for everything data/auth/secrets. Do
`docs/YOUR_SETUP_CHECKLIST.md` first — this assumes that's done.

## Backend → Render

1. Push this repo to GitHub (or GitLab/Bitbucket).
2. In Render: **New → Web Service**, connect the repo.
3. **Root Directory:** `backend`
4. **Runtime:** Python 3
5. **Build Command:** `pip install -r requirements.txt`
6. **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
7. **Environment variables** — add every key from `backend/.env.example`, with
   real values. Set `BACKEND_PUBLIC_URL` to the `https://your-service.onrender.com`
   URL Render assigns you (you'll see it after the first deploy — update this
   var and redeploy once you know it, since the GitHub OAuth callback URL
   depends on it matching exactly what you registered in your GitHub OAuth App).
8. Deploy. Check `https://your-service.onrender.com/health` returns
   `{"status": "ok", "phase": 1}`.

**Note on cold starts:** Render's free tier spins the service down after
inactivity and takes ~30-60s to wake back up on the next request. Fine for
development; worth a paid instance before this is public-facing, since that
delay hits every cold API call, not just one page load.

## Frontend → Vercel

1. In Vercel: **Add New → Project**, import the same repo.
2. **Root Directory:** `frontend`
3. Framework preset: Next.js (auto-detected).
4. **Environment variables** — add every key from `frontend/.env.local.example`,
   with real values. `NEXT_PUBLIC_API_URL` should point at your deployed Render
   backend URL from above.
5. Deploy. Vercel gives you a `https://your-project.vercel.app` URL (or your own
   domain if you've attached one).

## Wiring the two together (do this after both are deployed)

Both pieces need to know about each other's real URLs — none of this works with
placeholder/localhost values left in production:

- **Backend env vars:** `FRONTEND_URL` → your Vercel URL. `CORS_ALLOWED_ORIGINS`
  → include your Vercel URL (comma-separated if you have more than one, e.g. a
  preview deployment domain too).
- **Frontend env var:** `NEXT_PUBLIC_API_URL` → your Render URL.
- **Supabase → Authentication → URL Configuration:** Site URL and Redirect URLs
  → your Vercel URL. This is what email confirmation and password-reset links
  point at — get this wrong and those links 404 or redirect to localhost.
- **GitHub OAuth App's callback URL:** `<your Render URL>/connections/github-credential/oauth-callback`.
  Either update your existing dev OAuth App's callback (breaks local dev against
  it) or — recommended — register a second, separate OAuth App for production
  and use its client ID/secret in Render's env vars instead of your dev one's.

Redeploy the backend after changing any of its env vars (Render doesn't hot-reload
them). Vercel does this automatically on env var changes if you trigger a redeploy
from the dashboard.

## What's deliberately not here

No database migration automation, no Docker, no CI/CD pipeline config. Phase 1 is
about getting the data model and CRUD surfaces right, not about production
release engineering — add these once the app itself is worth automating the
release of. The RLS test suite in `backend/tests/` is the one piece worth wiring
into CI early (per §5's explicit requirement to run it on every PR touching
schema/policies), even before anything else is automated.
