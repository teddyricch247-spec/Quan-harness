import React from 'react';
import { ROUTES } from '../../../lib/routes';
import { BETA, KAEL, PRO_BETA } from '../facts';
import { docsHref } from '../nav';
import { A, C, Callout, H2, P, Table, Ul } from '../primitives';

/* ------------------------------------------------------------------ */
/* Dashboard and usage                                                 */
/* ------------------------------------------------------------------ */

export const Dashboard: React.FC = () => (
  <>
    <H2 id="dashboard">The dashboard</H2>
    <P>
      The <A href={ROUTES.dashboard}>dashboard</A> is the first page after you sign in. It shows two numbers and a
      request log.
    </P>
    <Ul>
      <li>
        <strong>Prepaid Balance:</strong> what you have left to spend. <strong>Top up</strong> opens the Usage page, where you add credit.
      </li>
      <li>
        <strong>Active Secret Keys:</strong> how many keys can still make requests. <strong>Manage</strong> opens{' '}
        <A href={docsHref('api-keys')}>API keys</A>.
      </li>
    </Ul>
    <Callout title="Times and delays">
      <p>All dates and times in the console are GMT+2. Data can be up to 5 minutes behind.</p>
    </Callout>

    <H2 id="request-log">The request log</H2>
    <P>Each row is one request. Until you make your first call, the log is empty.</P>
    <Table
      head={['Column', 'What it shows']}
      minWidth={520}
      rows={[
        ['Timestamp', 'When the request ran.'],
        ['Model', <>The model the request ran on: <C key="a">{BETA.id}</C> or <C key="b">{PRO_BETA.id}</C>.</>],
        ['Endpoint', 'The route you called.'],
        ['Status', 'The HTTP status, shown as OK below 400 and as Error otherwise.'],
        ['Tokens', 'The tokens you were billed for, input and output together.'],
        ['Cache', 'Shows Cached when part of the input was served from cache.'],
        ['Latency', 'How long the request took, in milliseconds.'],
        ['Cost', 'An estimate of what the request cost.'],
      ]}
    />

    <H2 id="usage-page">Usage, cost and billing</H2>
    <P>
      Open it from the menu as <strong>Usage &amp; Cost</strong>, or from <strong>View Full Cost Analytics</strong> on
      the dashboard. Its page is <A href={ROUTES.usage}>{ROUTES.usage}</A>.
    </P>
    <Ul>
      <li>
        <strong>Available balance</strong>, and the share of your input tokens that hit the cache.
      </li>
      <li>
        <strong>Daily token and cost chart.</strong> Each day is split into cached input, uncached input, and output.
      </li>
      <li>
        <strong>Usage by product.</strong> Tokens and cost for each model, {BETA.name} and {PRO_BETA.name}.
      </li>
      <li>
        <strong>Add Prepaid Credits.</strong> Pick $25, $50 or $100 and pay by card. The window shows roughly how many
        input tokens the amount buys. See <A href={docsHref('pricing')}>Pricing and billing</A>.
      </li>
      <li>
        <strong>Billing History &amp; Invoices.</strong> Your top-ups, each with an invoice number.
      </li>
    </Ul>

    <H2 id="estimates">Costs are estimates</H2>
    <P>
      The dashboard and Usage page work out each cost from the request&apos;s token counts at today&apos;s price. They
      are a good guide, not an invoice. If prices change, past requests are shown at the new price.
    </P>
  </>
);

/* ------------------------------------------------------------------ */
/* Playground                                                          */
/* ------------------------------------------------------------------ */

