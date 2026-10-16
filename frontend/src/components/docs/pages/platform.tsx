import React from 'react';
import { ROUTES } from '../../../lib/routes';
import { BETA, KAEL, PRO_BETA, listWords, usd } from '../facts';
import { docsHref } from '../nav';
import { A, C, Callout, CodeBlock, H2, P, Table, Ul } from '../primitives';

/* ------------------------------------------------------------------ */
/* About Kael                                                          */
/* ------------------------------------------------------------------ */

// Deliberately says nothing about how Kael produces an answer. Customers
// need to know what to expect (speed, billing, determinism) and when to
// choose it, not what happens inside. Keep it that way: do not describe
// internal steps, models or call counts here or anywhere else in the docs.

export const AboutKael: React.FC = () => (
  <>
    <H2 id="what-to-expect">What to expect</H2>
    <Ul>
      <li>
        <strong>It is slower than a single call, on purpose.</strong> Kael favors correctness over speed, so the first
        answer token arrives later than with a typical chat model. Kael Pro Beta is slower again. A <A href={docsHref('streaming')}>stream</A> sends short thinking titles in the
        meantime. For the quickest replies, use Kael Beta at its default <A href={docsHref('thinking')}>thinking</A>{' '}
        level, <C>low</C>.
      </li>
      <li>
        <strong>You are billed once.</strong> Your input and the final answer, nothing else. See{' '}
        <A href={docsHref('pricing')}>Pricing and billing</A>.
      </li>
      <li>
        <strong>Output is not deterministic.</strong> Sampling settings are ignored, so the same request can return
        different answers.
      </li>
    </Ul>

    <H2 id="what-kael-is">What Kael is</H2>
    <P>
      Kael is a Quancis product, offered through one API. Quancis does not publish how it is built or which components
      it uses, and Kael will not say. Kael&apos;s own weights are not available to download.
    </P>

    <H2 id="safety-screening">Safety screening</H2>
    <P>
      Requests and answers can be screened against the acceptable-use section of the{' '}
      <A href={ROUTES.terms}>Terms of Service</A>. A flagged request can be held for review and the account paused
      while it is checked. See <A href={docsHref('privacy')}>Data and privacy</A>.
    </P>

    <H2 id="when-to-use-kael">When to use Kael</H2>
    <Table
      head={['Reach for Kael when', 'Look elsewhere when']}
      minWidth={560}
      rows={[
        [
          'Correctness matters more than speed.',
          'You need the fastest possible response.',
        ],
        [
          'The work is code review, debugging, refactoring, or security review.',
          'The work is writing first: fiction or marketing copy.',
        ],
        [
          'An agent will act on the output.',
          'You need PDFs, video, or other file types today.',
        ],
        [
          'You already call a chat API and want to change as little as possible.',
          'You need a language other than English.',
        ],
        ['Your work is in English.', 'You need downloadable or self-hosted weights.'],
      ]}
    />
    <P>
      For most work, use <strong>{BETA.name}</strong> (<C>{BETA.id}</C>). Use <strong>{PRO_BETA.name}</strong> (
      <C>{PRO_BETA.id}</C>) for the hardest problems, where its extra thoroughness is worth the higher price per token. The two models are compared in <A href={docsHref('thinking')}>Thinking levels</A>.
    </P>
    <Callout title="No published benchmarks">
      <p>
        Quancis does not publish benchmark scores that it ran itself. Test Kael on your own tasks before you depend on
        it.
      </p>
    </Callout>
  </>
);

/* ------------------------------------------------------------------ */
/* Pricing and billing                                                 */
/* ------------------------------------------------------------------ */

