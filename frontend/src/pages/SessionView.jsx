import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { api } from '../lib/api.js';
import { streamTurn } from '../lib/sseStream.js';
import Composer from '../components/Composer.jsx';
import ThinkingBlock from '../components/ThinkingBlock.jsx';
import ToolActionList from '../components/ToolActionList.jsx';

function safeParse(raw) {
  try {
    return JSON.parse(raw || '{}');
  } catch {
    return {};
  }
}

function extractMessageText(item) {
  if (!item?.content) return '';
  return item.content
    .filter((c) => c.type === 'output_text')
    .map((c) => c.text)
    .join('');
}

// Rows in the messages table are the raw Responses-API items (see backend
// agent/loop.js). Group them back into one card per user turn for display: the
// user's text, the tool calls that turn made, and its final finish_task summary.
function groupIntoBuildTurns(rows) {
  const turns = [];
  let current = null;
  for (const row of rows) {
    if (row.role === 'user') {
      current = { key: row.id, userText: row.content.text, actions: [], summary: null };
      turns.push(current);
    } else if (row.role === 'assistant' && row.content?.type === 'function_call' && current) {
      current.actions.push({ name: row.content.name, arguments: safeParse(row.content.arguments) });
    } else if (row.role === 'assistant' && row.content?.type === 'turn_summary' && current) {
      current.summary = row.content;
    }
  }
  return turns;
}

// Interview sessions are conversational — every assistant message is something the
// user actually needs to read and respond to, not just a final summary, so this keeps
// each block (text / tool action / handoff) in the order it happened rather than
// collapsing a turn down to one line.
function groupIntoInterviewTurns(rows) {
  const turns = [];
  let current = null;
  for (const row of rows) {
    if (row.role === 'user') {
      current = { key: row.id, userText: row.content.text, blocks: [] };
      turns.push(current);
    } else if (row.role === 'assistant' && row.content?.type === 'message' && current) {
      const text = extractMessageText(row.content);
      if (text) current.blocks.push({ kind: 'text', text });
    } else if (row.role === 'assistant' && row.content?.type === 'function_call' && current) {
      const action = { name: row.content.name, arguments: safeParse(row.content.arguments) };
      const last = current.blocks[current.blocks.length - 1];
      if (last && last.kind === 'actions') {
        last.actions.push(action);
      } else {
        current.blocks.push({ kind: 'actions', actions: [action] });
      }
    } else if (row.role === 'assistant' && row.content?.type === 'interview_handoff' && current) {
      current.blocks.push({ kind: 'handoff', title: row.content.title, sessionId: row.content.session_id });
    }
  }
  return turns;
}

