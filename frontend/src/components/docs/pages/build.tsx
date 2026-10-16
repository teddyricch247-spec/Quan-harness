import React from 'react';
import { BETA, KAEL, PRO_BETA, usd } from '../facts';
import { docsHref } from '../nav';
import { A, C, Callout, CodeBlock, H2, P, Route, Table, Ul } from '../primitives';

// "low, high and max" / "z-low and z-high": the levels of one model, as code snippets.
const levelList = (levels: readonly string[]): React.ReactNode =>
  levels.map((level, i) => (
    <React.Fragment key={level}>
      {i > 0 ? (i === levels.length - 1 ? ' and ' : ', ') : null}
      <C>{level}</C>
    </React.Fragment>
  ));

/* ------------------------------------------------------------------ */
/* Endpoints                                                           */
/* ------------------------------------------------------------------ */

const EP_CHAT = `POST /v1/chat/completions

{
  "model": "kael-beta",
  "messages": [
    {"role": "system", "content": "You are a careful code reviewer."},
    {"role": "user", "content": "Review this function for bugs: ..."}
  ],
  "reasoning_effort": "high"
}`;

const EP_RESPONSES = `POST /v1/responses

{
  "model": "kael-beta",
  "instructions": "You are a careful code reviewer.",
  "input": "Review this function for bugs: ...",
  "reasoning": {"effort": "high"}
}`;

const EP_MESSAGES = `POST /v1/messages

{
  "model": "kael-beta",
  "max_tokens": 1024,
  "system": "You are a careful code reviewer.",
  "messages": [
    {"role": "user", "content": "Review this function for bugs: ..."}
  ],
  "reasoning_effort": "high"
}`;

const EP_MODELS = `{
  "object": "list",
  "data": [
    {"id": "kael-beta", "object": "model", "created": 1755000000, "owned_by": "quancis"},
    {"id": "kael-pro-beta", "object": "model", "created": 1755000000, "owned_by": "quancis"}
  ]
}`;

const RES_RESPONSES = `{
  "id": "...",
  "status": "completed",
  "model": "kael-beta",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [
        {"type": "output_text", "text": "The range goes one step too far: ..."}
      ]
    }
  ],
  "usage": {
    "input_tokens": 38,
    "output_tokens": 214,
    "total_tokens": 252,
    "input_tokens_details": {"cached_tokens": 0}
  }
}`;

const RES_MESSAGES = `{
  "id": "...",
  "type": "message",
  "role": "assistant",
  "model": "kael-beta",
  "content": [
    {"type": "text", "text": "The range goes one step too far: ..."}
  ],
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {"input_tokens": 38, "output_tokens": 214}
}`;

