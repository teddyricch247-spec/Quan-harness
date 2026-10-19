# The agent's browser — setup (supersedes §3c of YOUR_SETUP_CHECKLIST.md)

What changed, in one paragraph: the browser is now **on by default** (`AGENT_BROWSER_ENABLED=true`). Whether it works depends
on one thing only — whether Chromium is installed on the host. Where it isn't (the plain Python runtime), the browser tools
are simply not offered and nothing breaks. A model that **can't read images** still gets the browser: navigate, click, type
and console logs all work, and `browser_screenshot` returns a text outline of the page (visible text plus every clickable
element with a selector) instead of a picture.

## Do this on Render (about 15 minutes)

1. **Run the backend from the Docker image.** `backend/Dockerfile` installs Playwright and Chromium. The plain Python runtime
   cannot (Chromium's system libraries need root).
   - Open your backend service → **Settings**. If the runtime/language can be switched to **Docker**, do that.
     (I could not confirm from Render's docs that an existing service can be switched.)
   - If it can't: create a **new Web Service** from the same repo with **Runtime: Docker**, **Root Directory: `backend`**,
     copy every environment variable across, then either give it the old service's name (delete the old one first) or
     update the places that hold the URL: `BACKEND_PUBLIC_URL`, Vercel's `NEXT_PUBLIC_API_URL`, and the GitHub OAuth
     callback URL.
   - Remove the old Build and Start commands if Render keeps them — the Dockerfile has both. If Render says it can't
     find the Dockerfile, set **Dockerfile Path** to `backend/Dockerfile` and the **Docker build context** to `backend`
     (I couldn't confirm from Render's docs whether those paths are relative to the root directory or the repo).
   - Nobody has built this image yet. If the build fails, the log names the step; send it to me.
2. **Pick an instance with enough memory.** Render's **Standard** web service has 2 GB RAM; **Starter** has 512 MB. The
   backend (it imports litellm) plus Chromium will not fit in 512 MB. Set `AGENT_BROWSER_MAX_PAGES=1` if you stay tight.
3. **Check the environment variables.** `SPRITES_API_TOKEN` must be set. Delete `AGENT_BROWSER_ENABLED=false` if you ever
   added it; you don't need to add `=true` (it's the default).
4. **Deploy, then check the logs** for "The agent's browser could not start". If that line appears, the message after it
   says why (missing library, out of memory).

The browser also needs, for every project: a workspace (Sprite) that exists, and a **successful deploy** (the agent can call
`preview_rebuild` itself).

## Check that it works

Ask the agent in a throwaway project: *"Open the preview in your browser and tell me the page title and the first heading."*
With a text-only model you should get the title from `browser_navigate` and the heading from the text outline.

## Two safety checks nobody has run yet (do them once, in a throwaway project)

1. **Does the Sprite pass the Sprites token on to the app?** The browser sends `Authorization: Bearer <Sprites token>` to the
   project's own Sprite. If the Sprite's edge forwards that header to the app inside, app code could read the token. Ask
   the agent to add a route `/headers` that returns **only** whether an `authorization` header is present (`present` /
   `absent`) — **never its value** — then open it with the browser. Expected: `absent`. If it says `present`, switch the
   browser off (`AGENT_BROWSER_ENABLED=false`) and tell me.
2. **Does the network wall hold?** Ask the agent to add a page that tries `fetch("https://example.com")` and
   `fetch("http://169.254.169.254/")` and shows the result, then read the console logs. Expected: both fail, and the console
   shows them as blocked or failed. If either succeeds, switch the browser off and tell me.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_BROWSER_ENABLED` | `true` | Master switch. No effect where Chromium isn't installed. |
| `AGENT_BROWSER_MAX_PAGES` | `2` | Pages open at once across all sessions (memory). |
| `AGENT_BROWSER_ALLOWED_HOSTS` | empty | Extra hosts the page may reach (exact hosts or `*.domain`). |
| `AGENT_VISION_MODELS` | empty | litellm strings of models you know read images; they get real screenshots instead of the text outline. |