// The worked example's arithmetic, computed from the model's own rates so it
// cannot drift from facts.ts. Tokens are per request; rates are per 1M tokens.
const WORKED = { uncached: 3_000, cached: 9_000, output: 1_500 } as const;
const cost4 = (tokens: number, ratePerMillion: number): string => `$${((tokens * ratePerMillion) / 1_000_000).toFixed(4)}`;
const workedTotal = (price: { input: number; cachedInput: number; output: number }): string =>
  `$${(
    (WORKED.uncached * price.input + WORKED.cached * price.cachedInput + WORKED.output * price.output) /
    1_000_000
  ).toFixed(4)}`;

const priceFormula = (p: { input: number; cachedInput: number; output: number }): string => `cost = (prompt_tokens - cached_tokens)  x  ${usd(p.input)} / 1M
     + cached_tokens                    x  ${usd(p.cachedInput)} / 1M
     + completion_tokens                x  ${usd(p.output)} / 1M`;

export const Pricing: React.FC = () => (
  <>
    <H2 id="prices">Prices</H2>
    <P>
      Kael has two models, and each has its own price. A request is billed at the price of the model it called.
    </P>
    <Table
      head={['Per 1M tokens', BETA.name, PRO_BETA.name]}
      minWidth={520}
      rows={[
        ['Input', usd(BETA.price.input), usd(PRO_BETA.price.input)],
        ['Input served from cache', usd(BETA.price.cachedInput), usd(PRO_BETA.price.cachedInput)],
        ['Output', usd(BETA.price.output), usd(PRO_BETA.price.output)],
      ]}
    />
    <Ul>
      <li>
        Prices are in US dollars, and are the same at every hour of the day. The levels of one model share one price.{' '}
        {PRO_BETA.name} costs more per token than {BETA.name}. See <A href={docsHref('thinking')}>Thinking levels</A>.
      </li>
      <li>
        Cached input is {usd(BETA.price.cachedInput)} for {BETA.name} and {usd(PRO_BETA.price.cachedInput)} for{' '}
        {PRO_BETA.name}, and only when a request actually hits the cache. Without a hit, input is the full input price.
        See <A href={docsHref('caching')}>Prompt caching</A>.
      </li>
      <li>
        Compare with other providers on the <A href={ROUTES.pricing}>pricing page</A>.
      </li>
    </Ul>

    <H2 id="what-you-are-billed-for">What you are billed for</H2>
    <Ul>
      <li>
        <strong>Input:</strong> the tokens in your request. That is your system prompt, messages, tool definitions, and
        images. The instructions Kael adds itself are not counted.
      </li>
      <li>
        <strong>Output:</strong> the tokens in the final answer you receive.
      </li>
      <li>
        <strong>Never billed:</strong> anything Kael does internally, including the thinking titles in a stream. Only
        your input and the final answer count.
      </li>
      <li>
        The <C>usage</C> in every response is what you were billed for.
      </li>
    </Ul>

    <H2 id="worked-example">Worked example</H2>
    <P>
      A request with 12,000 input tokens, of which 9,000 came from cache, and a 1,500-token answer, on {BETA.name}:
    </P>
    <CodeBlock tabs={[{ label: 'Formula', lang: 'text', code: priceFormula(BETA.price) }]} />
    <Table
      head={['Part', 'Tokens', 'Rate per 1M', 'Cost']}
      minWidth={480}
      rows={[
        ['Input, not cached', WORKED.uncached.toLocaleString('en-US'), usd(BETA.price.input), cost4(WORKED.uncached, BETA.price.input)],
        ['Input, from cache', WORKED.cached.toLocaleString('en-US'), usd(BETA.price.cachedInput), cost4(WORKED.cached, BETA.price.cachedInput)],
        ['Output', WORKED.output.toLocaleString('en-US'), usd(BETA.price.output), cost4(WORKED.output, BETA.price.output)],
        [<strong key="t">Total</strong>, '', '', <strong key="c">{workedTotal(BETA.price)}</strong>],
      ]}
    />
    <P>
      The same request on {PRO_BETA.name} costs {workedTotal(PRO_BETA.price)} at its own rates, using the same token
      counts.
    </P>

    <H2 id="your-balance">Your balance</H2>
    <Ul>
      <li>Kael is prepaid. Your balance starts at $0 and each finished request deducts from it.</li>
      <li>
        The API and the <A href={docsHref('playground')}>Playground</A> use the same balance. There is no separate
        Playground quota.
      </li>
      <li>
        A request is refused with <C>402</C> and the code <C>insufficient_balance</C> if your balance is $0 or below
        when it starts.
      </li>
      <li>
        A request that starts with a positive balance can finish slightly below zero, because its real cost is known
        only when it finishes. Add credit before your next request.
      </li>
      <li>
        <strong>Adding credit:</strong> open <A href={ROUTES.usage}>Usage &amp; Cost</A> and choose{' '}
        <strong>Add Prepaid Credits</strong> (the dashboard&apos;s <strong>+ Top up</strong> goes to the same place).
        Pick $25, $50 or $100 and pay by card. The amount is added to your balance and used by both the API and the
        Playground.
      </li>
      <li>
        <strong>Credits are a prepaid allowance, not money:</strong> they have no cash value, cannot be withdrawn,
        transferred or exchanged, and can only be used on Quancis. They expire 12 months after they are added to your
        account, oldest first. The <A href={ROUTES.terms}>Terms of Service</A> have the details.
      </li>
    </Ul>

    <H2 id="console-estimates">Costs shown in the console</H2>
    <P>
      The dashboard and the Usage page show costs worked out from each request&apos;s token counts at today&apos;s
      price. They are estimates. If the price changes, older requests are shown at the new price. See{' '}
      <A href={docsHref('dashboard')}>Dashboard and usage</A>.
    </P>
  </>
);