export const Playground: React.FC = () => (
  <>
    <H2 id="what-it-is">What it is</H2>
    <P>
      The <A href={ROUTES.playground}>Playground</A> is a chat with Kael in your browser. It runs the same system as
      the API, and it is billed the same way: at the same per-token prices, from the same balance. There is no
      separate Playground quota.
    </P>

    <H2 id="conversations">Your conversations</H2>
    <Ul>
      <li>Each conversation has its own address, <C>/playground/&lt;id&gt;</C>, so you can bookmark it or share the link with yourself.</li>
      <li>Conversations are saved to your account. Rename or delete them from the sidebar.</li>
      <li>
        A saved conversation stays until you delete it. See <A href={docsHref('privacy')}>Data and privacy</A>.
      </li>
    </Ul>

    <H2 id="thinking-level">Thinking level</H2>
    <P>
      Open the settings to choose a model and a thinking level. {BETA.name} offers <C>low</C>, <C>high</C> and{' '}
      <C>max</C>, with <C>low</C> as the default. {PRO_BETA.name} offers <C>z-low</C> and <C>z-high</C>, with{' '}
      <C>z-low</C> as the default. Each model keeps its own level, and your choices are remembered in this browser. A
      level applies to your next message.
    </P>
    <P>
      You choose the model before the first message of a conversation. After that the conversation stays on that model,
      so to use the other one, start a new conversation. The sidebar shows which model each conversation uses. See{' '}
      <A href={docsHref('thinking')}>Thinking levels</A>.
    </P>

    <H2 id="thinking-steps">Thinking steps</H2>
    <P>
      While Kael works, the Playground shows the latest short thinking title in place of &quot;Thinking&quot;. When
      the answer arrives, a collapsed <strong>Thinking</strong> row lists every step. The steps are saved with the
      reply, so they are still there after a reload. They are summaries, not Kael&apos;s raw reasoning.
    </P>

    <H2 id="sending-messages">Sending messages</H2>
    <Ul>
      <li>
        On a computer, <strong>Enter</strong> sends and <strong>Shift + Enter</strong> starts a new line.
      </li>
      <li>On touch screens, Enter starts a new line. Use the send button.</li>
      <li>A message can be up to {KAEL.playgroundMessageChars} characters.</li>
      <li>
        One reply at a time per conversation. Sending while a reply is still running returns a <C>409</C> busy error.
      </li>
    </Ul>

    <H2 id="connection-lost">If you lose your connection</H2>
    <P>
      A reply keeps running even if you go offline, close the tab, or reload. When you come back, the Playground
      reconnects and shows the reply as soon as it is saved. If the message never arrived, you get a{' '}
      <strong>Retry</strong> button instead.
    </P>
    <P>
      There is no Stop button, on purpose. Kael finishes, saves, and bills the reply even if you leave, so stopping on
      your side would only hide a reply that still arrives.
    </P>

    <H2 id="long-chats">Long conversations</H2>
    <P>
      Kael reads the most recent {KAEL.playgroundHistoryMessages} messages, up to {KAEL.playgroundHistoryChars}{' '}
      characters. In a very long chat it forgets the oldest turns. Your saved conversation is not changed.
    </P>

    <H2 id="playground-errors">When something goes wrong</H2>
    <P>
      A failed message shows a red notice with a <strong>Retry</strong> button. If your balance is $0 or below, add
      credit first. See <A href={docsHref('errors')}>Errors</A>.
    </P>
  </>
);

/* ------------------------------------------------------------------ */
/* API keys                                                            */
/* ------------------------------------------------------------------ */

