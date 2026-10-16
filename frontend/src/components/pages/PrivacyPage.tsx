import React from 'react';
import { BrandMark } from '../BrandMark';

export const PrivacyPage: React.FC = () => {
  return (
    <div className="min-h-[calc(100vh-8rem)] flex items-start justify-center px-4 py-12 sm:py-16">
      <div className="w-full max-w-3xl space-y-8">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <BrandMark size={44} />
            <span className="font-medium tracking-tight text-3xl sm:text-4xl text-ink">
              uancis
            </span>
          </div>
          <div>
            <h1 className="text-2xl font-medium text-ink tracking-tight">Privacy Policy</h1>
            <p className="text-xs text-ink-3 mt-1">Last updated: October 13, 2026</p>
          </div>
        </div>

        <div className="space-y-8 text-sm text-ink-2 leading-relaxed">

          {/* 1. Introduction & Scope */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">1. Introduction &amp; Scope</h2>
            <p>This Privacy Policy explains how Quancis (&quot;we,&quot; &quot;us,&quot; &quot;our&quot;) collects, uses, shares, keeps, and protects your personal information when you use platform.quancis.space, including the Kael API (the &quot;API&quot;) and the in-browser chat interface on the platform (the &quot;Playground&quot;) (together, the &quot;Service&quot;). Quancis is not a registered company; it is a trading name used by Response Mosese, an unregistered sole proprietor operating under the laws of South Africa, based in Limpopo, Republic of South Africa. Any reference to &quot;Quancis&quot; throughout this Policy refers to Response Mosese personally, trading as Quancis. Response Mosese is the &quot;responsible party&quot; for your personal information under South African law.</p>
            <p><strong className="text-ink">What this Policy covers.</strong> This Policy covers the Quancis platform, the API, and the Playground only. Other Quancis products, such as Quan Harness and Quan Chat, have their own privacy terms. This Policy forms part of our <a href="/terms-of-service" className="text-accent-blue hover:underline">Terms of Service</a>, and words such as &quot;Credits&quot; and &quot;Account&quot; have the same meaning here as there.</p>
            <p><strong className="text-ink">Laws.</strong> We primarily comply with South Africa&apos;s Protection of Personal Information Act 4 of 2013 (POPIA). If you are located in the European Economic Area, the United Kingdom, or another jurisdiction with its own data protection law (such as the GDPR), we also aim to honor the rights those laws provide, as described below.</p>
            <p><strong className="text-ink">At a glance.</strong> This is a summary. The sections below are the full policy.</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li>We collect what we need to run your account, bill you, and give you the Service: your name and email address, your usage and billing records, and, in the Playground, the conversations you have.</li>
              <li><strong className="text-ink">API requests are not stored.</strong> We do not save the text of requests you send through the API, or the answers to them. We keep only usage and billing records.</li>
              <li><strong className="text-ink">Playground conversations are stored</strong> in your account until you delete them or delete your account. A short diagnostic record of each Playground request is deleted together with its conversation and in any case after 30 days.</li>
              <li><strong className="text-ink">We do not train models on your content.</strong> Our AI requests are sent only to providers that state that they do not store your content beyond what is needed to produce the answer, and do not train on it.</li>
              <li>Automated safety screening exists. Content it flags is kept for review, as described in Section 3.</li>
              <li>We do not sell your personal information, and we do not send marketing emails.</li>
              <li>You can delete your account yourself, at any time, on the Account page. Section 9 explains what that deletes and what we keep.</li>
            </ul>
          </section>

          {/* 2. Information We Collect */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">2. Information We Collect</h2>
            <p>In this Policy, &quot;personal information&quot; means information that identifies you or relates to you, in the categories described below.</p>
            <p><strong className="text-ink">Account information.</strong> When you register, we collect your name and your email address, and a password if you sign up with email. Passwords are handled by our authentication provider and stored only in hashed form; we cannot read them. If you sign in with Google or GitHub, we receive the name and email address that account shares with us. We also keep the settings you choose in your Account, such as your display name, your theme, and whether you want low-balance email alerts. Our authentication provider keeps sign-in and security records for your Account, such as when you signed in.</p>
            <p><strong className="text-ink">Records of your agreement.</strong> When you accept our Terms of Service and Privacy Policy, we record which version you accepted, when, your IP address, and your browser type, so that we can show what was agreed.</p>
            <p><strong className="text-ink">API keys.</strong> For each API key you create, we store the name you give it, a short visible prefix, a hashed form of the secret, the model and thinking-level settings you choose for it, and the dates it was created, last used, and revoked. The full key is shown to you only once, when you create it, and we cannot recover it.</p>
            <p><strong className="text-ink">Usage records.</strong> For each request, whether it came from the API or the Playground, we keep the time, the model, the status of the request, token counts, the response time, which API key (if any) was used, and, if the request failed, a short technical error description. We make sure these descriptions do not contain your prompts or Kael&apos;s answers. These records show how much you used the Service; they do not contain the text of your requests or the answers.</p>
            <p><strong className="text-ink">Billing records.</strong> We keep your Credit balance and a ledger of every charge, purchase, adjustment, and expiry on your Account. Ledger entries carry a short description, such as &quot;Admin credit adjustment&quot; or &quot;Expired credits,&quot; and never contain your email address. You can see your billing history in your Account.</p>
            <p><strong className="text-ink">Payment information.</strong> Payments are processed entirely by our Merchant of Record, Lemon Squeezy. We do not collect, process, or store your payment card, bank account, or other financial account details. We receive confirmation details of your purchases, such as the order number, amount, currency, date, and the name, email address, and country you gave at checkout, so that we can add Credits and keep our accounting records. This information is handled by Lemon Squeezy under its own terms and <a href="https://lemonsqueezy.com/privacy" target="_blank" rel="noopener noreferrer" className="text-accent-blue hover:underline">privacy policy</a>.</p>
            <p><strong className="text-ink">Playground conversations.</strong> Conversations in the Playground are saved to your Account so that you can come back to them. A saved conversation includes your messages, Kael&apos;s answers, any pictures you attach, short summaries of the steps Kael shows while it works, a conversation title that is generated automatically, and the model and thinking level used. Pictures are stored with the conversation. Playground conversations are kept until you delete them or delete your Account. We do not use them to train our models (see Section 4).</p>
            <p><strong className="text-ink">Playground diagnostic records.</strong> For troubleshooting, each Playground request also creates a diagnostic record. It contains technical details (timings, status, sizes) and short, truncated excerpts of your latest message (up to 500 characters) and of the answer (up to 1,500 characters). A diagnostic record is deleted together with its conversation, and in any case 30 days after it was created (Section 8).</p>
            <p><strong className="text-ink">API requests.</strong> When you send a request through the API, we do not save your prompt or Kael&apos;s answer. We keep only the usage and billing records described above, and, for requests sent through the API, the diagnostic record holds only counts, timings, and status, never text. While a request is processed, its content passes through our servers and our AI infrastructure providers (Sections 4 and 6). Those providers may use a short-lived technical cache so that repeated content can be recognized and billed at the cached rate; how long that cache lasts is set by the provider, not by us. The one exception to what we keep is flagged content, described in Section 3.</p>
            <p><strong className="text-ink">Support messages.</strong> If you write to us, we keep your message, your email address, and what we need to answer you and deal with the matter.</p>
            <p><strong className="text-ink">Technical information.</strong> When you access our website or API, our servers and hosting providers automatically log standard technical information, such as your IP address, browser or client type, and request timestamps, for security, fraud prevention, and operational purposes. We also apply rate limits that count requests per account or per network address; those counters are kept only in the memory of our server and are discarded.</p>
            <p><strong className="text-ink">Cookies and local storage.</strong> The platform does not use advertising or analytics cookies or trackers. It uses your browser&apos;s local storage to keep you signed in, to remember your preferences, such as your selected model and thinking level, and to keep a copy of your basic profile details (such as your name, email address, and balance) so that pages load quickly. Our authentication provider, and Google or GitHub if you use them to sign in, may set their own cookies or storage as part of signing in. You can clear this data in your browser settings, but you will then be signed out.</p>
            <p><strong className="text-ink">Emails we send you.</strong> We send account and service emails, such as sign-up confirmation, password reset, security notices (for example, if someone tries to sign up or reset a password using your email address), billing and policy notices, a confirmation when you delete your account, and low-balance alerts if you turn them on. We do not send marketing emails.</p>
            <p><strong className="text-ink">What you send us.</strong> Your content may include personal information, including about other people. You decide what to send. We do not ask for special personal information (for example, health, religion, or biometric data), and we ask you not to send more than you need to. Sections 4 and 5 explain how we treat the content you send.</p>
          </section>

          {/* 3. Content Screening & Flagged Requests */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">3. Content Screening &amp; Flagged Requests</h2>
            <p>Requests and answers are screened automatically, using our own checks and the safety systems of our AI providers, for content that violates our Terms of Service, Section 10 (Acceptable Use). Content that is flagged as potentially harmful may be blocked before it is delivered.</p>
            <p>If a request or answer is flagged, we keep it, together with the details needed to identify the Account, until an administrator has reviewed it, and the associated Account may be paused while that review is under way. Where we take enforcement action, such as blocking an Account, we may keep the flagged content for up to 90 days afterwards as a record in case of a dispute or a legal claim. If a flag is found to be a false positive, it is cleared, the flagged content is deleted, and the Account is restored.</p>
            <p>Flagged content is the only content of API requests that we keep. We use it only to review the flag, take and record enforcement action, handle disputes, and comply with the law, including reporting to the police or another authority where the law requires it (for example, for child sexual abuse material). We do not use it to train models. Screening is automated and is not perfect; a person reviews a flag before we take enforcement action beyond blocking the request and pausing the Account.</p>
          </section>

          {/* 4. Model Training & How AI Providers Handle Your Content */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">4. Model Training &amp; How AI Providers Handle Your Content</h2>
            <p><strong className="text-ink">We do not use your prompts, your Playground conversations, your pictures, or Kael&apos;s answers to train or improve our models.</strong> If we ever wanted to, we would ask for your explicit opt-in first.</p>
            <p><strong className="text-ink">Our AI providers.</strong> To generate answers, the content of your requests is sent to third-party providers that run AI models for us (including a routing service that passes requests on to the model hosts). We do not name these providers, and which ones are used for a given request can change. We configure every request so that it can only be routed to providers that state that they do not store your content beyond what is needed to produce the answer (other than short-lived technical caching) and do not train on it. If no provider that meets this condition is available, the request fails instead of being sent to another provider.</p>
            <p><strong className="text-ink">Limits of this.</strong> We rely on what those providers state in their own terms and policies, and we cannot audit their systems or guarantee what they do. They handle content under their own terms and privacy policies. Providers may also be required by law to keep or disclose information.</p>
          </section>

          {/* 5. How We Use Your Information */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">5. How We Use Your Information</h2>
            <p>We use the information described above to:</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li>Create and manage your Account, sign you in, and keep your Account secure;</li>
              <li>Operate, maintain, and bill for the Service, including adding Credits after a purchase, deducting usage, and removing expired Credits;</li>
              <li>Generate answers to your requests by sending your content to our AI providers;</li>
              <li>Save your Playground conversations so you can return to them;</li>
              <li>Calculate cache hits and other technical and billing functions;</li>
              <li>Show you your usage, balance, and billing history;</li>
              <li>Keep the Service secure, prevent fraud and abuse, and detect and respond to violations of our Terms of Service, including through the screening described in Section 3;</li>
              <li>Provide support when you ask for it;</li>
              <li>Communicate with you, including account, billing, and policy notices;</li>
              <li>Keep the accounting and tax records that the law requires;</li>
              <li>Comply with legal obligations and respond to lawful requests.</li>
            </ul>
            <p>We do not routinely read your Playground conversations. We may look at them where needed to investigate abuse, to give you support you have asked for, or to comply with the law.</p>
            <p><strong className="text-ink">Lawful grounds.</strong> Under POPIA, we process your personal information because it is needed to conclude or perform our contract with you (the Terms of Service), because the law requires it (for example, tax records), because it protects a legitimate interest of yours, ours, or a third party&apos;s (such as keeping the Service secure and preventing fraud and abuse), or because you consented (for example, to optional emails). Where the GDPR applies, our grounds are, in the same way, performance of a contract, legal obligation, our legitimate interests in running and securing the Service (which we balance against your rights), and your consent where we ask for it. You can withdraw consent at any time (for example, by turning off low-balance alerts), without affecting what we did before.</p>
            <p><strong className="text-ink">Where we act for you.</strong> If you are a business and you send us personal information about other people (for example, your own users) through the API, you are responsible for having a lawful basis to do so. To the extent that we process that information on your behalf, we do so only to provide the Service to you, as described in this Policy. If you need a data processing agreement, contact us at <a href="mailto:response@quancis.space" className="text-accent-blue hover:underline">response@quancis.space</a>.</p>
          </section>

          {/* 6. How We Share Your Information */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">6. How We Share Your Information</h2>
            <p>We do not sell your personal information. We share information only with the following kinds of recipients, and only as needed:</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li><strong className="text-ink">Hosting and infrastructure providers</strong> that run our website and servers (currently Vercel and Render).</li>
              <li><strong className="text-ink">Database and authentication provider</strong> that stores our data and handles sign-in (currently Supabase).</li>
              <li><strong className="text-ink">Email delivery provider</strong> that sends our account and service emails (currently Resend).</li>
              <li><strong className="text-ink">AI infrastructure providers.</strong> To generate answers, the content of your requests is sent to third-party providers that run AI models for us, as described in Section 4. We do not name these providers.</li>
              <li><strong className="text-ink">Sign-in providers</strong> (Google and GitHub), if you choose to sign in with them.</li>
              <li><strong className="text-ink">Lemon Squeezy</strong>, our Merchant of Record, which receives the information needed to process your payment, taxes, and refunds. Lemon Squeezy handles payment information under its own terms and privacy policy.</li>
              <li><strong className="text-ink">Our advisers</strong> (such as lawyers and accountants), under duties of confidentiality, where needed.</li>
              <li><strong className="text-ink">Authorities and courts</strong>, where required to comply with a valid court order or other lawful legal request, or to report content as described in Section 3.</li>
              <li><strong className="text-ink">A successor</strong>, if our business is reorganized, incorporated, or transferred, in which case we will make sure this Policy continues to apply to your information.</li>
            </ul>
            <p>We are not responsible for how these third parties independently handle data on their own platforms; their use of your data is governed by their own privacy policies. We choose our providers with care and give them only what they need.</p>
          </section>

          {/* 7. International Data Transfers */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">7. International Data Transfers</h2>
            <p>Our database and authentication data are stored with Supabase in the United States (US East). Our servers are hosted with Render, and our website is delivered through Vercel&apos;s network; both operate data centers outside South Africa. Our AI infrastructure providers may process content in other countries. Because we rely on providers outside South Africa, your information may be transferred to and processed in other countries. We take reasonable steps to ensure such transfers are consistent with POPIA and, where applicable, GDPR requirements, including by using providers that are bound by contract or by law to protect personal information to a similar standard.</p>
          </section>

          {/* 8. Data Retention */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">8. Data Retention</h2>
            <p>How long we keep each kind of information:</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li><strong className="text-ink">Account information</strong> (name, email, settings) is kept for as long as your Account exists, and is deleted when you delete your Account.</li>
              <li><strong className="text-ink">Playground conversations,</strong> including pictures and the summaries of Kael&apos;s steps, are kept until you delete the conversation or delete your Account.</li>
              <li><strong className="text-ink">Playground diagnostic records</strong> are deleted together with their conversation, and in any case 30 days after they were created. The deletion of records that are 30 days old runs once a day.</li>
              <li><strong className="text-ink">API prompts and answers</strong> are not saved by us. Short-lived technical caching by our AI providers is governed by those providers.</li>
              <li><strong className="text-ink">Flagged content</strong> is kept as described in Section 3: until it has been reviewed and, where we take enforcement action, for up to 90 days afterwards. Flagged content that is cleared is deleted.</li>
              <li><strong className="text-ink">Usage records</strong> (the usage and billing figures described in Section 2) and <strong className="text-ink">billing records</strong> (your balance and ledger) are kept for as long as your Account exists, and are deleted when you delete your Account.</li>
              <li><strong className="text-ink">Records of your agreement</strong> to our Terms and Privacy Policy are kept for as long as your Account exists, and are deleted when you delete your Account.</li>
              <li><strong className="text-ink">Payment and tax records</strong> are held by Lemon Squeezy as Merchant of Record. We also keep the accounting and tax records that the law requires us to keep, such as reports and statements from Lemon Squeezy about sales and payouts, which can include the order number, amount, date, country, and the name and email address given at checkout, for as long as the law requires (generally five years in South Africa).</li>
              <li><strong className="text-ink">Technical logs</strong> (such as IP addresses) are kept by our hosting, database, and email providers for the limited periods their services keep them, which in our setup is typically days to a few weeks, and are then deleted or anonymized.</li>
              <li><strong className="text-ink">Support messages</strong> are kept for as long as needed to deal with the matter and any follow-up, and are then deleted.</li>
              <li><strong className="text-ink">Backups.</strong> Deleted information may remain for a short time in backups kept by our database provider, until those backups are overwritten in the provider&apos;s normal cycle. We do not use backups for anything other than recovering from a failure.</li>
            </ul>
          </section>

          {/* 9. Deleting Your Account & Your Data */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">9. Deleting Your Account &amp; Your Data</h2>
            <p><strong className="text-ink">Deleting a conversation.</strong> You can delete a Playground conversation yourself at any time from the conversation list in the Playground. That deletes the conversation, its messages and pictures, and its diagnostic record.</p>
            <p><strong className="text-ink">Revoking a key.</strong> You can revoke an API key at any time on the API keys page.</p>
            <p><strong className="text-ink">Deleting your account yourself.</strong> You can permanently delete your Account on the Account page. You will be asked to type your account email address to confirm. The deletion takes effect straight away and cannot be undone. It:</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li>revokes all of your API keys;</li>
              <li>deletes your Playground conversations, messages, and pictures, your diagnostic records, your usage records, your Credit balance and billing history, the record of your agreement to the Terms and this Policy, and your login and account information;</li>
              <li>forfeits any Credits left on the Account, which have no cash value and are not refunded (see our Terms of Service, Sections 8 and 12), so ask for any refund you are entitled to before you delete; and</li>
              <li>is confirmed to you by a short email, if you have an email address on file.</li>
            </ul>
            <p><strong className="text-ink">Deleting your account by request.</strong> You can also ask us to delete your Account by emailing <a href="mailto:response@quancis.space" className="text-accent-blue hover:underline">response@quancis.space</a> from your account email address. We will complete the request within 30 days, and may ask you to verify your identity first.</p>
            <p><strong className="text-ink">What we keep after deletion.</strong> Information that the law requires us to keep (Section 8: accounting and tax records) stays; Lemon Squeezy keeps its own payment records as Merchant of Record; content flagged by our safety screening that is still under review, or is kept as a record of enforcement action, stays for the period in Section 3; and backups are overwritten as described in Section 8. After that, we do not keep your personal information, except in the case of a legal obligation or a dispute.</p>
            <p><strong className="text-ink">Administrator accounts</strong> cannot be deleted from the Account page and are removed by us directly.</p>
          </section>

          {/* 10. Your Rights */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">10. Your Rights</h2>
            <p>Subject to applicable law, you have the right to:</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li>Access the personal information we hold about you, and ask us to confirm whether we hold any;</li>
              <li>Correct inaccurate or out-of-date information (you can change your display name in your Account);</li>
              <li>Request deletion of your account and associated personal information (Section 9);</li>
              <li>Object to certain processing of your information, and withdraw a consent you gave;</li>
              <li>Ask us to restrict how we use your information while a question about it is being settled, where the law gives you that right;</li>
              <li>Where GDPR applies to you, request portability of your data: on request, we provide the personal information you gave us and your saved conversations in a commonly used electronic format;</li>
              <li>Not be subject to a decision made only by automated means that has legal or similarly significant effects on you (Section 15).</li>
            </ul>
            <p><strong className="text-ink">How to exercise your rights.</strong> You can do much of this yourself in your Account. For anything else, email us at <a href="mailto:response@quancis.space" className="text-accent-blue hover:underline">response@quancis.space</a> from your account email address. We will respond within 30 days, and may ask you to verify your identity before completing certain requests, such as access or deletion. We do not charge a fee for ordinary requests. We may refuse or limit a request where the law allows or requires it, and we will tell you why.</p>
            <p><strong className="text-ink">Complaints.</strong> If you are in South Africa and believe your rights under POPIA have been violated, you may lodge a complaint with the <a href="https://inforegulator.org.za/complaints/" target="_blank" rel="noopener noreferrer" className="text-accent-blue hover:underline">Information Regulator of South Africa</a>. If GDPR applies to you, you may lodge a complaint with your local supervisory authority. We would appreciate the chance to put things right first, so please also write to us.</p>
          </section>

          {/* 11. Information Officer */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">11. Information Officer</h2>
            <p>Under POPIA, Response Mosese, as the sole proprietor trading as Quancis, acts as the Information Officer responsible for compliance with South African data protection law and for handling requests, queries, and complaints regarding your personal information. The Information Officer can be reached at <a href="mailto:response@quancis.space" className="text-accent-blue hover:underline">response@quancis.space</a>.</p>
          </section>

          {/* 12. Data Security */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">12. Data Security</h2>
            <p>We take reasonable technical and organizational measures to protect your personal information, including:</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li>encrypted connections (HTTPS) between you and the Service;</li>
              <li>storing passwords only in hashed form, handled by our authentication provider;</li>
              <li>storing API keys only as a hash, so that we cannot read a key after you create it;</li>
              <li>keeping our database closed to browsers and apps: only our own servers can read and write the data, and a person&apos;s session can reach only that person&apos;s own data through our API;</li>
              <li>limiting who on our side can reach the data, and protecting administrator access separately; and</li>
              <li>not storing the text of API requests or answers.</li>
            </ul>
            <p>However, no system is completely secure, and we cannot guarantee absolute security. Please keep your password and API keys secret.</p>
            <p><strong className="text-ink">Breach notification.</strong> In the event of a security compromise affecting your personal information, we will notify affected users and, where required by law, the Information Regulator, without undue delay.</p>
          </section>

          {/* 13. Legal Disclosure */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">13. Legal Disclosure</h2>
            <p>We do not promise that we will withhold your data if compelled by a court of law or other valid legal process. We do promise to limit our own collection and retention of your data to what is described in this Policy.</p>
          </section>

          {/* 14. Children's Privacy */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">14. Children&apos;s Privacy</h2>
            <p>The Service is not directed at, and may not be used by, individuals under 18 years of age (or the age of majority in their jurisdiction). We do not knowingly collect personal information from minors. If you believe a minor has given us personal information, tell us at <a href="mailto:response@quancis.space" className="text-accent-blue hover:underline">response@quancis.space</a> and we will delete it.</p>
          </section>

          {/* 15. Automated Processing */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">15. Automated Processing</h2>
            <p>Our safety screening (Section 3) is automated and can block a request, and can lead us to pause an Account. A person reviews the flag before we take any further enforcement action, such as closing the Account, and you can ask us to review any decision by writing to <a href="mailto:response@quancis.space" className="text-accent-blue hover:underline">response@quancis.space</a>. Other than that, we do not make decisions about you based solely on automated processing that have legal or similarly significant effects on you.</p>
            <p>The answers Kael produces are generated by AI systems. They may be wrong, and they are not a decision about you.</p>
          </section>

          {/* 16. Changes to This Policy */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">16. Changes to This Policy</h2>
            <p>We may update this Privacy Policy from time to time. We will post the updated Policy on our website with a new &quot;Last updated&quot; date. For material changes, we will also notify you by email to your registered address at least 14 days before the change takes effect.</p>
          </section>

          {/* 17. Contact Us */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">17. Contact Us</h2>
            <p>Questions about this Privacy Policy, and requests to exercise your rights or to delete your account, can be sent to <a href="mailto:response@quancis.space" className="text-accent-blue hover:underline">response@quancis.space</a>, or to <a href="mailto:support@quancis.space" className="text-accent-blue hover:underline">support@quancis.space</a> for general help.</p>
            <p>Response Mosese, trading as Quancis, Sekhukhune 1124, Limpopo, South Africa.</p>
          </section>

        </div>
      </div>
    </div>
  );
};

export default PrivacyPage;
