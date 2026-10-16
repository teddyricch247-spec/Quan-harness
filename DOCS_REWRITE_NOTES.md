# Docs rewrite notes

`DocsPage.tsx` was **not edited**. It dates from when Quancis had several models and a different price list, so it needs a rewrite rather than patches. This is the checklist for whoever does it. Verify each fact against the backend on the day you write, since the backend is changing.

## Must be removed or corrected

1. **Vendor name in the Endpoints tab.** "DeepSeek" appears three times (the "Why Both Formats Exist" paragraph, a heading "DeepSeek Recommended Format Endpoints", and "DeepSeek's modern API specifications"). Remove the whole paragraph. Project rule: upstream providers are never named to customers.
2. **Availability** says "Fully Available (GA)". Kael is in beta.
3. **Image input** is described as unsupported ("Text Content Only"), but the product is advertised as text and images and the backend accepts image parts. Document what actually works.
4. **Tools / JSON mode.** The parameter table lists `tools`, `tool_choice`, `max_tokens` as inert. Check each against the backend and state what is supported. `response_format` / JSON mode is not mentioned at all.
5. **Endpoint count.** Says "nine explicit routing endpoints" and lists six. The backend has eight routes: chat completions, responses, messages, and models, each under `/v1` and `/pro/v1`. **Decided 2026-10-08: `/pro/v1` is retired.** The per-model prefixes `/kael-beta/v1` and `/kael-pro-beta/v1` replace it and are documented on the Endpoints page.
6. **Anthropic SDK example** uses `baseURL: 'https://api.quancis.space/v1'`. The Anthropic SDK adds `/v1/messages` itself, so the base should most likely be `https://api.quancis.space`. Test with the real SDK. Add a full Messages example (model, `max_tokens`, streaming, version header note).
7. **Rate limits.** Docs say up to 100 concurrent requests and no per-minute cap. The backend enforces 150 requests per minute and 30 concurrent per user (set 2026-10-03). Add the **429** rows to the error table (`rate_limit_exceeded`, `concurrency_limit_exceeded`).
8. **Caching.** "Caches persist automatically across requests" needs the real window. The cache is the AI providers' own short-lived technical cache and its lifetime is theirs, not ours; say so without a number. (The Privacy Policy no longer says "15 minutes" anywhere: nothing in our systems ever held API text for 15 minutes, because it is never stored.)
9. **Leftover multi-model wording.** "see the rate card above for each model's exact rates", "see Models & Pricing above for exact per-model cached rates" (twice), "that model's standard input rate", and "Keys grant uniform access to all models". There is one model. The rate card is also on a different tab, not "above".
10. **"100% wire-compatible"** (Quickstart). Replace with a statement of what is and is not honoured.
11. **Environment variable names** are inconsistent: `QUANCIS_API_KEY` on the home page vs `QUAN_API_KEY` in the Vercel AI SDK example.
12. **Schema details.** `id` is described as "deterministic" (it is not); `input` is described as an array only, but Responses also accepts a plain string and the website's own example sends one.

## Missing and worth adding

- **Thinking level**: `reasoning_effort` with `low` (default), `high`, `max`; the `reasoning.effort` form for Responses; what an invalid value returns (400). Leave out Off until it exists.
- **Quickstart order**: create account, add credits, create key, make a call. State that a zero balance returns 402.
- Context window (1M tokens), input and output types, knowledge cutoff, maximum output length.
- Streaming for all three formats, including usage fields.
- The `id` on each response and a note to log it when contacting support.
- Data handling summary matching the Privacy Policy (API text is not stored; Playground conversations are, until deleted; diagnostic records are deleted with the conversation and after 30 days). The "Data and privacy" page in `components/docs/pages/platform.tsx` was brought in line on 2026-10-13.
- Links to Terms, Privacy, Contact, and the Kael page on the website. The docs currently have none.
- Beta stability note: what may change and how changes are announced; a changelog link.
- Status page or uptime statement, if you intend one.
- **Deep links.** Sections are tab state, not URLs, so "Prompt Caching" and "API Reference" in the footer cannot open the right section. Give each section its own anchor or route.

## Check on the same pass

- Price numbers must match the Pricing page and backend config (input $3.00, cached $0.60, output $10.00 per 1M, as of 2026-10-08).
- Remove the "Composite Intelligence Systems" explainer or align it with the website copy, so the two do not describe the product differently.
- Keep the new text consistent with the Terms (the Terms now say "designed to be compatible with the OpenAI and Anthropic request formats", Terms §4; see `LEGAL_UPDATES.md`).
