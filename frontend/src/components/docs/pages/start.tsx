import React from 'react';
import { BETA, KAEL, PRO_BETA, usd } from '../facts';
import { docsHref } from '../nav';
import { A, C, Callout, CodeBlock, CopyField, FactList, H2, KeysLink, P, Step, Steps, Table, Ul } from '../primitives';

/* ------------------------------------------------------------------ */
/* Overview (/docs)                                                    */
/* ------------------------------------------------------------------ */

export const Overview: React.FC = () => (
  <>
    <FactList
      rows={[
        { label: `${BETA.name} model ID`, value: <CopyField value={BETA.id} /> },
        { label: `${PRO_BETA.name} model ID`, value: <CopyField value={PRO_BETA.id} /> },
        { label: 'Base URL for OpenAI SDKs', value: <CopyField value={KAEL.openaiBase} /> },
        { label: 'Base URL for Anthropic SDKs', value: <CopyField value={KAEL.anthropicBase} /> },
        { label: 'Formats', value: 'Chat Completions, Responses, Anthropic Messages' },
        { label: 'Input and output', value: 'Text and images in, text out' },
        { label: 'Context window', value: KAEL.contextWindow },
        { label: 'Maximum response', value: KAEL.maxOutput },
        {
          label: `${BETA.name} price per 1M tokens`,
          value: `${usd(BETA.price.input)} input, ${usd(BETA.price.cachedInput)} cached input, ${usd(BETA.price.output)} output`,
        },
        {
          label: `${PRO_BETA.name} price per 1M tokens`,
          value: `${usd(PRO_BETA.price.input)} input, ${usd(PRO_BETA.price.cachedInput)} cached input, ${usd(PRO_BETA.price.output)} output`,
        },
      ]}
    />

    <H2 id="start-here">Start here</H2>
    <Ul>
      <li>
        <A href={docsHref('quickstart')}>Quickstart</A>: create a key and send your first request.
      </li>
      <li>
        <A href={docsHref('pricing')}>Pricing and billing</A>: know what a request costs before you build on it.
      </li>
      <li>
        <A href={docsHref('playground')}>Playground</A>: try Kael in the browser, no code.
      </li>
      <li>
        <A href={docsHref('endpoints')}>Endpoints</A>: the three request formats and their routes.
      </li>
    </Ul>

    <H2 id="what-to-expect">What to expect</H2>
    <Ul>
      <li>
        <strong>Answers are checked.</strong> Kael favors correctness over speed. See{' '}
        <A href={docsHref('about')}>About Kael</A>.
      </li>
      <li>
        <strong>It is slower than a single model call, on purpose.</strong> Kael favors correctness over speed. Choose
        how hard it works with <A href={docsHref('thinking')}>thinking levels</A>. <C>low</C>, the default for{' '}
        {BETA.name}, is the quickest. {PRO_BETA.name} is slower again.
      </li>
      <li>
        <strong>You pay for your input and the final answer.</strong> Everything Kael does internally is free to you.
      </li>
      <li>
        <strong>Your existing code mostly keeps working.</strong> Sampling settings such as <C>temperature</C> are
        accepted and ignored. See <A href={docsHref('request-fields')}>Request fields</A>.
      </li>
    </Ul>

    <Callout title="Kael is in beta">
      <p>
        Details can change as we learn from real use. Minor fixes ship under the same model ID. Major changes get a new
        model ID, so a change never silently replaces the behavior you tested.
      </p>
    </Callout>
  </>
);

/* ------------------------------------------------------------------ */
/* Quickstart                                                          */
/* ------------------------------------------------------------------ */

const PROMPT = 'What is wrong with this loop? for i in range(len(xs) + 1): total += xs[i]';

const QS_CURL = String.raw`curl https://api.quancis.space/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QUAN_API_KEY" \
  -d '{
    "model": "kael-beta",
    "messages": [
      {"role": "user", "content": "${PROMPT}"}
    ]
  }'`;

const QS_PYTHON = `from openai import OpenAI

client = OpenAI(
    base_url="https://api.quancis.space/v1",
    api_key="sk-quan-...",  # load this from an environment variable
)

reply = client.chat.completions.create(
    model="kael-beta",
    messages=[
        {"role": "user", "content": "${PROMPT}"},
    ],
)

print(reply.choices[0].message.content)`;

const QS_TS = `import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'https://api.quancis.space/v1',
  apiKey: process.env.QUAN_API_KEY,
});

const reply = await client.chat.completions.create({
  model: 'kael-beta',
  messages: [
    { role: 'user', content: '${PROMPT}' },
  ],
});

console.log(reply.choices[0].message.content);`;

const QS_ANTHROPIC = `import anthropic

client = anthropic.Anthropic(
    base_url="https://api.quancis.space",  # no /v1: the SDK adds /v1/messages
    api_key="sk-quan-...",
)

message = client.messages.create(
    model="kael-beta",
    max_tokens=1024,  # the SDK requires it; Kael ignores it
    messages=[
        {"role": "user", "content": "${PROMPT}"},
    ],
)

print(message.content[0].text)`;

const QS_RESPONSE = `{
  "id": "...",
  "object": "chat.completion",
  "created": 1790000000,
  "model": "kael-beta",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The range goes one step too far: ..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 38,
    "completion_tokens": 214,
    "total_tokens": 252,
    "prompt_cache_hit_tokens": 0
  }
}`;