export const Endpoints: React.FC = () => (
  <>
    <H2 id="routes">Routes</H2>
    <P>
      Kael speaks three request formats. Pick the one your SDK or framework already uses; the answer and the price are
      the same in all three.
    </P>
    <Table
      head={['Route', 'Format']}
      minWidth={460}
      rows={[
        [<Route key="1" method="POST" path="/v1/chat/completions" />, 'OpenAI Chat Completions'],
        [<Route key="2" method="POST" path="/v1/responses" />, 'OpenAI Responses'],
        [<Route key="3" method="POST" path="/v1/messages" />, 'Anthropic Messages'],
        [<Route key="4" method="GET" path="/v1/models" />, 'Lists the models you can call'],
      ]}
    />
    <Ul>
      <li>
        <strong>OpenAI SDKs</strong> use the base URL <C>{KAEL.openaiBase}</C> and add{' '}
        <C>/chat/completions</C> or <C>/responses</C> themselves.
      </li>
      <li>
        <strong>Anthropic SDKs</strong> use <C>{KAEL.anthropicBase}</C> with no <C>/v1</C>, because they add{' '}
        <C>/v1/messages</C> themselves.
      </li>
      <li>One API key works on every route. See <A href={docsHref('authentication')}>Authentication</A>.</li>
    </Ul>
    <Callout title="Model-specific paths">
      <p>
        If a tool cannot send a model name, put the model in the path instead: <C>/{BETA.id}/v1/...</C> or{' '}
        <C>/{PRO_BETA.id}/v1/...</C>, with the same routes as above. The path decides the model and the{' '}
        <C>model</C> field is not read.
      </p>
    </Callout>

    <H2 id="model-name">Model name</H2>
    <P>
      There are two models. Send the one you want as <C>model</C>. Any other value returns a <C>400</C> with the code{' '}
      <C>model_not_found</C>, and the message lists the two valid names.
    </P>
    <Table
      head={['model', 'Best for', 'Thinking levels']}
      minWidth={560}
      rows={[
        [
          <C key="b">{BETA.id}</C>,
          'Everyday reasoning.',
          <>
            {levelList(BETA.thinkingLevels)} (default <C>{BETA.defaultLevel}</C>)
          </>,
        ],
        [
          <C key="p">{PRO_BETA.id}</C>,
          'The hardest problems. Costs more per token.',
          <>
            {levelList(PRO_BETA.thinkingLevels)} (default <C>{PRO_BETA.defaultLevel}</C>)
          </>,
        ],
      ]}
    />
    <P>
      Prices are on the <A href={docsHref('pricing')}>Pricing and billing</A> page.
    </P>
    <CodeBlock tabs={[{ label: 'GET /v1/models', lang: 'json', code: EP_MODELS }]} />

    <H2 id="same-request">The same request in each format</H2>
    <CodeBlock
      tabs={[
        { label: 'Chat Completions', lang: 'text', code: EP_CHAT },
        { label: 'Responses', lang: 'text', code: EP_RESPONSES },
        { label: 'Messages', lang: 'text', code: EP_MESSAGES },
      ]}
    />
    <Table
      head={['', 'Chat Completions', 'Responses', 'Messages']}
      minWidth={760}
      rows={[
        [
          'System prompt',
          <>
            a <C>system</C> or <C>developer</C> message
          </>,
          <>
            <C>instructions</C>
          </>,
          <>
            top-level <C>system</C>
          </>,
        ],
        ['Thinking level', <C key="a">reasoning_effort</C>, <C key="b">reasoning.effort</C>, <C key="c">reasoning_effort</C>],
        [
          'Answer text',
          <C key="a">choices[0].message.content</C>,
          <>
            the <C>message</C> item in <C>output</C>
          </>,
          <>
            the <C>text</C> block in <C>content</C>
          </>,
        ],
        [
          'Tokens billed',
          <>
            <C>usage.prompt_tokens</C>, <C>usage.completion_tokens</C>
          </>,
          <>
            <C>usage.input_tokens</C>, <C>usage.output_tokens</C>
          </>,
          <>
            <C>usage.input_tokens</C>, <C>usage.output_tokens</C>
          </>,
        ],
        [
          'Cached tokens',
          <C key="a">usage.prompt_cache_hit_tokens</C>,
          <C key="b">usage.input_tokens_details.cached_tokens</C>,
          'Not reported',
        ],
        [
          'Why it stopped',
          <>
            <C>finish_reason</C>: <C>stop</C>, <C>length</C>, <C>tool_calls</C>
          </>,
          <>
            <C>status</C>: <C>completed</C>, <C>incomplete</C>
          </>,
          <>
            <C>stop_reason</C>: <C>end_turn</C>, <C>max_tokens</C>, <C>tool_use</C>
          </>,
        ],
      ]}
    />

    <H2 id="response-shapes">Response shapes</H2>
    <P>
      The Chat Completions response is shown in the <A href={docsHref('quickstart')}>Quickstart</A>. The other two
      look like this. A Responses <C>output</C> list can hold more than one kind of item, so read the one whose{' '}
      <C>type</C> is <C>message</C>.
    </P>
    <CodeBlock
      tabs={[
        { label: 'Responses', lang: 'json', code: RES_RESPONSES },
        { label: 'Messages', lang: 'json', code: RES_MESSAGES },
      ]}
    />
    <P>
      The <C>model</C> field always says the model you called, <C>{BETA.id}</C> or <C>{PRO_BETA.id}</C>. The{' '}
      <C>usage</C> you see is what you are billed. See{' '}
      <A href={docsHref('pricing')}>Pricing and billing</A>.
    </P>
  </>
);

/* ------------------------------------------------------------------ */
/* Request fields                                                      */
/* ------------------------------------------------------------------ */