/* ------------------------------------------------------------------ */
/* Prompt caching                                                      */
/* ------------------------------------------------------------------ */

export const Caching: React.FC = () => (
  <>
    <H2 id="how-it-works">How it works</H2>
    <P>
      Caching is automatic. There is nothing to turn on: no headers, no flags, no parameters. When the beginning of a
      request matches one Kael has seen recently, those input tokens are served from cache and billed at the cached
      rate.
    </P>
    <Callout tone="warn" title="Treat caching as a bonus, not a plan">
      <p>
        Hits are best effort, and Quancis cannot promise a hit rate. Budget for the full input
        price ({usd(BETA.price.input)} for {BETA.name}, {usd(PRO_BETA.price.input)} for {PRO_BETA.name}). Any cache hit is a discount on top. If you are benchmarking or evaluating Kael with prompts that are all
        different, expect no hits at all.
      </p>
    </Callout>

    <H2 id="what-a-hit-costs">What a hit costs</H2>
    <Table
      head={['Input tokens', BETA.name, PRO_BETA.name]}
      minWidth={520}
      rows={[
        ['Not cached', usd(BETA.price.input), usd(PRO_BETA.price.input)],
        ['Served from cache (80% less)', usd(BETA.price.cachedInput), usd(PRO_BETA.price.cachedInput)],
      ]}
    />
    <P>
      A request only gets the cached rate on the tokens that hit, so its overall saving is somewhere between none and
      80%, depending on how much of the input was cached.
    </P>

    <H2 id="see-your-hits">See your hits</H2>
    <Table
      head={['Where', 'Field']}
      minWidth={520}
      rows={[
        ['Chat Completions', <C key="a">usage.prompt_cache_hit_tokens</C>],
        ['Responses', <C key="b">usage.input_tokens_details.cached_tokens</C>],
        ['Messages', 'Not reported in the response'],
        ['Dashboard', 'The Cache column on each request'],
        ['Usage page', 'Cached and uncached input, per day'],
      ]}
    />
    <P>
      <C>prompt_tokens</C> already includes the cached tokens, so the tokens you paid full price for are{' '}
      <C>prompt_tokens</C> minus the cached count.
    </P>

    <H2 id="getting-more-hits">Getting more hits</H2>
    <Ul>
      <li>
        Caching matches the start of a request, so keep the beginning stable from one request to the next and add what
        changes at the end.
      </li>
      <li>In a conversation, append new turns rather than rewriting earlier ones.</li>
      <li>Check the cached count in your own responses to see what you actually get.</li>
    </Ul>

    <H2 id="answers-are-not-cached">Answers are not cached</H2>
    <P>
      Kael does not cache answers. Sending the same request twice generates two fresh answers, and you are billed for
      both.
    </P>
  </>
);

