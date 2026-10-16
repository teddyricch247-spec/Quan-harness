import React from 'react';
import { ROUTES } from '../../../lib/routes';
import { CONTACT } from '../facts';
import { docsHref } from '../nav';
import { A, C, Callout, H2, P, Table, Ul } from '../primitives';

/* ------------------------------------------------------------------ */
/* Not available yet                                                   */
/* ------------------------------------------------------------------ */

export const NotYet: React.FC = () => (
  <>
    <P>
      Kael is in beta. This is what it does not do today. If something here is missing for you, tell us at{' '}
      <A href={`mailto:${CONTACT.support}`}>{CONTACT.support}</A>.
    </P>

    <H2 id="inputs-and-outputs">Inputs and outputs</H2>
    <Ul>
      <li>
        <strong>Files:</strong> PDFs, audio, video, and other file types. Images are supported. See{' '}
        <A href={docsHref('images')}>Images</A>.
      </li>
      <li>
        <strong>Output other than text:</strong> Kael does not create images, audio, or files.
      </li>
      <li>
        <strong>Languages other than English.</strong> Kael is built and tested for English. Other languages have not
        been tested, so they are not listed as supported.
      </li>
    </Ul>

    <H2 id="controls">Controls</H2>
    <Ul>
      <li>
        <strong>Auto thinking level:</strong> there is no <C>auto</C>. Choose a level yourself: <C>low</C>, <C>high</C> or{' '}
        <C>max</C> for Kael Beta, and <C>z-low</C> or <C>z-high</C> for Kael Pro Beta. See{' '}
        <A href={docsHref('thinking')}>Thinking levels</A>.
      </li>
      <li>
        <strong>Sampling:</strong> <C>temperature</C>, <C>top_p</C>, <C>seed</C> and similar settings are ignored.
        Output is not deterministic.
      </li>
      <li>
        <strong>Response length:</strong> <C>max_tokens</C> is ignored. Ask for the length you want in your prompt.
      </li>
      <li>
        <strong>Structured output:</strong> <C>response_format</C> is not enforced, and <C>tool_choice</C> is not
        enforced. Ask for JSON in your prompt and validate it. See{' '}
        <A href={docsHref('request-fields')}>Request fields</A>.
      </li>
      <li>
        <strong>Built-in tools:</strong> web search, code execution, and file search are not available. Your own
        function tools are.
      </li>
      <li>
        <strong>Answer caching:</strong> answers are never cached. Input caching exists and is automatic.
      </li>
    </Ul>

    <H2 id="platform">Platform</H2>
    <Ul>
      <li>
        <strong>Key permissions and spend caps:</strong> a key can use every endpoint and your whole balance.
      </li>
      <li>
        <strong>Other APIs:</strong> no embeddings, batch API, fine-tuning, or file uploads.
      </li>
      <li>
        <strong>Downloadable or self-hosted weights:</strong> Kael is available only through the API and Quancis apps.
      </li>
    </Ul>

    <H2 id="not-published">Not published yet</H2>
    <Ul>
      <li>A model card or technical report.</li>
      <li>An uptime commitment or SLA, and worst-case latency figures for long prompts.</li>
      <li>Benchmark results. Quancis does not publish scores it ran itself.</li>
    </Ul>

    <H2 id="versioning">Versioning</H2>
    <P>
      Minor bug fixes ship silently under the same model ID. A major change gets a new model ID, such as{' '}
      <C>kael-beta-1-1</C>, so you choose when to move. Details can change during the beta as we learn from real use.
    </P>
  </>
);

/* ------------------------------------------------------------------ */
/* Support                                                             */
/* ------------------------------------------------------------------ */

export const Support: React.FC = () => (
  <>
    <H2 id="contact">Contact</H2>
    <Table
      head={['', 'Address']}
      minWidth={420}
      rows={[
        ['Support', <A key="s" href={`mailto:${CONTACT.support}`}>{CONTACT.support}</A>],
        ['Business', <A key="b" href={`mailto:${CONTACT.business}`}>{CONTACT.business}</A>],
      ]}
    />

    <H2 id="what-to-include">What to include</H2>
    <P>A few details let us find your request quickly:</P>
    <Ul>
      <li>
        The time of the request, with its time zone (the console uses GMT+2).
      </li>
      <li>
        The endpoint you called and the HTTP status or error <C>code</C> you got.
      </li>
      <li>
        The <strong>name</strong> of the key you used. Never send the secret itself.
      </li>
      <li>What you expected, and what happened.</li>
    </Ul>
    <Callout title="Never send your API key or prompts you want kept private">
      <p>
        We do not need your secret to look into a problem. If a key has been exposed, delete it first, then write to us.
      </p>
    </Callout>

    <H2 id="company">Company</H2>
    <P>
      {CONTACT.company} is based in {CONTACT.region}.
    </P>
    <P>
      Terms and privacy: <A href={ROUTES.terms}>Terms of Service</A> and <A href={ROUTES.privacy}>Privacy Policy</A>.
    </P>
  </>
);