export const RequestFields: React.FC = () => (
  <>
    <H2 id="fields-kael-uses">Fields Kael uses</H2>
    <Table
      head={['Field', 'Format', 'What it does']}
      minWidth={640}
      rows={[
        [<C key="1">model</C>, 'All', <>Required. <C>{BETA.id}</C> or <C>{PRO_BETA.id}</C>.</>],
        [<C key="2">messages</C>, 'Chat Completions, Messages', 'The conversation, oldest turn first.'],
        [<C key="3">input</C>, 'Responses', 'A string, or a list of input items.'],
        [<C key="4">instructions</C>, 'Responses', 'The system prompt.'],
        [<C key="5">system</C>, 'Messages', 'The system prompt.'],
        [<C key="6">stream</C>, 'All', <>Set <C>true</C> to receive the answer as server-sent events. See <A href={docsHref('streaming')}>Streaming</A>.</>],
        [<C key="7">stream_options.include_usage</C>, 'Chat Completions', 'Adds a final streamed chunk that carries usage.'],
        [<C key="8">tools</C>, 'All', <>Function tools Kael may call. See <A href={docsHref('tools')}>Tool calling</A>.</>],
        [
          <C key="9">reasoning_effort</C>,
          'Chat Completions, Messages',
          <>
            {levelList(BETA.thinkingLevels)} for <C>{BETA.id}</C>; {levelList(PRO_BETA.thinkingLevels)} for{' '}
            <C>{PRO_BETA.id}</C>. See <A href={docsHref('thinking')}>Thinking levels</A>.
          </>,
        ],
        [<C key="10">reasoning.effort</C>, 'Responses', 'The same setting, in the Responses shape.'],
      ]}
    />

    <H2 id="accepted-but-ignored">Accepted but ignored</H2>
    <P>
      So existing code keeps working, Kael accepts every standard parameter without an error. Only the fields above
      change what Kael does. These are the ones people most often expect to work:
    </P>
    <Table
      head={['Field', 'What to do instead']}
      minWidth={560}
      rows={[
        [
          <>
            <C>temperature</C>, <C>top_p</C>, <C>seed</C>, <C>n</C>, <C>stop</C>, penalties, <C>logprobs</C>
          </>,
          <>
            Nothing. Sampling is managed inside Kael. Output is <strong>not deterministic</strong>, so the same request
            can return different answers.
          </>,
        ],
        [
          <>
            <C>max_tokens</C>, <C>max_output_tokens</C>
          </>,
          <>
            A response can run up to {KAEL.maxOutput}. To keep answers short, ask for that in your prompt. The
            Messages format requires <C>max_tokens</C>, so send any value.
          </>,
        ],
        [
          <C key="1">response_format</C>,
          'JSON mode is not enforced. Ask for JSON in your prompt and validate what comes back.',
        ],
        [<C key="2">tool_choice</C>, 'Kael decides whether and which tool to call.'],
        [<C key="3">thinking</C>, <>Messages-format extended thinking. Use <C>reasoning_effort</C> instead.</>],
      ]}
    />
    <Callout tone="warn" title="Long answers cost real money">
      <p>
        Because <C>max_tokens</C> is ignored, an open-ended prompt can produce a very long answer, and output is the
        most expensive part of a bill. Say how long you want the answer to be.
      </p>
    </Callout>
  </>
);

/* ------------------------------------------------------------------ */
/* Thinking levels                                                     */
/* ------------------------------------------------------------------ */

const TH_CHAT = String.raw`curl https://api.quancis.space/v1/chat/completions \
  -H "Authorization: Bearer $QUAN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kael-beta",
    "reasoning_effort": "high",
    "messages": [{"role": "user", "content": "Find the race condition in this code: ..."}]
  }'`;

const TH_RESPONSES = String.raw`curl https://api.quancis.space/v1/responses \
  -H "Authorization: Bearer $QUAN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kael-beta",
    "reasoning": {"effort": "high"},
    "input": "Find the race condition in this code: ..."
  }'`;

const TH_MESSAGES = String.raw`curl https://api.quancis.space/v1/messages \
  -H "x-api-key: $QUAN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kael-beta",
    "max_tokens": 1024,
    "reasoning_effort": "high",
    "messages": [{"role": "user", "content": "Find the race condition in this code: ..."}]
  }'`;

const TH_PY = `reply = client.chat.completions.create(
    model="kael-beta",
    messages=[{"role": "user", "content": "Find the race condition in this code: ..."}],
    extra_body={"reasoning_effort": "high"},  # works on any SDK version
)`;

const TH_PRO = String.raw`curl https://api.quancis.space/v1/chat/completions \\
  -H "Authorization: Bearer $QUAN_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "kael-pro-beta",
    "reasoning_effort": "z-high",
    "messages": [{"role": "user", "content": "Find the race condition in this code: ..."}]
  }'`;

const TH_ERROR = `{
  "error": {
    "message": "Invalid reasoning_effort 'auto'. Kael Beta supports 'low', 'high', or 'max'.",
    "type": "invalid_request_error",
    "param": "reasoning_effort"
  }
}`;

