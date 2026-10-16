# Legal documents: status, decisions and hand-off (Terms of Service + Privacy Policy)

**Status (2026-10-13): both documents were rewritten in full** (`frontend/src/components/pages/TermsPage.tsx`, 24 sections, and `PrivacyPage.tsx`, 17 sections, "Last updated: October 13, 2026"). They describe the product as it will be when the payment processor goes live, including features that are still to be finished before launch (see "Must be true at launch").

I am not a lawyer. Everything below that says "for your lawyers" is a question for a South African attorney, not an answer.

---

## 1. What changed, against the earlier list of needed changes

| # | Earlier point | Now |
|---|---|---|
| 1 | Playground and API are different | Defined in Terms §4 and §9, Privacy §2, §8, §9. API text is never stored; Playground conversations are, until deleted. |
| 2 | No training | Terms §9, Privacy §4. States that providers are chosen on a "do not store, do not train" basis and that this relies on their own statements. |
| 3 | Credits | Terms §6. Not money, no cash value, not withdrawable, not transferable, only usable on Quancis. 12-month expiry, oldest credits first, recorded as "Expired credits". |
| 4 | Payment processor and refunds | Lemon Squeezy as Merchant of Record: Terms §7 and §8, Privacy §2 and §6. Whop and the 72-hour allocation text are gone. |
| 5 | Cache discount wording | Terms §6: the cached rate is fixed ($0.60 and $1.60 per 1M tokens); what varies is how much of a request is served from cache. |
| 6 | Contact details | `support@quancis.space` (help, billing, refunds) and `response@quancis.space` (privacy, legal, Information Officer, deletion). No personal Gmail address anywhere. |
| 7 | Effective date and version | "Last updated: October 13, 2026" on both pages. 14 days' email notice for material changes (Terms §20, Privacy §16). |
| 8 | Scope | Both documents say they cover the platform, the API and the Playground only; Quan Harness and Quan Chat have their own terms. |
| 9 | Data recipients and location | Recipients named by role and, for infrastructure, by vendor (Vercel, Render, Supabase, Resend, Lemon Squeezy, Google, GitHub). AI providers are not named. Supabase is in US East. |
| 10 | Open-ended retention | Every kind of data has a stated period (Privacy §8). |
| 11 | Cookies and analytics | No analytics or advertising cookies (the code has none). Local storage is for sign-in and preferences. |
| 12 | Account deletion | A delete button exists on the Account page (`DELETE /api/account`). Email requests are completed within 30 days. |
| 13 | Smaller items | "OpenAI-compatible" softened (Terms §4); 18+ (Terms §3); rate limits mentioned without numbers (Terms §5). |

Website pages that summarise these rules and must be edited on the day you publish, because this repo does not contain them: `www.quancis.space` `/legal` ("What Kael Does With Your Requests"), the `/kael` "Your data" section and FAQ, and `/about`. They must not say "15 minutes", "whop", or anything the documents no longer say. The docs page inside this repo (`components/docs/pages/platform.tsx`, "Data and privacy") was updated.

---

## 2. Decisions taken by default (you did not answer these; change them if wrong)

Your answers to the code questions on 2026-10-13 settled prices, expiry, deletion, the 15-minute claim and the safety screening. The rest of the earlier question list was not answered, so the documents use the defaults below.

- **Q1** Only prepaid Kael credits are sold. Harness and Chat get their own terms.
- **Q2** Still an unregistered sole proprietorship. No VAT or tax number is shown.
- **Q3** The address "Sekhukhune 1124, Limpopo, South Africa" is published in both documents.
- **Q4** Both inboxes are real and checked.
- **Q9** Credits we add free of charge are ordinary credits (they expire) with no cash value, and are not refundable.
- **Q10** A request that starts positive may finish below zero; the negative amount is netted against the next credits.
- **Q11** Fixed top-ups ($25, $50, $100), tax added at checkout by Lemon Squeezy.
- **Q12 to Q16** Refund of unused credits within 14 days of the purchase (the unused part only, oldest credits counted as used first); billing errors on our side are always corrected or refunded; leftover balance of an account closed for violating the Terms is forfeited; reply within 5 business days.
- **Q19** Flagged content: kept until reviewed, and up to 90 days after enforcement action; not reused.
- **Q21** Account deletion done within 30 days of an emailed request (immediately by button); financial records five years; usage, ledger and agreement records are deleted with the account.
- **Q22** Server logs: "the limited periods their services keep them, typically days to a few weeks". **Check this** against Render, Vercel and Supabase on your plans before publishing.
- **Q25** Infrastructure vendors are named; AI providers are not (your rule).
- **Q26, Q27** No marketing emails, no analytics.
- **Q28** 14 days' email notice for material changes.
- **Q29** South African law and courts, with consumers keeping their own country's mandatory rights.