/* ------------------------------------------------------------------ */
/* Limits                                                              */
/* ------------------------------------------------------------------ */

export const Limits: React.FC = () => (
  <>
    <H2 id="limits-table">Limits</H2>
    <Table
      head={['Limit', 'Value', 'Notes']}
      minWidth={620}
      rows={[
        ['Context window', KAEL.contextWindow, 'How much conversation Kael can read in one request.'],
        [
          'Response length',
          KAEL.maxOutput,
          <>
            Fixed. <C key="a">max_tokens</C> does not change it. Ask for shorter answers in your prompt.
          </>,
        ],
        ['Requests per minute', `${KAEL.requestsPerMinute} per account`, 'Counted across all your keys, both models and the Playground.'],
        ['Requests at once', `${KAEL.concurrentRequests} per account`, 'Requests that are still running.'],
        [
          'Requests per minute from one network',
          `${KAEL.ipRequestsPerMinute} per IP address`,
          'Checked before your key. Offices and shared networks count together.',
        ],
        ['Time per request', 'Minutes, not seconds', 'Hard requests, especially on Kael Pro Beta, can run for 20 minutes or more. One that takes too long is stopped with a timeout error.'],
        ['Input', 'Text and images', 'No PDFs, audio, or video.'],
        ['Output', 'Text', 'Kael does not create images or files.'],
      ]}
    />
    <P>
      These are the limits today. Kael is in beta, so they can change as we learn from real traffic.
    </P>

    <H2 id="when-you-hit-one">When you hit one</H2>
    <P>
      Going over a rate or concurrency limit returns <C>429</C> with the code <C>rate_limit_exceeded</C> or{' '}
      <C>concurrency_limit_exceeded</C>. Wait, then retry with exponential backoff. See{' '}
      <A href={docsHref('errors')}>Errors</A>.
    </P>
    <P>
      Long requests can run for minutes. <A href={docsHref('streaming')}>Stream</A> them, and set your client timeout
      to {KAEL.clientTimeoutMinutes} minutes or more.
    </P>

    <H2 id="published-commitments">What we do not publish yet</H2>
    <P>
      There is no uptime commitment or SLA yet, and no worst-case latency figures for long prompts. See{' '}
      <A href={docsHref('not-yet')}>Not available yet</A>.
    </P>
  </>
);

/* ------------------------------------------------------------------ */
/* Errors                                                              */
/* ------------------------------------------------------------------ */

const ERR_SHAPE = `{
  "error": {
    "message": "Insufficient balance ($0.00). Add funds to continue.",
    "type": "insufficient_balance",
    "code": "insufficient_balance"
  }
}`;

const ERR_RETRY = `import random
import time

RETRY = {429, 500, 502, 503, 504}

def with_retries(send, attempts=5):
    for attempt in range(attempts):
        response = send()
        if response.status_code not in RETRY:
            return response
        time.sleep(min(30, 2 ** attempt) + random.random())  # backoff with jitter
    return response`;