export const Thinking: React.FC = () => (
  <>
    <H2 id="levels">Levels</H2>
    <P>
      A higher thinking level makes Kael work harder on a request. Each model has its own levels, and a model accepts
      only its own. Start at the model&apos;s default and move up when an answer is not good enough.
    </P>
    <P>
      <strong>{BETA.name}</strong> (<C>{BETA.id}</C>) has three levels.
    </P>
    <Table
      head={['Level', 'Use it for', 'Price per 1M tokens']}
      minWidth={640}
      rows={[
        [<><C>low</C> (default)</>, 'Everyday questions, quick edits, short answers.', `${usd(BETA.price.input)} in, ${usd(BETA.price.output)} out`],
        [<C key="h">high</C>, 'Debugging, code review, and problems with several steps.', `${usd(BETA.price.input)} in, ${usd(BETA.price.output)} out`],
        [<C key="m">max</C>, 'Your hardest work: security reviews, large refactors, anything you will act on without checking.', `${usd(BETA.price.input)} in, ${usd(BETA.price.output)} out`],
      ]}
    />
    <P>
      <strong>{PRO_BETA.name}</strong> (<C>{PRO_BETA.id}</C>) has two. It is the more thorough model, and it is priced
      higher per token.
    </P>
    <Table
      head={['Level', 'Use it for', 'Price per 1M tokens']}
      minWidth={640}
      rows={[
        [<><C>z-low</C> (default)</>, 'Demanding work.', `${usd(PRO_BETA.price.input)} in, ${usd(PRO_BETA.price.output)} out`],
        [<C key="zh">z-high</C>, 'The most thorough level, for work you will act on without checking.', `${usd(PRO_BETA.price.input)} in, ${usd(PRO_BETA.price.output)} out`],
      ]}
    />
    <Ul>
      <li>
        <strong>Every level thinks first.</strong> There is no way to turn thinking off. The first level of each model
        is the quickest; higher levels wait longer before the first word, and the output then streams quickly.
      </li>
      <li>
        <strong>Levels of one model cost the same per token.</strong> Higher levels think for longer, so a request
        takes more time and can use more tokens. {PRO_BETA.name} costs more per token than {BETA.name}, at every level.
        See <A href={docsHref('pricing')}>Pricing and billing</A>.
      </li>
      <li>The level applies to the whole request.</li>
    </Ul>

    <H2 id="set-the-level">Set the level</H2>
    <P>
      The setting has a different name in each format, but the same values. The examples below use {BETA.name} unless the
      tab says otherwise.
    </P>
    <CodeBlock
      tabs={[
        { label: 'Chat Completions', lang: 'bash', code: TH_CHAT },
        { label: 'Responses', lang: 'bash', code: TH_RESPONSES },
        { label: 'Messages', lang: 'bash', code: TH_MESSAGES },
        { label: 'Python SDK', lang: 'python', code: TH_PY },
        { label: 'Kael Pro Beta', lang: 'bash', code: TH_PRO },
      ]}
    />
    <P>
      Values are not case sensitive. With the OpenAI Python SDK or the Anthropic SDK, pass the field through{' '}
      <C>extra_body</C> so it works whatever the SDK&apos;s own type list says.
    </P>

    <H2 id="set-on-the-key">Set it on the key</H2>
    <P>
      If your tool cannot send the field at all, set the level on the key instead. On the{' '}
      <A href={docsHref('api-keys')}>API keys</A> page, every key has a Thinking level dropdown. <strong>SDK</strong>, the
      default, means the request decides, as described above. Choosing <strong>Low</strong>, <strong>High</strong> or{' '}
      <strong>Max</strong> makes every {BETA.name} request made with that key run at that level, whatever the request
      says. Choosing <strong>z-low</strong> or <strong>z-high</strong> does the same for {PRO_BETA.name}.
    </P>
    <P>
      A key holds one level, and a level belongs to one model, so it applies to that model only. A key set to{' '}
      <C>high</C> that calls <C>{PRO_BETA.id}</C> behaves as if it were on SDK for that call: the request decides, and
      with nothing set the default <C>{PRO_BETA.defaultLevel}</C> runs. You can choose the level when you create the key,
      and change it at any time. It applies from the key&apos;s next request.
    </P>

    <H2 id="not-available">What is not available</H2>
    <P>
      There is no <C>auto</C> level, so choose a level yourself. <C>medium</C> does not exist either. Any value the model
      you called does not offer returns a <C>400</C> that names the field, so a typo never runs at a level you did not
      choose. That includes the other model&apos;s levels: sending <C>z-low</C> to <C>{BETA.id}</C> is a{' '}
      <C>400</C> that tells you to use <C>{PRO_BETA.id}</C>. The one exception is a key with a level set on the
      dashboard for the model you call: that level is used and the request&apos;s value is not read.
    </P>
    <CodeBlock tabs={[{ label: '400 response', lang: 'json', code: TH_ERROR }]} />
    <P>
      The Messages format&apos;s own <C>thinking</C> field is accepted and ignored.
    </P>

    <H2 id="in-the-playground">In the Playground</H2>
    <P>
      The <A href={docsHref('playground')}>Playground</A> lets you choose the model for a new conversation and its
      thinking level, and remembers your choices in this browser. A conversation stays on the model it started with.
    </P>
  </>
);

