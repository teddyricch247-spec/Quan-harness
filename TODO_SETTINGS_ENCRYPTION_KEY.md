# ❌ NOT DONE YET — set SETTINGS_ENCRYPTION_KEY in Render

> Delete this file once you've done the steps below.

## Why

The new Settings (BYOK) feature encrypts every provider/API key you save (DeepSeek,
GitHub, Vercel, Tavily, ...) before it touches the database. `SETTINGS_ENCRYPTION_KEY`
is the one master secret that makes that encryption work — without it set in Render,
the backend will refuse to boot.

## Steps

1. **Push this code to GitHub** (your usual GitSync workflow) so Render picks up the
   new `settingsStore.js`, `routes/settings.js`, and the `Settings.jsx` page.

2. **Set the env var in Render:**
   - Render → your backend web service → **Environment** tab
   - Add a new variable:
     - Key: `SETTINGS_ENCRYPTION_KEY`
     - Value:
       ```
       59ffcdf81665d95a82a27616a3eea41d382ec7a358707129c922d915bd4a183f
       ```
   - Save

3. **Deploy.** Saving the env var alone doesn't redeploy — either push a commit
   (auto-deploy) or Render → **Manual Deploy → Deploy latest commit**.

4. **Check the logs** for a clean boot. If `DEEPSEEK_API_KEY` / `GITHUB_TOKEN` / etc.
   were still set in Render's env from before, you'll see lines like
   `Settings: imported 'deepseek' provider from legacy .env vars` — that's the
   one-time migration into the new encrypted tables.

5. **Open the app → Settings** (linked from the Projects page header) and confirm your
   providers/keys show up. Add anything that didn't migrate.

## ⚠️ Before you delete this file

The key value above is now committed to your git history the moment you push this
file — deleting the file later removes it from the working tree, **not** from history.
That's fine for a personal, single-user project like this one, but if it ever bothers
you (e.g. the repo becomes shared or public), generate a fresh key and update it in
Render — you don't need to touch git history to rotate it, just don't leave the old
one lying around in a file like this again.