export const Errors: React.FC = () => (
  <>
    <H2 id="error-shape">Error shape</H2>
    <P>
      Errors return an HTTP status and a JSON body with an <C>error</C> object. Use <C>code</C> to decide what to do;
      the <C>message</C> is for people.
    </P>
    <CodeBlock tabs={[{ label: '402 response', lang: 'json', code: ERR_SHAPE }]} />
    <P>
      This shape is used on every route. The one exception is an unknown model on the Messages route, which answers in
      Anthropic&apos;s shape: <C>type: &quot;error&quot;</C> with a nested <C>error</C> object.
    </P>

    <H2 id="error-codes">Status and error codes</H2>
    <Table
      head={['Status', 'Code', 'Meaning', 'What to do']}
      minWidth={760}
      rows={[
        ['400', <C key="1">invalid_json</C>, 'The body is not a valid JSON object.', 'Fix the request body.'],
        ['400', <C key="2">model_not_found</C>, 'The model name is not recognized.', <>Use <C key="x">{BETA.id}</C> or <C key="y">{PRO_BETA.id}</C>.</>],
        [
          '400',
          <>
            <C key="3">param: reasoning_effort</C>
          </>,
          'The model you called does not offer that thinking level.',
          <>
            {BETA.name}: {listWords(BETA.thinkingLevels)}. {PRO_BETA.name}: {listWords(PRO_BETA.thinkingLevels)}. See{' '}
            <A href={docsHref('thinking')}>Thinking levels</A>.
          </>,
        ],
        ['400', <C key="12">invalid_request</C>, 'The request was rejected as invalid.', 'Check your messages, tools and parameters.'],
        ['400', <C key="13">context_length_exceeded</C>, 'The request is too long for the context window.', 'Shorten the messages, tools or attachments.'],
        ['401', <C key="4">missing_api_key</C>, 'No API key was sent.', 'Send a key in a supported header.'],
        ['401', <C key="5">invalid_api_key</C>, 'The key is unknown or revoked.', 'Create a new key.'],
        ['402', <C key="6">insufficient_balance</C>, 'Your balance is $0 or below.', 'Add credit, then retry.'],
        ['413', <C key="14">request_too_large</C>, 'The request is too large.', 'Send less data.'],
        ['429', <C key="7">rate_limit_exceeded</C>, 'Too many requests in a minute, or Kael is briefly busy.', 'Back off, then retry.'],
        ['429', <C key="8">concurrency_limit_exceeded</C>, 'Too many requests running at once.', 'Wait for one to finish.'],
        ['500', <C key="9">billing_unavailable</C>, 'Your balance could not be checked.', 'Retry shortly.'],
        ['502', <C key="10">upstream_unreachable</C>, 'Kael could not complete the request.', 'Retry.'],
        ['502', <C key="15">upstream_error</C>, 'Kael could not complete the request.', 'Retry.'],
        ['503', <C key="16">upstream_unavailable</C>, 'Kael is temporarily unavailable.', 'Retry shortly, with backoff.'],
        ['504', <C key="11">upstream_timeout</C>, 'The request took too long.', 'Retry, or lower the thinking level or split the task.'],
      ]}
    />

    <H2 id="what-to-retry">What to retry</H2>
    <Ul>
      <li>
        <strong>Retry</strong> <C>429</C>, <C>500</C>, <C>502</C>, <C>503</C> and <C>504</C>, with exponential backoff and a little
        random jitter.
      </li>
      <li>
        <strong>Do not retry</strong> <C>400</C>, <C>401</C>, <C>402</C> or <C>413</C> until you have fixed the cause. The same
        request will fail the same way.
      </li>
      <li>A retry is a new request, billed like any other if it succeeds.</li>
    </Ul>
    <CodeBlock tabs={[{ label: 'Python', lang: 'python', code: ERR_RETRY }]} />

    <H2 id="errors-in-a-stream">Errors in a stream</H2>
    <P>
      An error before streaming starts uses a normal status code. An error after it starts arrives as an event inside
      the stream, because the status is already <C>200</C>. See <A href={docsHref('streaming')}>Streaming</A>.
    </P>
  </>
);