/* ------------------------------------------------------------------ */
/* Streaming                                                           */
/* ------------------------------------------------------------------ */

const ST_PY = `stream = client.chat.completions.create(
    model="kael-beta",
    messages=[{"role": "user", "content": "Explain this stack trace: ..."}],
    stream=True,
    stream_options={"include_usage": True},
)

for chunk in stream:
    if not chunk.choices:  # the final usage chunk has no choices
        print("\\n", chunk.usage)
        continue

    delta = chunk.choices[0].delta
    title = getattr(delta, "reasoning_content", None)
    if title:
        print("[thinking]", title)
    if delta.content:  # empty strings are keep-alives
        print(delta.content, end="", flush=True)`;

const ST_SSE = `data: {"choices":[{"index":0,"delta":{"reasoning_content":"Reading the stack trace"}}]}

data: {"choices":[{"index":0,"delta":{"content":""}}]}

data: {"choices":[{"index":0,"delta":{"content":"The error comes from"}}]}

data: [DONE]`;

export const Streaming: React.FC = () => (
  <>
    <H2 id="turn-it-on">Turn it on</H2>
    <P>
      Set <C>stream</C> to <C>true</C> on any of the three formats. The response is then a stream of server-sent
      events, and the OpenAI and Anthropic SDKs handle it for you.
    </P>

    <H2 id="timing">What to expect from the stream</H2>
    <Ul>
      <li>
        <strong>The answer starts after Kael has finished working it out.</strong> The first answer token arrives
        later than with a single model call.
      </li>
      <li>
        <strong>Until then, with thinking on, you get thinking titles.</strong> These are short lines such as
        &quot;Reading the stack trace&quot;. Kael writes them for you. Raw reasoning is never sent, so do not parse the
        titles or depend on their wording.
      </li>
      <li>
        <strong>Keep-alives arrive about once a second</strong> while Kael is quiet. Ignore them (see below).
      </li>
    </Ul>

    <H2 id="by-format">By format</H2>
    <Table
      head={['', 'Chat Completions', 'Responses', 'Messages']}
      minWidth={760}
      rows={[
        [
          'Answer text',
          <C key="a">choices[0].delta.content</C>,
          'Content delta events',
          <>
            <C>text_delta</C> events
          </>,
        ],
        [
          'Thinking titles',
          <C key="b">choices[0].delta.reasoning_content</C>,
          <C key="c">response.reasoning_text.delta</C>,
          <>
            <C>thinking</C> blocks (<C>thinking_delta</C>)
          </>,
        ],
        [
          'Keep-alive',
          <>
            a chunk with <C>content: &quot;&quot;</C>
          </>,
          <C key="d">response.ping</C>,
          <>
            the standard <C>ping</C> event
          </>,
        ],
        [
          'End of stream',
          <>
            <C>data: [DONE]</C>
          </>,
          <>
            <C>response.completed</C> (or <C>response.incomplete</C>); no <C>[DONE]</C>
          </>,
          <>
            <C>message_stop</C>
          </>,
        ],
        [
          'Usage',
          <>
            final chunk, if you set <C>stream_options.include_usage</C>
          </>,
          <>
            in the <C>response.completed</C> event
          </>,
          <>
            in the final <C>message_delta</C> event
          </>,
        ],
      ]}
    />
    <P>
      On the Responses format, Kael sends content deltas and a final completed event, not every item lifecycle event.
      If your client expects each lifecycle event, treat the completed event as the source of truth.
    </P>

    <H2 id="example">Example</H2>
    <CodeBlock tabs={[{ label: 'Python', lang: 'python', code: ST_PY }]} />
    <P>A Chat Completions stream looks like this (shortened):</P>
    <CodeBlock tabs={[{ label: 'Server-sent events', lang: 'text', code: ST_SSE }]} />

    <H2 id="failures">Failures</H2>
    <Ul>
      <li>
        <strong>Errors before the stream starts</strong> use a normal HTTP status. See{' '}
        <A href={docsHref('errors')}>Errors</A>.
      </li>
      <li>
        <strong>Errors after the stream starts</strong> cannot change the status, which is already <C>200</C>. They
        arrive as a <C>data:</C> event holding an <C>error</C> object. Treat that as a failed request.
      </li>
      <li>
        If the connection drops, send the request again. A retry is a new request.
      </li>
      <li>
        Without streaming, the connection stays open until the answer is ready, which can take minutes on hard
        requests. Set client timeouts to {KAEL.clientTimeoutMinutes} minutes or more, or stream.
      </li>
    </Ul>
  </>
);