export default function SessionView() {
  const { projectId, sessionId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  const [session, setSession] = useState(null);
  const [rows, setRows] = useState(null);
  const [providers, setProviders] = useState([]);
  const [error, setError] = useState(null);
  const [live, setLive] = useState(null); // { thinking, content, actions } while a turn is streaming
  const bottomRef = useRef(null);
  const autoSentRef = useRef(false);

  useEffect(() => {
    autoSentRef.current = false; // fresh session id — allow one auto-send again if applicable
    api.getSession(sessionId).then(setSession).catch((err) => setError(err.message));
    refreshMessages();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    api.getMeta().then((m) => setProviders(m.providers || [])).catch(() => {});
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [rows, live]);

  // If we just got handed off here from a prompt-maker session, send its generated
  // prompt as this session's first message automatically — once, and only if this
  // session is genuinely still empty. The nav state is cleared right away so a
  // refresh or back/forward navigation never re-triggers it.
  useEffect(() => {
    const prompt = location.state?.autoSendPrompt;
    if (!prompt || autoSentRef.current || rows === null || rows.length > 0) return;
    autoSentRef.current = true;
    navigate(location.pathname, { replace: true, state: {} });
    handleSend(prompt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, location.state, sessionId]);

  function refreshMessages() {
    return api
      .listMessages(sessionId)
      .then(setRows)
      .catch((err) => setError(err.message));
  }

  const isInterview = session?.kind === 'interview';
  const buildTurns = useMemo(() => (rows && !isInterview ? groupIntoBuildTurns(rows) : []), [rows, isInterview]);
  const interviewTurns = useMemo(() => (rows && isInterview ? groupIntoInterviewTurns(rows) : []), [rows, isInterview]);

  const currentProvider = providers.find((p) => p.id === session?.provider);
  const efforts = currentProvider?.reasoningEfforts || [];

  async function handleEffortChange(value) {
    try {
      const updated = await api.updateSession(sessionId, { reasoning_effort: value });
      setSession(updated);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleProviderChange(value) {
    try {
      const updated = await api.updateSession(sessionId, { provider: value });
      setSession(updated);
    } catch (err) {
      setError(err.message);
    }
  }

  function handleSend(text) {
    setError(null);
    setLive({ thinking: '', content: '', actions: [] });

    streamTurn(sessionId, { text, reasoning_effort: session?.reasoning_effort }, (type, data) => {
      switch (type) {
        case 'reasoning_delta':
          setLive((l) => (l ? { ...l, thinking: l.thinking + (data.delta || '') } : l));
          break;
        case 'content_delta':
          setLive((l) => (l ? { ...l, content: l.content + (data.delta || '') } : l));
          break;
        case 'tool_call':
          setLive((l) => (l ? { ...l, actions: [...l.actions, { name: data.name, arguments: data.arguments }] } : l));
          break;
        case 'handoff':
          setLive(null);
          refreshMessages().then(() => {
            navigate(`/project/${projectId}/session/${data.session_id}`, { state: { autoSendPrompt: data.prompt } });
          });
          break;
        case 'done':
        case 'error':
          if (type === 'error') setError(data.message);
          setLive(null);
          refreshMessages();
          break;
        default:
          break;
      }
    });
  }

  const locked = isInterview && !!session?.completed_at;
  const lastHandoff = locked
    ? interviewTurns.flatMap((t) => t.blocks).reverse().find((b) => b.kind === 'handoff')
    : null;

  return (
    <main className="page">
      <header className="page-header">
        <Link to={`/project/${projectId}`} className="back-link">
          ← Sessions
        </Link>
        <h1>{session?.title || '…'}</h1>
        {isInterview && <span className="badge">Prompt Maker</span>}
        {session?.kind === 'build' && session?.origin_session_id && (
          <Link className="muted small" to={`/project/${projectId}/session/${session.origin_session_id}`}>
            ← from prompt maker
          </Link>
        )}
      </header>

      {error && <p className="error">{error}</p>}

      <div className="turns">
        {isInterview
          ? interviewTurns.map((turn) => (
              <div className="turn" key={turn.key}>
                <div className="bubble user">{turn.userText}</div>
                {turn.blocks.map((block, i) => {
                  if (block.kind === 'text') {
                    return (
                      <div className="bubble assistant" key={i}>
                        {block.text}
                      </div>
                    );
                  }
                  if (block.kind === 'actions') {
                    return <ToolActionList key={i} actions={block.actions} />;
                  }
                  if (block.kind === 'handoff') {
                    return (
                      <div className="bubble assistant handoff" key={i}>
                        Prompt ready — opened build session{' '}
                        <Link to={`/project/${projectId}/session/${block.sessionId}`}>{block.title}</Link>.
                      </div>
                    );
                  }
                  return null;
                })}
              </div>
            ))
          : buildTurns.map((turn) => (
              <div className="turn" key={turn.key}>
                <div className="bubble user">{turn.userText}</div>
                <ToolActionList actions={turn.actions} />
                {turn.summary ? (
                  <div className="bubble assistant">
                    <p>{turn.summary.summary}</p>
                    {turn.summary.verifier_notes && <p className="muted small">Verifier: {turn.summary.verifier_notes}</p>}
                    {turn.summary.critique_notes?.map((c, i) => (
                      <p className="muted small" key={i}>
                        Critique{c.focus ? ` (${c.focus})` : ''}: {c.critique}
                      </p>
                    ))}
                    {turn.summary.deployment_status && (
                      <p className="muted small">Deploy: {turn.summary.deployment_status.state}</p>
                    )}
                  </div>
                ) : (
                  !live && <p className="muted small">(no summary recorded for this turn)</p>
                )}
              </div>
            ))}

        {live && (
          <div className="turn">
            <ThinkingBlock text={live.thinking} live />
            {live.content && <div className="bubble assistant">{live.content}</div>}
            <ToolActionList actions={live.actions} />
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {locked ? (
        <div className="composer-locked">
          <p className="muted small">
            This prompt-maker session is done
            {lastHandoff && (
              <>
                {' '}
                — its build session is{' '}
                <Link to={`/project/${projectId}/session/${lastHandoff.sessionId}`}>here</Link>
              </>
            )}
            .
          </p>
        </div>
      ) : (
        <Composer
          effort={session?.reasoning_effort}
          efforts={efforts}
          onEffortChange={handleEffortChange}
          provider={session?.provider}
          providers={providers}
          onProviderChange={handleProviderChange}
          onSend={handleSend}
          busy={!!live}
          placeholder={isInterview ? 'Answer, or add more detail…' : 'Describe what to change…'}
        />
      )}
    </main>
  );
}