Added by me without being asked (each is a promise or a rule; keep or delete): one account per person (Terms §5); the AUP items on probing internal components, sharing keys and training competing models (Terms §10); an offer of a refund of unused credits if we stop the Service altogether (Terms §20); the statement that the 14-day refund is meant to cover the seven-day cooling-off of ECTA s44 (Terms §8); "we will not charge or pursue you for credits already used if a payment is refunded", from your original refund text (Terms §8); the carve-out from the indemnity for our own gross negligence (Terms §17); a person reviews a flag before enforcement beyond a block and a pause (Privacy §3, §15).

---

## 3. For your lawyers

1. **CPA section 63 (prepaid credit).** South Africa's Consumer Protection Act sets a longer minimum validity for prepaid certificates, vouchers and credits (three years as I read it). You chose 12 months and said you do not mind the risk. The Terms say the expiry does not take away rights that cannot be waived (Terms §6 and §8), which probably means the longer period wins anyway for a South African consumer. Ask whether to (a) keep as is, (b) use three years, or (c) add an explicit South African carve-out.
2. **"Credits are not money".** Check that the wording in Terms §6 holds up: no cash value, not withdrawable, not transferable, Quancis only, displayed with a "$" sign for convenience. In particular check the sentence that the price of credits "tracks the US dollar amount you pay", the "not electronic money / stored-value" statement, and whether anything is needed for Lemon Squeezy's own rules.
3. **Refunds and cooling-off.** Check Terms §8 against ECTA s44 (seven days, distance contracts) and s42 exclusions, the CPA, and the EU/UK 14-day withdrawal right for digital content (not addressed beyond the general "rights that cannot be waived" sentence). Lemon Squeezy's Buyer Terms give refunds at its sole discretion, and the Terms say so.
4. **Merchant of Record structure.** The Terms say the purchase contract for credits is concluded through Lemon Squeezy, while the Service itself is provided by you. Check that this split is described correctly, who is the seller for consumer-law purposes, and the effect of Lemon Squeezy's seller terms on the refund and chargeback wording.
5. **Limitation of liability and indemnity** (Terms §16, §17): three months of payments as the cap, and the carve-outs. Check against the CPA (sections 48 to 61, plain language, unfair terms, no exclusion of liability for gross negligence).
6. **Plain language and unfair terms (CPA s22, s48, s49).** The Terms are consumer terms for South African users. Notice requirements for risky or unusual terms (the credit expiry, the loss of credits on account closure, the indemnity) may need to be drawn to the user's attention more prominently, for example at checkout.
7. **POPIA.** Check: the Information Officer (a sole proprietor is the responsible party and the Information Officer; the documents do not say whether the Information Officer is registered with the Information Regulator, which the law expects); the lawful grounds paragraph; operator versus responsible party for API customers who send personal information of others (Privacy §5 offers a data processing agreement); cross-border transfers (Privacy §7: US database, providers in other countries; section 72 conditions); retention of records (five years for tax records is my reading of the Tax Administration Act); automated decision-making (Privacy §15; section 71).
8. **GDPR and UK GDPR.** The documents say you "aim to honor" those rights. If you knowingly sell to people in the EU or UK, ask whether an EU/UK representative and standard contractual clauses for the US and other transfers are needed, and whether the GDPR rights in Privacy §10 are complete (restriction, portability, objection, the right not to be subject to automated decisions).
9. **Reporting of child sexual abuse material** (Terms §11, Privacy §3): South African law (the Films and Publications Act and the Criminal Law (Sexual Offences) Act) creates a duty to report. Check the wording and the retention it implies.
10. **ECTA section 43 information.** Terms §24 gives name, legal status, address, contact details, website and the price, payment and refund information. Not stated: VAT number (if registered), membership of any self-regulatory or accreditation body, any code of conduct subscribed to. Check what the law wants shown.
11. **Notices and "domicilium"** (Terms §22): the postal address is used as the address for service. Check this is fine for an unregistered sole proprietorship that is a person living at that address.
12. **Beta and "as is"** (Terms §4, §15): check that the disclaimers are enforceable against consumers, and the "not for high-risk use" paragraph.
13. **Content and output ownership** (Terms §9): the statement that you own 100% of the output "subject to compliance", and the no-originality-guarantee wording.
14. **Provider statements** (Terms §9, §13, Privacy §4). The text says requests go only to providers that state they do not keep prompts (beyond transient processing and short-lived technical caches) and do not train on them, and that you cannot audit this. This is true only while the upstream setting described in `backend/README.md` ("Upstream data policy") is on and the router account's own privacy settings are right (see section 4). A lawyer should look at whether "state that" is accurate enough.
15. **Whether to name the providers.** The documents name only infrastructure vendors. If a regulator or Lemon Squeezy asks, the answer is a list of recipients by category and the contracts behind them.