/* ------------------------------------------------------------------ */
/* Tool calling                                                        */
/* ------------------------------------------------------------------ */

const TOOLS_OPENAI = `tools = [{
    "type": "function",
    "function": {
        "name": "get_order_status",
        "description": "Look up an order by its id.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
}]

messages = [{"role": "user", "content": "Where is order A-1042?"}]
first = client.chat.completions.create(model="kael-beta", messages=messages, tools=tools)

call = first.choices[0].message.tool_calls[0]  # finish_reason is "tool_calls"
messages.append(first.choices[0].message)
messages.append({
    "role": "tool",
    "tool_call_id": call.id,
    "content": '{"status": "shipped", "arrives": "Friday"}',  # your function's result
})

final = client.chat.completions.create(model="kael-beta", messages=messages, tools=tools)
print(final.choices[0].message.content)`;

const TOOLS_ANTHROPIC = `tools = [{
    "name": "get_order_status",
    "description": "Look up an order by its id.",
    "input_schema": {
        "type": "object",
        "properties": {"order_id": {"type": "string"}},
        "required": ["order_id"],
    },
}]

messages = [{"role": "user", "content": "Where is order A-1042?"}]
first = client.messages.create(model="kael-beta", max_tokens=1024, messages=messages, tools=tools)

call = next(block for block in first.content if block.type == "tool_use")  # stop_reason is "tool_use"
messages.append({"role": "assistant", "content": first.content})
messages.append({
    "role": "user",
    "content": [{
        "type": "tool_result",
        "tool_use_id": call.id,
        "content": '{"status": "shipped", "arrives": "Friday"}',  # your function's result
    }],
})

final = client.messages.create(model="kael-beta", max_tokens=1024, messages=messages, tools=tools)
print(final.content[0].text)`;

export const Tools: React.FC = () => (
  <>
    <H2 id="the-loop">The loop</H2>
    <P>
      Tool calling works the way it does in the OpenAI and Anthropic APIs. You describe your functions in{' '}
      <C>tools</C>. When Kael wants one run, it replies with a tool call instead of text. You run the function and send
      the result back, and Kael continues.
    </P>
    <CodeBlock
      tabs={[
        { label: 'OpenAI SDK', lang: 'python', code: TOOLS_OPENAI },
        { label: 'Anthropic SDK', lang: 'python', code: TOOLS_ANTHROPIC },
      ]}
    />

    <H2 id="how-tool-calls-behave">How tool calls behave</H2>
    <Ul>
      <li>
        <strong>Tool calls are checked before you see them.</strong> Kael can change which tool is called, or its
        arguments, before the call is returned. This is one reason tool requests take longer.
      </li>
      <li>
        <strong>Kael decides when to call a tool.</strong> <C>tool_choice</C> is accepted but not enforced.
      </li>
      <li>
        <strong>Only your own function tools exist.</strong> Kael has no built-in web search, code execution, or file
        search through the API.
      </li>
      <li>
        <strong>Streaming:</strong> on Chat Completions, tool calls stream in pieces. On Responses and Messages the
        whole call arrives at once.
      </li>
      <li>
        <strong>Tool results are information, not commands.</strong> Kael treats instructions that appear inside a tool
        result as content to weigh, not orders to follow.
      </li>
    </Ul>
    <Callout title="Tool definitions count as input">
      <p>
        Your tool descriptions and schemas are part of the prompt, so they are billed as input tokens on every request.
        Keep them tight.
      </p>
    </Callout>
  </>
);

/* ------------------------------------------------------------------ */
/* Images                                                              */
/* ------------------------------------------------------------------ */

const IMG_CHAT = `{
  "model": "kael-beta",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "What does this stack trace say?"},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo..."}}
    ]
  }]
}`;

const IMG_RESPONSES = `{
  "model": "kael-beta",
  "input": [{
    "role": "user",
    "content": [
      {"type": "input_text", "text": "What does this stack trace say?"},
      {"type": "input_image", "image_url": "data:image/png;base64,iVBORw0KGgo..."}
    ]
  }]
}`;