export const ApiKeys: React.FC = () => (
  <>
    <H2 id="create-a-key">Create a key</H2>
    <Ul>
      <li>
        Open <A href={ROUTES.keys}>API keys</A> and choose <strong>New Key</strong>.
      </li>
      <li>
        Give it a name, such as Production, CI/CD, or Development. Leave <strong>Thinking level</strong> on SDK unless the
        tool that will use the key cannot set one (see <A href="#thinking-level">Thinking level for a key</A>). Then
        choose <strong>Create Key</strong>.
      </li>
      <li>
        Copy the secret and store it somewhere safe, then choose <strong>Done</strong>.
      </li>
    </Ul>
    <Callout tone="warn" title="The secret is shown once">
      <p>
        You cannot view it again, and Quancis cannot recover it, because only a hash is stored. If you lose it, create a
        new key.
      </p>
    </Callout>

    <H2 id="your-keys">Your keys</H2>
    <P>The table lists every key you have created:</P>
    <Table
      head={['Column', 'What it shows']}
      minWidth={480}
      rows={[
        ['Name', 'The name you gave it.'],
        ['Key', <>The start of the key, for example <C key="a">{KAEL.keyPrefix}ab12</C>, with the rest hidden.</>],
        ['Created', 'When you made it.'],
        ['Thinking level', 'A dropdown: SDK, or a level of Kael Beta (Low, High, Max) or Kael Pro Beta (z-low, z-high). Change it here at any time.'],
        [
          'Actions',
          <>
            A menu with <strong key="v">View Details</strong>, which also shows when the key was last used (a good way
            to spot an unused key), and <strong key="d">Delete Key</strong>.
          </>,
        ],
      ]}
    />

    <H2 id="thinking-level">Thinking level for a key</H2>
    <P>
      Some tools, such as Cursor, cannot send a <C>reasoning_effort</C> with their requests, so they could only ever run
      at the default level. Every key therefore has its own Thinking level setting, in the table and in the New Key form:
    </P>
    <Ul>
      <li>
        <strong>SDK</strong> (the default) leaves the choice to your code. Each request sets its own level, and a
        request that sets none runs at the model&apos;s default: <C>{BETA.defaultLevel}</C> for {BETA.name},{' '}
        <C>{PRO_BETA.defaultLevel}</C> for {PRO_BETA.name}.
      </li>
      <li>
        <strong>Low, High or Max</strong> pins that level for {BETA.name}. <strong>z-low or z-high</strong> pins it for{' '}
        {PRO_BETA.name}. Every request to that model made with the key runs at the level, and whatever the request itself
        says is ignored, including a value Kael would otherwise reject.
      </li>
    </Ul>
    <P>
      A key holds one level, so it applies to one model. Requests from the same key to the other model behave as if
      the key were on SDK: the request decides. A change applies from the key&apos;s next request, and the key itself
      does not change, so you do not need to update the tool. {PRO_BETA.name} costs more per token than {BETA.name}, so
      check <A href={docsHref('pricing')}>Pricing and billing</A> before pinning a key to z-low or z-high. See{' '}
      <A href={docsHref('thinking')}>Thinking levels</A> for what each level does.
    </P>

    <H2 id="delete-a-key">Delete a key</H2>
    <P>
      <strong>Delete Key</strong> revokes the key. It takes effect at once, there is no confirmation step, and it
      cannot be undone. The key fails with <C>invalid_api_key</C> on its next request. Create a new key instead.
    </P>
    <P>
      To rotate a key without downtime: create the new key, deploy it, check that the old key&apos;s last used time (in View Details)
      stops changing, then delete the old one. More on safe handling in <A href={docsHref('authentication')}>Authentication</A>.
    </P>
  </>
);

/* ------------------------------------------------------------------ */
/* Account                                                             */
/* ------------------------------------------------------------------ */

export const Account: React.FC = () => (
  <>
    <H2 id="profile">Profile</H2>
    <P>
      <A href={ROUTES.account}>Account</A> has three tabs: Profile, Security and Notifications. On Profile you can change
      your full name. Your email cannot be changed here, because it is tied to how you sign in.
    </P>

    <H2 id="security">Security</H2>
    <Ul>
      <li>
        On the Security tab you can set a new password of at least 8 characters, if you sign in with email and
        password.
      </li>
      <li>
        If you signed in with Google or GitHub, there is no password to change here. You manage it with that provider.
      </li>
      <li>
        Forgot your password? Use the link on the sign-in page. Quancis emails you a reset link, and the page never
        reveals whether an email address has an account.
      </li>
    </Ul>

    <H2 id="notifications">Notifications</H2>
    <P>
      On the Notifications tab, turn the low-balance email alert on and set the dollar amount it triggers at. Alerts
      depend on the service having them switched on, so do not rely on them as your only way to watch your balance.
    </P>

    <H2 id="signing-in">Signing in</H2>
    <P>
      The sign-in page offers email and password, Google, and GitHub. When you create an account you accept the{' '}
      <A href={ROUTES.terms}>Terms of Service</A> and <A href={ROUTES.privacy}>Privacy Policy</A>, and Quancis records
      that you did.
    </P>
  </>
);