/* ------------------------------------------------------------------ */
/* Data and privacy                                                    */
/* ------------------------------------------------------------------ */

export const Privacy: React.FC = () => (
  <>
    <Callout title="The Privacy Policy is the binding document">
      <p>
        This page summarizes it. If they ever differ, the <A href={ROUTES.privacy}>Privacy Policy</A> and the{' '}
        <A href={ROUTES.terms}>Terms of Service</A> win.
      </p>
    </Callout>

    <H2 id="training">Training</H2>
    <P>
      Quancis does not use your prompts, your Playground conversations, your pictures, or Kael&apos;s answers to train
      or improve its models. If that ever changed, it would be opt-in only.
    </P>

    <H2 id="how-long-we-keep-requests">What is stored, and for how long</H2>
    <Ul>
      <li>
        <strong>API requests:</strong> the text of your prompts and of Kael&apos;s answers is <strong>not stored</strong>.
        We keep only usage and billing records: the time, model, status, token counts, and cost.
      </li>
      <li>
        <strong>Playground conversations</strong> are saved to your account so you can come back to them. They stay
        until you delete them or delete your account. See <A href={docsHref('playground')}>Playground</A>.
      </li>
      <li>
        <strong>Playground diagnostic records:</strong> each Playground request also leaves a short technical record
        (timings, status, and a truncated excerpt of your last message and the answer). It is deleted with its
        conversation, and in any case after 30 days.
      </li>
      <li>
        <strong>Flagged content:</strong> requests and answers are screened for content that breaks the{' '}
        <A href={ROUTES.terms}>Terms of Service</A>. If something is flagged, it is kept until the support team has
        reviewed it, and, if action is taken, for up to 90 days afterwards. The account can be paused while that
        happens. If the flag was a false positive, it is cleared and deleted, and the account restored.
      </li>
    </Ul>

    <H2 id="what-we-record">What we record</H2>
    <Ul>
      <li>
        <strong>Usage records:</strong> for each request, the time, model, status, token counts, response time, and the
        key used. They contain no prompt or answer text. This powers your dashboard and your bill.
      </li>
      <li>
        <strong>Billing records:</strong> your credit balance and a history of purchases, charges, and expired credits.
      </li>
      <li>
        <strong>Technical logs:</strong> such as IP addresses, kept by our hosting providers for a limited time for
        security and fraud prevention.
      </li>
      <li>
        <strong>Account details:</strong> your name and email, for as long as the account exists.
      </li>
      <li>
        <strong>Payments</strong> are handled by our payment provider, Lemon Squeezy, which acts as Merchant of Record.
        We never see or store your card details.
      </li>
    </Ul>

    <H2 id="who-processes-requests">Who processes your requests</H2>
    <P>
      Kael generates answers using third-party AI infrastructure and processing providers, so your prompts are shared
      with them as needed to produce a response. Requests are sent only to providers that state that they do not store
      your content beyond what is needed to produce the answer, and do not train on it. If none is available, the
      request fails rather than going to another provider. We rely on what the providers state and cannot audit
      them. Because those providers may operate outside South Africa, information can be processed in other
      countries. See the <A href={ROUTES.privacy}>Privacy Policy</A> for the details.
    </P>

    <H2 id="your-rights">Your rights</H2>
    <P>
      You can ask to access, correct, or delete the personal information we hold about you. You can delete a Playground
      conversation from the conversation list, revoke a key on the API keys page, and permanently delete your whole
      account on the Account page (any credits left are lost, so ask for a refund you are due first). For anything
      else, email <A href="mailto:response@quancis.space">response@quancis.space</A> from your account email address.
      We may ask you to verify your identity first.
    </P>

    <H2 id="what-we-never-show">What Kael never reveals</H2>
    <P>
      Quancis does not name the models Kael is built on, in answers, errors, or anywhere else in the product. Error
      messages are generic on purpose.
    </P>
  </>
);
