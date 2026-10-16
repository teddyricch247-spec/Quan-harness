import React from 'react';
import { BrandMark } from '../BrandMark';

export const TermsPage: React.FC = () => {
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
            <h1 className="text-2xl font-medium text-ink tracking-tight">Terms of Service</h1>
            <p className="text-xs text-ink-3 mt-1">Last updated: October 13, 2026</p>
          </div>
        </div>

        <div className="space-y-8 text-sm text-ink-2 leading-relaxed">

          {/* 1. Introduction & Acceptance */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">1. Introduction &amp; Acceptance</h2>
            <p>Welcome to Quancis. These Terms of Service (&quot;Terms&quot;) govern your access to and use of the Quancis platform at platform.quancis.space, including the Kael API (the &quot;API&quot;), the in-browser chat interface on the platform (the &quot;Playground&quot;), the documentation, and all related services (together, the &quot;Service&quot;). The Service is provided by Response Mosese, trading as Quancis (&quot;Quancis,&quot; &quot;we,&quot; &quot;us,&quot; or &quot;our&quot;). Quancis is not a registered company, close corporation, or other separate legal entity. It is an unregistered sole proprietorship operating under the laws of South Africa, based in Limpopo, Republic of South Africa. &quot;Quancis&quot; is simply a trading name used by Response Mosese in that capacity, and any reference to &quot;Quancis&quot; throughout these Terms refers to Response Mosese personally, trading as Quancis.</p>
            <p><strong className="text-ink">What these Terms cover.</strong> These Terms cover the Quancis platform, the API, and the Playground only. Other Quancis products, such as Quan Harness and Quan Chat, are offered under their own terms and are not covered by these Terms.</p>
            <p><strong className="text-ink">The agreement.</strong> These Terms, together with our <a href="/privacy-policy" className="text-accent-blue hover:underline">Privacy Policy</a>, form the agreement between you and Quancis about the Service. If you use the Service on behalf of a business or other organization, you confirm that you have authority to bind it to these Terms, and &quot;you&quot; then means that organization as well as you.</p>
            <p><strong className="text-ink">How you accept.</strong> You accept these Terms when you create an account (including by ticking the box that says you accept the Terms and Privacy Policy, or by signing in for the first time with Google or GitHub), or when you first access or use the Service, whichever happens first. We keep a record of which version of the Terms and Privacy Policy you accepted and when. Accepting by clicking, ticking, or using the Service is a valid way of concluding an agreement electronically under the Electronic Communications and Transactions Act 25 of 2002, and you agree that you do not need to sign these Terms for them to bind you.</p>
            <p>If you do not agree to these Terms, do not create an account and do not use the Service.</p>
          </section>

          {/* 2. Definitions */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">2. Definitions</h2>
            <p>In these Terms:</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li><strong className="text-ink">&quot;Account&quot;</strong> means the Quancis account you register to use the Service.</li>
              <li><strong className="text-ink">&quot;API key&quot;</strong> means a secret key, beginning with &quot;sk-quan-&quot;, that you create in your Account and use to send requests to the API.</li>
              <li><strong className="text-ink">&quot;Credits&quot;</strong> means the prepaid units of value in your Account that are used up as you use the Service, as described in Section 6.</li>
              <li><strong className="text-ink">&quot;Kael&quot;</strong> means the AI system that powers the Service. Kael is currently offered as two models, <strong className="text-ink">Kael Beta</strong> and <strong className="text-ink">Kael Pro Beta</strong>.</li>
              <li><strong className="text-ink">&quot;Lemon Squeezy&quot;</strong> means our online reseller and Merchant of Record, which handles payments for the Service (Section 7).</li>
              <li><strong className="text-ink">&quot;Output&quot;</strong> means the text, code, and other content that Kael generates in response to Your Content.</li>
              <li><strong className="text-ink">&quot;Playground&quot;</strong> means the chat interface on the platform, where you sign in and talk to Kael directly.</li>
              <li><strong className="text-ink">&quot;Your Content&quot;</strong> means the prompts, instructions, pictures, files, and other material that you send to the Service, whether through the API or the Playground.</li>
              <li><strong className="text-ink">&quot;Business day&quot;</strong> means a day other than a Saturday, a Sunday, or a public holiday in South Africa.</li>
            </ul>
          </section>

          {/* 3. Eligibility */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">3. Eligibility</h2>
            <p>You must be at least 18 years old, or the age of majority in your jurisdiction if that is higher, to use the Service. By using Quancis, you represent and warrant that you meet this requirement, that you have the legal capacity to enter into a binding agreement, and that you are not barred from using the Service under any law that applies to you. We do not independently verify age, and we are not responsible or liable if you misrepresent your age or eligibility to use the Service.</p>
            <p>You may not use the Service if you are located in, or ordinarily resident in, a country or region that is subject to a comprehensive trade embargo or sanctions that apply to us, or if you appear on a sanctions or denied-party list that applies to us. You are responsible for making sure that your use of the Service, and of the Output, is lawful where you are.</p>
          </section>

          {/* 4. The Service */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">4. The Service</h2>
            <p>Quancis builds AI products on a composite intelligence system called Kael. Kael is a system of several AI components working together behind a single request, designed for coding, security, software engineering, math, and tool-using or agentic work. Rather than returning a single-pass response, the system drafts an answer, reviews it, and refines it before the result is returned to you. Kael is currently offered as two models, <strong className="text-ink">Kael Beta</strong> (thinking levels &quot;low,&quot; &quot;high,&quot; and &quot;max&quot;) and <strong className="text-ink">Kael Pro Beta</strong> (thinking levels &quot;z-low&quot; and &quot;z-high&quot;). Each model accepts only its own thinking levels. Higher thinking levels can change how long a request takes and how many tokens it uses.</p>
            <p><strong className="text-ink">Two ways to use Kael.</strong> The <strong className="text-ink">API</strong> lets your own software send requests using an API key. The <strong className="text-ink">Playground</strong> is the chat interface on the platform, where you sign in and talk to Kael directly. Both draw on the same Credit balance and are billed at the same rates (Section 6). They handle your content differently. Playground conversations are saved to your Account so you can come back to them. API requests are not saved: we do not store the text of requests you send through the API or the answers to them (see Section 9 and the <a href="/privacy-policy" className="text-accent-blue hover:underline">Privacy Policy</a>).</p>
            <p><strong className="text-ink">Compatibility.</strong> The API is designed to be compatible with the OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages request formats, so that it works with existing software with few changes. Compatibility does not mean that every feature or parameter of those services is supported. For example, sampling settings such as temperature are accepted but ignored, so the same request can return different answers at different times.</p>
            <p><strong className="text-ink">How answers are produced.</strong> To produce an answer, Kael may make several internal calls to AI models run by third-party infrastructure providers (Section 13). Which internal components, models, and providers are used can change at any time without notice, and we do not disclose them. You agree not to attempt to find out or to interfere with them (Section 10).</p>
            <p><strong className="text-ink">Beta status.</strong> Kael is in active beta. Performance may fluctuate significantly and may not match descriptions published elsewhere at all times. Some requests, especially difficult ones on Kael Pro Beta, can take many minutes, and a request that takes too long is stopped with a timeout error. We do not currently offer a service-level agreement or an uptime guarantee. We may modify, suspend, replace, or discontinue models, thinking levels, features, or the whole Service at any time, as described in Section 20.</p>
            <p><strong className="text-ink">Not for high-risk use.</strong> The Service is not designed or intended for use where a failure or an error could lead to death, personal injury, or serious physical or environmental harm, or for automated decisions about people that have legal or similarly significant effects, without a human who independently reviews them. You use the Service for such purposes entirely at your own risk (see Section 9).</p>
          </section>

          {/* 5. Accounts, API Keys & Rate Limits */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">5. Accounts, API Keys &amp; Rate Limits</h2>
            <p><strong className="text-ink">Your account.</strong> You must give accurate information when you register and keep it up to date. You may hold only one Account unless we agree otherwise in writing, and you may not let another person use your Account.</p>
            <p><strong className="text-ink">Security of your credentials and keys.</strong> You are responsible for maintaining the confidentiality of your account credentials and API keys, and for all activity that occurs under your account, including usage charged against your Credit balance. An API key is shown to you in full only once, when you create it, and we cannot recover it for you. Treat API keys like passwords: do not put them in public code repositories, in web pages, or in apps that other people can inspect. You can revoke an API key at any time on the API keys page. Notify us immediately at <a href="mailto:support@quancis.space" className="text-accent-blue hover:underline">support@quancis.space</a> if you suspect unauthorized use of your account or API keys. Credits used through a key before you tell us it was compromised are not refunded, unless the use happened because of an error on our part.</p>
            <p><strong className="text-ink">Rate limits.</strong> We apply rate limits, concurrency limits, request-size and picture limits, and other technical restrictions to the API and the Playground to maintain platform stability and fair access for all users. Current limits are listed in our documentation. We may change them at our discretion, with or without prior notice.</p>
            <p><strong className="text-ink">Suspended accounts.</strong> While an Account is suspended, you cannot sign in, and all of its API keys are revoked and stop working (Section 11).</p>
          </section>

          {/* 6. Credits & Billing */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">6. Credits &amp; Billing</h2>
            <p><strong className="text-ink">Prepaid credits.</strong> The Service runs on prepaid Credits. You buy Credits in advance (Section 7), and they are used up as you use the Service. We do not bill you in arrears, and we do not charge a card for usage.</p>
            <p><strong className="text-ink">Credits are not money.</strong> Please read this carefully.</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li>Credits are a prepaid allowance for using the Service and nothing more. They are shown with a &quot;$&quot; sign for convenience, so that you can see what your usage costs, and the price of Credits tracks the US dollar amount you pay (a purchase of US$1 adds 1 dollar of Credits). That does not make a Credit a US dollar or any other currency.</li>
              <li>Credits are not currency, money, electronic money, a deposit, a stored-value or payment instrument, a security, or a financial product of any kind. Buying Credits does not make you a depositor or a creditor of Quancis, and Credits do not earn interest.</li>
              <li>Credits have <strong className="text-ink">no cash value</strong>. They <strong className="text-ink">cannot be withdrawn</strong>, cashed out, or exchanged for money, for gift cards, or for anything else of value. The only way money comes back to you is a refund of a payment under Section 8, which is a refund of the payment and not a redemption of Credits.</li>
              <li>Credits are <strong className="text-ink">not transferable</strong>. You cannot sell, lend, gift, or transfer Credits, or pay with them, to another person or to another Account, and you may not trade or offer them for sale anywhere.</li>
              <li>Credits can be used <strong className="text-ink">only on Quancis</strong>, for the Service as described in these Terms. They cannot be used with any other business, product, or service, including Quancis products that are offered under their own terms, unless we say so in writing.</li>
              <li>Credits exist only as an entry in our records. The balance and history shown in your Account are the only valid record of them.</li>
            </ul>
            <p><strong className="text-ink">Prices.</strong> The price of the Service is per token. A token is a small piece of text (roughly a few characters), counted by our system. Our count can differ from the count shown by another provider&apos;s tokenizer or by your own software. Current prices, per 1,000,000 tokens, are:</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li><strong className="text-ink">Kael Beta:</strong> $3.00 for input tokens and $10.00 for output tokens.</li>
              <li><strong className="text-ink">Kael Pro Beta:</strong> $8.00 for input tokens and $25.00 for output tokens.</li>
              <li><strong className="text-ink">Cached input.</strong> When part of your input matches content our system has recently processed (a &quot;cache hit&quot;), that part is billed at the cached input rate instead of the standard input rate: $0.60 per 1,000,000 tokens for Kael Beta and $1.60 per 1,000,000 tokens for Kael Pro Beta. These cached rates are 80% below the standard input rates. The rate for cached input is fixed. What varies from request to request, and is not guaranteed, is how much of a given request is served from cache.</li>
            </ul>
            <p><strong className="text-ink">What you are billed for.</strong></p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li>You are billed for the input tokens of your request and for the output tokens of the final answer. In the Playground, the input includes the earlier messages of the conversation (and any pictures) that are sent along with each new message.</li>
              <li>Kael may make several internal calls to produce one answer. The extra input and output of those internal steps, and the short progress summaries shown while Kael works, are not billed to you.</li>
              <li>The API and the Playground draw on the same balance and are billed at the same rates.</li>
              <li>We do not intend to charge for a request that fails before it produces an answer. If you think you were charged for a failed request, tell us and we will review it (Section 8).</li>
              <li>Your billing history in your Account lists each charge, purchase, and adjustment. Figures on the Usage page are estimates calculated from token counts at the current prices. If they differ from your billing history, the billing history is correct.</li>
            </ul>
            <p><strong className="text-ink">Balance at or below zero.</strong> The exact cost of a request is known only when it finishes, so a request that starts with a positive balance may finish and take your balance slightly below zero. New requests are blocked while your balance is at or below zero, and any negative amount is netted against the next Credits you buy or are given.</p>
            <p><strong className="text-ink">Credits expire 12 months after they are added.</strong> Every Credit expires 12 months after the date it was added to your Account, whether you bought it or we added it (see &quot;Credits we add&quot; below). Credits added in one purchase or one adjustment expire together.</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li><strong className="text-ink">Oldest first.</strong> When you use the Service, we use your oldest Credits first. Your balance is therefore made up of lots of Credits, each with its own expiry date.</li>
              <li><strong className="text-ink">What happens at expiry.</strong> Credits that are still unused when their 12 months end are removed from your balance. The removal is recorded in your billing history as a line beginning &quot;Expired credits.&quot; Expired Credits cannot be restored, refunded, or paid out, because they have no cash value (Section 8 explains the one refund you can ask for).</li>
              <li><strong className="text-ink">When it is processed.</strong> We process expiry once a day. A removal can therefore be recorded some time after the expiry date, and Credits that you use in the meantime count as used. You should not rely on being able to use Credits after their 12 months have ended.</li>
              <li><strong className="text-ink">Mandatory law.</strong> This expiry rule does not take away any right you have under a law that cannot be waived (Section 8).</li>
            </ul>
            <p><strong className="text-ink">Credits we add.</strong> From time to time we may add Credits to an Account, for example as goodwill, or to correct an error. These are ordinary Credits under these Terms and expire 12 months after they are added, and they have no cash value and are not refundable.</p>
            <p><strong className="text-ink">Price changes.</strong> We may change pricing, the rate for Credits, or billing terms at any time. A change applies only to usage after it takes effect, and we will give reasonable notice of material changes on the website or by email to your registered address. Prices shown in the Service and in the documentation are the prices that apply to you at the time of your request.</p>
            <p><strong className="text-ink">Taxes.</strong> Prices do not include sales tax, VAT, or similar taxes where those apply. Where Lemon Squeezy collects them, they are calculated at checkout (Section 7). You are responsible for any other taxes, duties, or charges that apply to your use of the Service or to your business.</p>
          </section>

          {/* 7. Payments */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">7. Payments</h2>
            <p><strong className="text-ink">Lemon Squeezy is our Merchant of Record.</strong> Our order process is handled by our online reseller and Merchant of Record, Lemon Squeezy. Lemon Squeezy processes your payment, calculates, collects, and pays the applicable sales tax or VAT, issues your receipt or invoice, and handles refunds and payment disputes for the payment. When you buy Credits, your contract for the purchase of those Credits is concluded through Lemon Squeezy, and your purchase is also subject to Lemon Squeezy&apos;s <a href="https://lemonsqueezy.com/buyer-terms" target="_blank" rel="noopener noreferrer" className="text-accent-blue hover:underline">Buyer Terms</a> and <a href="https://lemonsqueezy.com/privacy" target="_blank" rel="noopener noreferrer" className="text-accent-blue hover:underline">Privacy Policy</a>. Quancis does not collect, process, or store your payment card, bank account, or other financial account information.</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li><strong className="text-ink">What you can buy.</strong> You buy Credits in the amounts offered at checkout (for example, $25, $50, or $100), at the price shown at checkout. Prices are in US dollars. If Lemon Squeezy shows you a price in another currency, it applies its own exchange rate, and the Credits you receive are the US dollar amount of what you bought.</li>
              <li><strong className="text-ink">Taxes.</strong> Applicable taxes are calculated by Lemon Squeezy, based on your location, and shown at checkout before you pay.</li>
              <li><strong className="text-ink">Delivery of Credits.</strong> Credits are added to your Account once your payment is confirmed, usually within minutes. They are available immediately after that.</li>
              <li><strong className="text-ink">Missing credits.</strong> If you have paid and your Credits have not appeared, contact <a href="mailto:support@quancis.space" className="text-accent-blue hover:underline">support@quancis.space</a> from your account email address, with your order number or receipt. We will add the missing Credits to your Account or, if you prefer and you tell us within the time in Section 8, refund the payment.</li>
              <li><strong className="text-ink">Failed or duplicate payments.</strong> If a payment fails, no Credits are added. If you were charged twice for one purchase, tell us and we will correct it (Section 8).</li>
              <li><strong className="text-ink">No subscriptions or automatic recharge.</strong> Buying Credits is a one-time purchase. We do not renew it, and we do not recharge your payment method automatically.</li>
              <li><strong className="text-ink">Payment disputes and chargebacks.</strong> Please contact us before disputing a payment with your bank or card issuer, so that we can fix the problem quickly. Lemon Squeezy&apos;s Buyer Terms also ask you to contact Lemon Squeezy before raising a chargeback. If a payment is reversed, we remove the Credits that were bought with it. We may suspend the Account until the dispute is resolved, and we may refuse further purchases if a payment dispute was raised in bad faith.</li>
              <li><strong className="text-ink">Fraud.</strong> We and Lemon Squeezy may refuse or cancel a payment, or refuse a refund, where there is evidence of fraud, stolen payment methods, refund abuse, or other manipulative behavior, and we may suspend or terminate the Account involved (Section 11).</li>
            </ul>
          </section>

          {/* 8. Refunds */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">8. Refunds</h2>
            <p><strong className="text-ink">The short version.</strong> Credits are generally non-refundable once used. You can ask for a refund of unused Credits within 14 days of buying them, and we always correct billing errors on our side. The details follow.</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li><strong className="text-ink">Unused Credits within 14 days.</strong> You may ask for a refund of the unused Credits from a purchase within 14 days of the date of that purchase. If you have already used some of the Credits from that purchase, only the unused part is refunded. To work out how much of a purchase is unused, we use the same order as in Section 6, so use is counted against your oldest Credits first.</li>
              <li><strong className="text-ink">Our errors.</strong> We will always correct or refund a duplicate charge, a charge for Credits that were not delivered, a charge for a request that failed before it produced an answer, or any other billing error on our part, whenever you tell us about it. If we correct the error by adding Credits or by refunding, we choose the quicker option unless you ask for the other, and a refund for an error on our side is not limited to 14 days.</li>
              <li><strong className="text-ink">Not refundable.</strong> Credits that have already been used; Credits that have expired; Credits we added to your Account free of charge (Section 6); Credits used through an API key that was compromised through no error on our part (Section 5); and the remaining balance of an Account that we close for violating these Terms (Section 11).</li>
            </ul>
            <p><strong className="text-ink">How to ask.</strong> Email <a href="mailto:support@quancis.space" className="text-accent-blue hover:underline">support@quancis.space</a> from your account email address, with your order number or receipt, and tell us which purchase the refund is for. We aim to reply within 5 business days. We refund through Lemon Squeezy to your original payment method, and how long the money takes to appear depends on your payment provider. A refund removes the refunded Credits from your Quancis balance. If you contact Lemon Squeezy directly instead, its Buyer Terms say that refunds are provided at Lemon Squeezy&apos;s sole discretion, on a case-by-case basis.</p>
            <p><strong className="text-ink">Ask before you delete your account.</strong> Credits left in an Account that is deleted or closed are lost (Section 12). If you want a refund of unused Credits, ask for it before you close or delete the Account.</p>
            <p><strong className="text-ink">Credits that arrive after a refund.</strong> If Credits from a payment are added to your Account after that payment has already been refunded, we will simply remove those Credits. If a payment is refunded or reversed after you have already used some of its Credits, we remove whatever is left of them, and the Credits already used stay used. We will not charge, penalize, or ask you to repay anything for Credits you have already used in that situation, unless we determine that you manipulated our systems, misrepresented facts, or otherwise acted in bad faith to obtain Credits, a refund, or both. In that case, you may face consequences up to and including permanent account termination, in addition to any other remedies available to us under law.</p>
            <p><strong className="text-ink">Your legal rights.</strong> The 14-day refund period above is also intended to give you at least the cooling-off right that applies to distance contracts under section 44 of the Electronic Communications and Transactions Act, where that section applies to you. Nothing in these Terms limits any right you have under consumer protection law that cannot be waived, including any right to cancel a purchase or to a minimum period of validity for prepaid credit. Where such a right gives you more than these Terms do, you may rely on it.</p>
          </section>

          {/* 9. Your Content & Ownership of Output */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">9. Your Content &amp; Ownership of Output</h2>
            <p><strong className="text-ink">Your content.</strong> You keep ownership of Your Content. You allow us to process Your Content only as needed to run the Service for you, including sending it to the AI infrastructure providers that generate answers, and as described in our <a href="/privacy-policy" className="text-accent-blue hover:underline">Privacy Policy</a>. <strong className="text-ink">We do not use Your Content or the Output to train or improve our models.</strong> We configure our requests so that they are routed only to AI providers that state that they do not store prompts beyond what is needed to produce the answer and do not train on them (see the <a href="/privacy-policy" className="text-accent-blue hover:underline">Privacy Policy</a>). We rely on what those providers state, and we cannot audit them (Section 13).</p>
            <p><strong className="text-ink">Saved conversations (Playground).</strong> Playground conversations are saved to your Account until you delete them, so that you can return to them. A saved conversation includes your messages, the answers, pictures you attached, short summaries of the steps Kael showed, and an automatically generated title. You can delete a conversation yourself at any time, and doing so deletes it from your Account. For troubleshooting, each Playground request also creates a short diagnostic record that is deleted together with the conversation and in any case after 30 days.</p>
            <p><strong className="text-ink">API requests.</strong> We do not store the text of requests sent through the API or the answers to them. We keep only usage and billing records, such as the time, the model, the status, token counts, and the cost. The only exception is content that our safety screening flags (Section 11), which is kept as described there and in the <a href="/privacy-policy" className="text-accent-blue hover:underline">Privacy Policy</a>.</p>
            <p><strong className="text-ink">What you must have the right to send.</strong> You are responsible for Your Content. You confirm that you have all the rights and permissions needed to send it to us for processing, that it does not break the law or these Terms, and that, if it contains personal information about other people, you have a lawful basis to send it to us and to the providers described in the Privacy Policy. Please do not send us information that you are not allowed to share, or that is more sensitive than you need (for example, passwords, payment card numbers, or health records) unless you have made sure that it is appropriate to do so.</p>
            <p><strong className="text-ink">Output.</strong> As between you and Quancis, <strong className="text-ink">you own 100% of the Output</strong> Kael generates in response to your prompts (including generated code, text, and any other content), subject to your compliance with these Terms and applicable law. Quancis claims no ownership over your Output. Because AI systems can generate similar Output for similar prompts, other users may receive similar Output, and we make no claim to exclusive rights for you in Output.</p>
            <p><strong className="text-ink">No warranty on output.</strong> Kael&apos;s Output, including generated code and calculations, may contain errors and is not guaranteed to be accurate, complete, secure, current, or production-ready. This is especially true given the Service&apos;s beta status, described in Section 4. <strong className="text-ink">You are solely responsible for independently reviewing, testing, and validating all Output before relying on it</strong>, particularly in production, mission-critical, or high-stakes environments. Quancis is not liable for any loss, damage, or harm arising from your use of or reliance on generated Output.</p>
            <p><strong className="text-ink">No guarantee of originality.</strong> Because Output is generated by an AI system, Quancis does not guarantee that any specific Output is free of third-party intellectual property rights, and does not warrant that your use of any Output will not infringe the rights of others. You are responsible for independently assessing whether your intended use of any Output complies with applicable intellectual property law.</p>
          </section>

          {/* 10. Acceptable Use */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">10. Acceptable Use</h2>
            <p>You agree not to use the Service to:</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li>Generate, request, or facilitate illegal content or activity, including fraud, malware or exploits for unauthorized access to systems, instructions for illegal weapons, or illegal goods;</li>
              <li>Generate, request, store, or facilitate child sexual abuse material (CSAM) or any content that sexually exploits, endangers, or involves minors, in any form;</li>
              <li>Attempt to bypass, circumvent, or abuse rate limits, authentication, the safety screening described in Section 11, or the credit and billing system;</li>
              <li>Resell, sublicense, or provide third parties access to the Service without our prior written authorization;</li>
              <li>Share an Account, or share an API key with people outside your own organization;</li>
              <li>Systematically extract outputs or system prompts in order to build a directly competing product, or use the Output to train a model that competes with Kael;</li>
              <li>Attempt to discover, probe, or interfere with the internal components, models, prompts, or third-party providers that the Service uses, or to reverse engineer the Service;</li>
              <li>Generate content that infringes the intellectual property rights of others, or that defames, harasses, or violates the rights of any person;</li>
              <li>Engage in automated abuse of the Service, including scraping, spamming, or excessive querying intended to overload the Service;</li>
              <li>Generate or spread knowingly false content intended to cause harm (for example, disinformation campaigns);</li>
              <li>Generate content that threatens, incites, or promotes violence or terrorism, or that targets a person or group for harm because of who they are;</li>
              <li>Violate any applicable export control or sanctions laws.</li>
            </ul>
            <p>Violating any of the above may result in a warning, suspension, or termination of your account as described in Section 11, in addition to any other remedies available to us under law.</p>
          </section>

          {/* 11. Safety Screening, Enforcement, Suspension & Termination */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">11. Safety Screening, Enforcement, Suspension &amp; Termination</h2>
            <p><strong className="text-ink">Safety screening.</strong> Requests and answers are screened automatically for content that violates Section 10, using our own checks and the safety systems of our AI providers. Content that is flagged as potentially harmful may be blocked before it is delivered. Screening is automated and is not perfect: it can miss violations and it can flag content that is fine, and it does not replace your own responsibility for Your Content.</p>
            <p><strong className="text-ink">Flagged content.</strong> If a request or an answer is flagged, we keep it, together with the details needed to identify the Account, until an administrator has reviewed it, and the Account may be paused while that review is under way. If we take enforcement action, we may keep the flagged content for up to 90 days afterwards as a record in case of a dispute or a legal claim. If a flag is found to be a false positive, it is cleared, the flagged content is deleted, and the Account is restored. We do not use flagged content for anything other than review, enforcement, and legal compliance, and in particular we do not use it to train models. How flagged content is kept is described in the <a href="/privacy-policy" className="text-accent-blue hover:underline">Privacy Policy</a>.</p>
            <p><strong className="text-ink">Reports to authorities.</strong> Where the law requires it, for example for child sexual abuse material, we will report the content and the Account to the police or another competent authority and may keep what is needed for that purpose.</p>
            <p><strong className="text-ink">Suspension and termination.</strong> We may suspend or terminate your account at our discretion, including for violations of these Terms, an unpaid negative balance, a payment that was reversed, abuse of the Service, or as required by law. We will notify you via your registered email address where we reasonably can.</p>
            <p>For most violations, we will issue a warning before taking action. However, we reserve the right to suspend or terminate an account immediately, without prior warning, where conduct is severe or outrageous, including, without limitation, generating or requesting CSAM.</p>
            <p><strong className="text-ink">Effect of suspension or termination.</strong> When an Account is suspended or terminated, you can no longer use it, and its API keys stop working. Credits left in an Account that we terminate for violating these Terms are lost and are not refunded (Section 8). Credits left in a suspended Account that is later restored (for example, after a false positive) are not affected, but their expiry dates keep running.</p>
            <p><strong className="text-ink">Your right to stop.</strong> You may stop using the Service at any time, and you may close and delete your Account (Section 12). Provisions of these Terms that by their nature should continue after the end of the agreement (including Sections 8, 9, 15 to 18, and 21) continue to apply.</p>
          </section>

          {/* 12. Closing & Deleting Your Account */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">12. Closing &amp; Deleting Your Account</h2>
            <p><strong className="text-ink">How to delete your account.</strong> You can permanently delete your Account yourself on the Account page of the platform. You will be asked to type your account email address to confirm. You can also ask us to delete it by emailing <a href="mailto:response@quancis.space" className="text-accent-blue hover:underline">response@quancis.space</a> from your account email address, and we will complete the request within 30 days. We may ask you to verify your identity first.</p>
            <p><strong className="text-ink">What deletion does.</strong> Deleting your Account is permanent and cannot be undone. When you delete it:</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li>All of your API keys are revoked immediately, and API requests with them stop working.</li>
              <li>Your Playground conversations, messages, and pictures, your diagnostic records, your usage records, your Credit balance and billing history, and the record of your acceptance of these Terms and the Privacy Policy are deleted, and your login is removed.</li>
              <li><strong className="text-ink">Credits left on the Account are lost.</strong> They have no cash value and are not refunded (Section 8). If you want a refund of unused Credits that you are entitled to, ask for it <strong className="text-ink">before</strong> you delete the Account.</li>
              <li>We send you a short confirmation email.</li>
            </ul>
            <p><strong className="text-ink">What we keep.</strong> Payment and tax records are held by Lemon Squeezy as Merchant of Record, which keeps its own records of your purchases. We also keep the accounting and tax records that the law requires us to keep, for example reports and statements from Lemon Squeezy about sales and payouts, for as long as the law requires (generally five years in South Africa). Content that our safety screening flagged and that is still under review or kept as a record of enforcement action is kept as described in Section 11. Details are in the <a href="/privacy-policy" className="text-accent-blue hover:underline">Privacy Policy</a>.</p>
            <p><strong className="text-ink">Administrator accounts.</strong> Accounts that have administrator rights cannot be deleted from the Account page and are removed by us directly.</p>
          </section>

          {/* 13. Third-Party Services */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">13. Third-Party Services</h2>
            <p>The Service relies on third-party providers to operate, including hosting providers (Vercel and Render), a database and authentication provider (Supabase), an email delivery provider (Resend), sign-in providers if you choose to use them (Google and GitHub), third-party AI infrastructure and processing providers, and our payment provider and Merchant of Record, Lemon Squeezy. Your data may be transmitted to these providers as necessary to provide the Service, as described in our <a href="/privacy-policy" className="text-accent-blue hover:underline">Privacy Policy</a>.</p>
            <p><strong className="text-ink">AI providers.</strong> To generate answers, the content of your requests is sent to third-party providers that run AI models for us. We choose and change these providers ourselves and do not name them. We configure our requests so that they are only routed to providers that state that they do not store prompts (beyond what is needed to produce the answer, including short-lived technical caching) and do not train on them. If no provider meeting that condition is available, the request fails instead of being sent to another provider. We rely on the providers&apos; own statements and terms and cannot independently audit their systems.</p>
            <p>We select our providers with care, but <strong className="text-ink">we do not control their operations</strong>. To the extent permitted by law, Quancis is not responsible for the availability, performance, or data handling practices of any third-party service, and your use of such services (where applicable) may be subject to their own terms. If you sign in with Google or GitHub, their terms and privacy policies apply to that sign-in.</p>
          </section>

          {/* 14. Privacy */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">14. Privacy</h2>
            <p>Our collection, use, storage, and sharing of your personal information is described in our <a href="/privacy-policy" className="text-accent-blue hover:underline">Privacy Policy</a>, which is incorporated into these Terms by reference. By using the Service, you also agree to the terms of our Privacy Policy.</p>
          </section>

          {/* 15. Disclaimers */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">15. Disclaimers</h2>
            <p className="uppercase text-xs sm:text-[13px] tracking-tight text-ink-2 font-medium leading-relaxed">The Service is provided &quot;as is&quot; and &quot;as available,&quot; without warranties of any kind, whether express or implied, including warranties of merchantability, fitness for a particular purpose, or non-infringement. We do not warrant that the Service will be uninterrupted, error-free, or secure, or that any model, feature, or price will remain available. Output from the Service does not constitute professional, legal, financial, medical, or engineering advice.</p>
            <p>Nothing in this Section excludes a warranty or right that the law does not allow to be excluded.</p>
          </section>

          {/* 16. Limitation of Liability */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">16. Limitation of Liability</h2>
            <p className="uppercase text-xs sm:text-[13px] tracking-tight text-ink-2 font-medium leading-relaxed">To the maximum extent permitted by law, Quancis&apos;s total liability arising out of or related to these Terms or the Service shall not exceed the total amount you actually paid for Credits in the three (3) months preceding the claim (excluding any Credits we added to your account free of charge). In no event will Quancis be liable for any indirect, incidental, consequential, special, or punitive damages, including lost profits, lost data, or loss of business, even if advised of the possibility of such damages.</p>
            <p>Nothing in these Terms limits liability that cannot be excluded or limited under applicable South African law.</p>
          </section>

          {/* 17. Indemnification */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">17. Indemnification</h2>
            <p>You agree to indemnify and hold Quancis harmless from any claims, damages, liabilities, and expenses (including reasonable legal fees) arising from your use of the Service, your violation of these Terms, or your violation of any law or third-party right in connection with your use of the Service or its Output. This does not apply to the extent that a claim, damage, liability, or expense is caused by our own gross negligence or willful misconduct.</p>
          </section>

          {/* 18. Force Majeure */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">18. Force Majeure</h2>
            <p>Quancis is not liable for any failure or delay in performance caused by circumstances beyond our reasonable control, including, without limitation: outages or failures of third-party providers (such as our hosting, AI infrastructure, or payment providers); natural disasters; internet, power, or telecommunications failures; governmental action or restrictions; labor disputes; acts of war or terrorism; epidemics or pandemics; or any other event of force majeure.</p>
          </section>

          {/* 19. Intellectual Property */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">19. Intellectual Property</h2>
            <p>&quot;Quancis,&quot; &quot;Kael,&quot; and associated logos and branding are the property of Quancis. The Service itself, including its software, design, documentation, and the way its components are combined, belongs to Quancis or its licensors. Nothing in these Terms grants you any right to use our trademarks or branding, or any right in the Service other than the right to use it as these Terms allow, without prior written permission. Your right to use the Service is non-exclusive, non-transferable, and revocable.</p>
            <p><strong className="text-ink">Feedback.</strong> If you submit feedback, suggestions, or ideas about the Service, you grant us the right to use, modify, and incorporate that feedback into the Service in any way, without any obligation to credit or compensate you, and without any confidentiality obligation on our part regarding that feedback. Feedback does not include Your Content or the Output, which remain yours as set out in Section 9.</p>
          </section>

          {/* 20. Changes to the Service and to These Terms */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">20. Changes to the Service and to These Terms</h2>
            <p><strong className="text-ink">Changes to the Service.</strong> We may add, change, replace, or remove models, thinking levels, features, limits, and prices (see Section 6 for price changes) and may stop offering the Service. Where it is practical, we will tell you about important changes in advance through the website or by email. If we stop offering the Service altogether, we will let you ask for a refund of the unused Credits that you bought and that have not expired.</p>
            <p><strong className="text-ink">Changes to these Terms.</strong> We may update these Terms from time to time. We will post the updated Terms on our website with a new &quot;Last updated&quot; date. For material changes, we will also notify you by email to your registered address at least 14 days before the change takes effect. Continued use of the Service after changes take effect constitutes acceptance of the revised Terms. If you do not agree with a change, you may stop using the Service and close your Account (Section 12).</p>
          </section>

          {/* 21. Governing Law & Disputes */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">21. Governing Law &amp; Disputes</h2>
            <p>These Terms are governed by the laws of the Republic of South Africa, without regard to conflict-of-law principles. Any disputes arising from these Terms or the Service shall be subject to the jurisdiction of the courts of South Africa.</p>
            <p><strong className="text-ink">Consumers.</strong> If you are a consumer, you may also have rights under mandatory consumer protection laws of the country where you live, and these Terms do not limit those rights. Nothing in these Terms stops you from bringing a claim in the courts of your own country where mandatory law allows it, or, if you are in South Africa, from lodging a complaint with the National Consumer Commission or another competent authority or tribunal.</p>
            <p><strong className="text-ink">Talk to us first.</strong> Before starting any formal proceedings, please write to <a href="mailto:support@quancis.space" className="text-accent-blue hover:underline">support@quancis.space</a> and tell us what the problem is. We will try to resolve it with you in good faith, and we aim to respond within 30 days.</p>
          </section>

          {/* 22. Notices & Electronic Communications */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">22. Notices &amp; Electronic Communications</h2>
            <p><strong className="text-ink">Notices to you.</strong> We may send notices about the Service, your Account, billing, and these Terms to the email address registered on your Account, and may also post them on the website or show them in the platform. A notice sent by email is treated as received 24 hours after it is sent, unless we receive a message that it was not delivered. Please keep your email address up to date and check it regularly.</p>
            <p><strong className="text-ink">Notices to us.</strong> Send notices to <a href="mailto:support@quancis.space" className="text-accent-blue hover:underline">support@quancis.space</a> (or to <a href="mailto:response@quancis.space" className="text-accent-blue hover:underline">response@quancis.space</a> for privacy and legal matters). You may also send a written notice to the address in Section 24. For legal process and formal notices, we choose that address as our address for service.</p>
            <p><strong className="text-ink">Electronic communication.</strong> You agree that we may communicate with you electronically and that electronic communications satisfy any legal requirement that a communication be in writing, to the extent the law allows. We do not send marketing emails.</p>
          </section>

          {/* 23. General */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">23. General</h2>
            <p>If any provision of these Terms is found unenforceable, the remaining provisions remain in full effect. Our failure to enforce any provision is not a waiver of that provision. Quancis may assign these Terms (for example, in connection with a business reorganization or incorporation); you may not assign your rights or obligations under these Terms without our prior written consent. These Terms, together with the Privacy Policy, constitute the entire agreement between you and Quancis regarding the Service and replace any earlier version. No person other than you and Quancis has any right to enforce these Terms, except that Lemon Squeezy may rely on the provisions that concern payments. Headings are for convenience only. These Terms are written in English, and if they are translated, the English version prevails.</p>
          </section>

          {/* 24. Information About Us & Contact */}
          <section className="space-y-3">
            <h2 className="text-base font-bold text-ink">24. Information About Us &amp; Contact</h2>
            <p>Questions about these Terms, billing, or refunds can be sent to <a href="mailto:support@quancis.space" className="text-accent-blue hover:underline">support@quancis.space</a>. Privacy and legal matters, and requests to delete an account or exercise your data rights, can be sent to <a href="mailto:response@quancis.space" className="text-accent-blue hover:underline">response@quancis.space</a>.</p>
            <ul className="list-disc pl-5 space-y-1.5 leading-relaxed">
              <li><strong className="text-ink">Operator:</strong> Response Mosese, trading as Quancis, an unregistered sole proprietorship.</li>
              <li><strong className="text-ink">Address:</strong> Sekhukhune 1124, Limpopo, South Africa.</li>
              <li><strong className="text-ink">Websites:</strong> the platform at <a href="https://platform.quancis.space" target="_blank" rel="noopener noreferrer" className="text-accent-blue hover:underline">platform.quancis.space</a> and our main site at <a href="https://www.quancis.space" target="_blank" rel="noopener noreferrer" className="text-accent-blue hover:underline">www.quancis.space</a>.</li>
              <li><strong className="text-ink">General and billing contact:</strong> <a href="mailto:support@quancis.space" className="text-accent-blue hover:underline">support@quancis.space</a>.</li>
              <li><strong className="text-ink">Privacy, legal, and account deletion contact:</strong> <a href="mailto:response@quancis.space" className="text-accent-blue hover:underline">response@quancis.space</a>.</li>
              <li><strong className="text-ink">Payments:</strong> handled by Lemon Squeezy as Merchant of Record (Section 7).</li>
            </ul>
          </section>

        </div>
      </div>
    </div>
  );
};

export default TermsPage;