const IMG_MESSAGES = `{
  "model": "kael-beta",
  "max_tokens": 1024,
  "messages": [{
    "role": "user",
    "content": [
      {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo..."}},
      {"type": "text", "text": "What does this stack trace say?"}
    ]
  }]
}`;

export const Images: React.FC = () => (
  <>
    <H2 id="send-an-image">Send an image</H2>
    <P>
      Put an image in a message next to your text, using the content format of the API you are calling. A base64 data
      URL is the most reliable way to send one.
    </P>
    <CodeBlock
      tabs={[
        { label: 'Chat Completions', lang: 'json', code: IMG_CHAT },
        { label: 'Responses', lang: 'json', code: IMG_RESPONSES },
        { label: 'Messages', lang: 'json', code: IMG_MESSAGES },
      ]}
    />

    <H2 id="what-to-know">What to know</H2>
    <Ul>
      <li>
        Images count as input tokens and are billed at the input price. There is no separate image price.
      </li>
      <li>Kael reads images. It does not create them: output is always text.</li>
      <li>
        An image in a form Kael does not recognize is dropped without an error. If an answer ignores your image, check
        the format of the content part.
      </li>
      <li>
        <strong>Not supported yet:</strong> PDFs, audio, video, and other file types. Convert a PDF page to an image, or
        extract its text, before sending it.
      </li>
      <li>Kael is built and tested for English, including text inside images.</li>
    </Ul>
  </>
);

/* ------------------------------------------------------------------ */
/* System prompts                                                      */
/* ------------------------------------------------------------------ */

export const SystemPrompts: React.FC = () => (
  <>
    <H2 id="where-it-goes">Where it goes</H2>
    <Table
      head={['Format', 'System prompt']}
      minWidth={520}
      rows={[
        ['Chat Completions', <>A message with the role <C key="a">system</C> or <C key="b">developer</C></>],
        ['Responses', <>The <C key="c">instructions</C> field, or a system or developer input item</>],
        ['Messages', <>The top-level <C key="d">system</C> field</>],
      ]}
    />

    <H2 id="how-kael-treats-it">How Kael treats it</H2>
    <Ul>
      <li>
        <strong>Your prompt defines the persona and the task.</strong> If it gives Kael a name or a character, Kael uses
        it, including when a user asks who it is.
      </li>
      <li>
        <strong>Without one, Kael calls itself Kael.</strong> That is a Quancis Composite Intelligence System.
      </li>
      <li>
        <strong>Kael&apos;s own rules rank above yours.</strong> A system prompt cannot make Kael claim to be a
        different AI product, and Kael will not name or guess the models it is built on, even if asked to.
      </li>
      <li>
        <strong>Instructions inside tool results, files, and quoted text</strong> are treated as information, not as
        commands. That protects an agent from instructions hidden in the content it reads.
      </li>
    </Ul>

    <H2 id="what-kael-adds">What Kael adds</H2>
    <P>
      Kael wraps your request with its own instructions: who it is, how to rank your instructions, and today&apos;s real
      date. You do not need to tell Kael the date. Those added instructions are not billed to you.
    </P>
    <P>
      Your own system prompt is billed as input like any other text, so keep it as short as it can be while still
      doing its job.
    </P>
  </>
);

/* ------------------------------------------------------------------ */
/* SDKs and frameworks                                                 */
/* ------------------------------------------------------------------ */

const SDK_OPENAI_PY = `from openai import OpenAI

client = OpenAI(
    base_url="https://api.quancis.space/v1",
    api_key="sk-quan-...",
)

reply = client.chat.completions.create(
    model="kael-beta",
    messages=[{"role": "user", "content": "Review this function."}],
)
print(reply.choices[0].message.content)`;

const SDK_OPENAI_TS = `import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'https://api.quancis.space/v1',
  apiKey: process.env.QUAN_API_KEY,
});

const reply = await client.chat.completions.create({
  model: 'kael-beta',
  messages: [{ role: 'user', content: 'Review this function.' }],
});
console.log(reply.choices[0].message.content);`;

const SDK_OPENAI_RESPONSES = `from openai import OpenAI

client = OpenAI(base_url="https://api.quancis.space/v1", api_key="sk-quan-...")

reply = client.responses.create(
    model="kael-beta",
    instructions="You are a careful code reviewer.",
    input="Review this function.",
)
print(reply.output_text)`;