export const Quickstart: React.FC = () => (
  <>
    <Steps>
      <Step n={1} title="Create an API key">
        <P>
          Sign in, open <KeysLink>API keys</KeysLink>, choose <strong>New Key</strong>, name it, and choose{' '}
          <strong>Create Key</strong>. Leave Thinking level on SDK unless your tool cannot set one. Copy the secret
          straight away. It starts with <C>{KAEL.keyPrefix}</C> and is
          shown only once.
        </P>
      </Step>
      <Step n={2} title="Check your balance">
        <P>
          Kael is prepaid. A request is refused with a <C>402</C> error when your balance is $0 or below. Your balance
          is on the <A href="/dashboard">dashboard</A>. To add credit, see{' '}
          <A href={docsHref('pricing')}>Pricing and billing</A>.
        </P>
      </Step>
      <Step n={3} title="Send a request">
        <P>
          Use the OpenAI SDK you already have, or plain HTTP. Only the base URL and the model name change. Kael also
          speaks the Anthropic Messages format; the last tab shows it.
        </P>
        <CodeBlock
          tabs={[
            { label: 'cURL', lang: 'bash', code: QS_CURL },
            { label: 'Python', lang: 'python', code: QS_PYTHON },
            { label: 'TypeScript', lang: 'ts', code: QS_TS },
            { label: 'Anthropic SDK', lang: 'python', code: QS_ANTHROPIC },
          ]}
        />
      </Step>
    </Steps>

    <Callout title="The first reply takes a moment">
      <p>
        Kael works a request through before it answers, so expect more latency than a single model call. For long jobs,{' '}
        <A href={docsHref('streaming')}>stream</A> the response. To trade depth for speed, see{' '}
        <A href={docsHref('thinking')}>thinking levels</A>.
      </p>
    </Callout>

    <H2 id="read-the-response">Read the response</H2>
    <P>
      The answer is in <C>choices[0].message.content</C>. The <C>usage</C> object shows exactly what you were billed
      for: <C>prompt_tokens</C> in, <C>completion_tokens</C> out, and how many input tokens were served from cache.
    </P>
    <CodeBlock tabs={[{ label: 'Response', lang: 'json', code: QS_RESPONSE }]} />

    <H2 id="next">Next</H2>
    <Ul>
      <li>
        Use a different format or route: <A href={docsHref('endpoints')}>Endpoints</A>.
      </li>
      <li>
        Make Kael think harder on a hard request, or use {PRO_BETA.name} for the hardest ones:{' '}
        <A href={docsHref('thinking')}>Thinking levels</A>.
      </li>
      <li>
        Handle failures: <A href={docsHref('errors')}>Errors</A>.
      </li>
    </Ul>
  </>
);

/* ------------------------------------------------------------------ */
/* Authentication                                                      */
/* ------------------------------------------------------------------ */

const AUTH_MESSAGES = String.raw`curl https://api.quancis.space/v1/messages \
  -H "x-api-key: $QUAN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kael-beta",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}]
  }'`;

export const Authentication: React.FC = () => (
  <>
    <H2 id="send-your-key">Send your key</H2>
    <P>
      Every request needs an API key. Send it in whichever header your SDK already uses:
    </P>
    <Table
      head={['Header', 'Used by']}
      minWidth={440}
      rows={[
        [<C key="a">Authorization: Bearer sk-quan-...</C>, 'OpenAI SDKs, curl, and most HTTP clients'],
        [<C key="b">x-api-key: sk-quan-...</C>, 'Anthropic SDKs'],
      ]}
    />
    <P>
      If a request carries both, <C>x-api-key</C> is the one used.
    </P>
    <CodeBlock tabs={[{ label: 'x-api-key with the Messages route', lang: 'bash', code: AUTH_MESSAGES }]} />

    <H2 id="what-a-key-can-do">What a key can do</H2>
    <Ul>
      <li>
        A key works on every endpoint and every format. It is not tied to one model or route.
      </li>
      <li>
        Everything a key does is billed to your account balance. The <A href={docsHref('playground')}>Playground</A>{' '}
        draws from the same balance.
      </li>
      <li>
        Keys cannot yet be limited to certain endpoints or capped at a spend amount. Treat each key as full access to
        your balance.
      </li>
    </Ul>

    <H2 id="keep-keys-safe">Keep keys safe</H2>
    <Ul>
      <li>
        <strong>Keep keys on the server.</strong> Never put one in browser or mobile app code. Load it from an
        environment variable.
      </li>
      <li>
        <strong>The secret is shown once.</strong> Quancis stores only a hash of it, so a lost key cannot be recovered.
        Create a new one and delete the old one.
      </li>
      <li>
        <strong>Use one key per app or environment</strong>, named for it (for example Production or CI). You can then
        delete one without touching the others.
      </li>
      <li>
        <strong>Delete a leaked key immediately.</strong> Deleting a key revokes it, and it stops working on its next
        request. See{' '}
        <A href={docsHref('api-keys')}>API keys</A>.
      </li>
      <li>
        If an account is suspended, its keys are revoked. Reactivating the account does not bring them back, so create
        new keys.
      </li>
    </Ul>

    <H2 id="authentication-errors">Authentication errors</H2>
    <P>
      A missing key returns <C>401</C> with the code <C>missing_api_key</C>. An unknown or revoked key returns{' '}
      <C>401</C> with <C>invalid_api_key</C>. See <A href={docsHref('errors')}>Errors</A> for the full list.
    </P>
  </>
);