---

## 4. Must be true at launch (engineering and owner actions)

These are statements in the documents that are not yet true today, or depend on a step only you can take.

| What the documents say | State | What to do |
|---|---|---|
| Automated safety screening, flagged content kept until reviewed and up to 90 days after enforcement | **No screening code exists.** The database refuses to store API text (migration 0010). | Build screening and a place to keep flagged content (and decide how it interacts with 0010), or change both documents. You said it will be built before launch. |
| Playground diagnostic records deleted with the conversation and after 30 days | Done. Migration `0016` is fully applied (2026-10-15) | Nothing. The first daily run after the deploy deletes diagnostic rows older than 30 days. |
| Credits expire 12 months after they are added | Code done and tested. Migration `0017` applied on 2026-10-15 | Nothing more; nothing can expire before late 2027. Run the admin dry run (`POST /api/admin/expire-credits`) after deploying. |
| Providers do not keep or train on prompts | Code done (`data_collection: "deny"`); **never run against the real router** | After deploying, make one real request in the Playground and one through the API and check that each succeeds. If a model has no provider that meets the rule, requests to it fail with a 503 (that is the intended behaviour). Also check the router account's own privacy and logging settings (no storing of prompts or answers). |
| Delete account | Code done on the backend and the Account page; works without the migrations | After deploying, test with a throw-away account. |
| Refunds remove credits; "Expired credits" lines | Expiry is built; **no payment or refund code exists** | Build checkout, the webhook and the refund handling (`PLAN.md` D1) to match Terms §7 and §8. |
| Last updated date and version | October 13, 2026 | On the day you publish, change the date on both pages and `TERMS_VERSION` / `PRIVACY_VERSION` in `backend/app/config.py` together, and email existing users (Terms §20). |
| Three old ledger rows with your personal email in their description | Fixed on 2026-10-15: they now read "Admin credit adjustment" (amounts unchanged) | Nothing. |
| Logs retention "days to a few weeks" | Unverified | Check the log retention of Render, Vercel and Supabase on your plans, and adjust Privacy §8 if different. |

## 14. Attached files and voice typing (added 2026-10-14)

- **Attached text, code, PDF and Word files** are read in the user's browser (the file itself is not uploaded); only the extracted text is sent, as part of the message text, so they are stored with the Playground conversation and sent to the model on every later turn, exactly like typed text. The Privacy Policy's description of what a conversation contains should say files the user attaches are included.
- **Voice typing:** a recording is sent to a speech-to-text service (through the same router provider as the chat models) and turned into text, which the user can edit before sending. Quancis does not store, log or reuse the audio and does not send it to Kael; only the resulting text is used, and only if the user sends it. The Privacy Policy's data recipients (section 9 above) should name speech-to-text processing and say the audio is not kept by Quancis. Whether the transcription providers keep audio is not something this code controls or verified; check OpenRouter's current terms and the providers it routes to before promising anything about retention. Note also that the chat requests carry `data_collection: "deny"` (section 4) but the transcription request (`backend/app/transcription.py`, `build_request_body`) does not, and OpenRouter's speech-to-text documentation describes its `provider` field as provider-specific passthrough, not the routing object, so whether the same rule can be applied there is unverified. Privacy section 4 says every request is configured that way: either confirm it works for transcription (one real voice clip after adding it) or soften that sentence.
- Voice typing is free to the user (Quancis pays the small per-second cost). Say nothing about price in the legal text.

---

## 5. How to keep the documents true

Every promise above is tied to a place in the code (`AGENTS.md`, section 2, "What the Terms and Privacy Policy promise is tied to code"). When you change retention, deletion, expiry, providers or prices, change the two pages in the same commit.