const SDK_ANTHROPIC_PY = `import anthropic

client = anthropic.Anthropic(
    base_url="https://api.quancis.space",  # no /v1
    api_key="sk-quan-...",
)

message = client.messages.create(
    model="kael-beta",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Review this function."}],
)
print(message.content[0].text)`;

const SDK_ANTHROPIC_TS = `import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({
  baseURL: 'https://api.quancis.space', // no /v1
  apiKey: process.env.QUAN_API_KEY,
});

const message = await client.messages.create({
  model: 'kael-beta',
  max_tokens: 1024,
  messages: [{ role: 'user', content: 'Review this function.' }],
});
console.log(message.content);`;

const SDK_LANGCHAIN = `from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="kael-beta",
    base_url="https://api.quancis.space/v1",
    api_key="sk-quan-...",
)

print(llm.invoke("Review this function.").content)`;

const SDK_VERCEL = `import { createOpenAI } from '@ai-sdk/openai';
import { generateText } from 'ai';

const quancis = createOpenAI({
  baseURL: 'https://api.quancis.space/v1',
  apiKey: process.env.QUAN_API_KEY,
});

const { text } = await generateText({
  model: quancis.chat('kael-beta'),
  prompt: 'Review this function.',
});`;

export const Sdks: React.FC = () => (
  <>
    <H2 id="openai-sdks">OpenAI SDKs</H2>
    <P>
      Point the client at <C>{KAEL.openaiBase}</C> and use your Quancis key. Both the Chat Completions and Responses
      APIs work.
    </P>
    <CodeBlock
      tabs={[
        { label: 'Python', lang: 'python', code: SDK_OPENAI_PY },
        { label: 'TypeScript', lang: 'ts', code: SDK_OPENAI_TS },
        { label: 'Python (Responses)', lang: 'python', code: SDK_OPENAI_RESPONSES },
      ]}
    />

    <H2 id="anthropic-sdks">Anthropic SDKs</H2>
    <P>
      Use <C>{KAEL.anthropicBase}</C> <strong>without</strong> <C>/v1</C>. Anthropic SDKs add <C>/v1/messages</C>{' '}
      themselves, so a base URL that already ends in <C>/v1</C> would call <C>/v1/v1/messages</C> and fail.
    </P>
    <CodeBlock
      tabs={[
        { label: 'Python', lang: 'python', code: SDK_ANTHROPIC_PY },
        { label: 'TypeScript', lang: 'ts', code: SDK_ANTHROPIC_TS },
      ]}
    />

    <H2 id="frameworks">Frameworks</H2>
    <P>
      Any framework that lets you set an OpenAI-compatible base URL will work. These two are tested patterns:
    </P>
    <CodeBlock
      tabs={[
        { label: 'LangChain', lang: 'python', code: SDK_LANGCHAIN },
        { label: 'Vercel AI SDK', lang: 'ts', code: SDK_VERCEL },
      ]}
    />
    <Callout title="Use the Chat Completions helper in the Vercel AI SDK">
      <p>
        <C>quancis.chat(&apos;kael-beta&apos;)</C> calls Chat Completions. Calling <C>quancis(&apos;kael-beta&apos;)</C>{' '}
        may use the Responses API instead, depending on your version of the SDK. Both work, and the{' '}
        <A href={docsHref('endpoints')}>Endpoints</A> page covers each.
      </p>
    </Callout>

    <H2 id="environment-variables">Environment variables</H2>
    <P>Tools that read the standard variables need no code change:</P>
    <Table
      head={['Tools that use', 'Set']}
      minWidth={520}
      rows={[
        [
          'OpenAI SDKs and OpenAI-compatible tools',
          <>
            <C key="1">OPENAI_BASE_URL={KAEL.openaiBase}</C> and <C key="2">OPENAI_API_KEY=sk-quan-...</C>
          </>,
        ],
        [
          'Anthropic SDKs and Anthropic-compatible tools',
          <>
            <C key="3">ANTHROPIC_BASE_URL={KAEL.anthropicBase}</C> and <C key="4">ANTHROPIC_API_KEY=sk-quan-...</C>
          </>,
        ],
      ]}
    />

    <H2 id="client-settings">Client settings that matter</H2>
    <Ul>
      <li>
        Set request timeouts to {KAEL.clientTimeoutMinutes} minutes or more, or stream. Hard requests can run for many minutes.
      </li>
      <li>
        The SDKs retry some failures on their own. That is fine for <C>429</C> and <C>5xx</C>; see{' '}
        <A href={docsHref('errors')}>Errors</A> for what is safe to retry.
      </li>
    </Ul>
  </>
);
