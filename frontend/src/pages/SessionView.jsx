import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
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

// Rows in the messages table are the raw Responses-API items (see backend
// agent/loop.js). Group them back into one card per user turn for display: the
// user's text, the tool calls that turn made, and its final finish_task summary.
function groupIntoTurns(rows) {
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

export default function SessionView() {
  const { projectId, sessionId } = useParams();
  const [session, setSession] = useState(null);
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [live, setLive] = useState(null); // { thinking, content, actions } while a turn is streaming
  const bottomRef = useRef(null);

  useEffect(() => {
    api.getSession(sessionId).then(setSession).catch((err) => setError(err.message));
    refreshMessages();
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [rows, live]);

  function refreshMessages() {
    return api
      .listMessages(sessionId)
      .then(setRows)
      .catch((err) => setError(err.message));
  }

  const turns = useMemo(() => (rows ? groupIntoTurns(rows) : []), [rows]);

  async function handleEffortChange(value) {
    setSession((s) => ({ ...s, reasoning_effort: value }));
    try {
      await api.updateSession(sessionId, { reasoning_effort: value });
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

  return (
    <main className="page">
      <header className="page-header">
        <Link to={`/project/${projectId}`} className="back-link">
          ← Sessions
        </Link>
        <h1>{session?.title || '…'}</h1>
      </header>

      {error && <p className="error">{error}</p>}

      <div className="turns">
        {turns.map((turn) => (
          <div className="turn" key={turn.key}>
            <div className="bubble user">{turn.userText}</div>
            <ToolActionList actions={turn.actions} />
            {turn.summary ? (
              <div className="bubble assistant">
                <p>{turn.summary.summary}</p>
                {turn.summary.verifier_notes && <p className="muted small">Verifier: {turn.summary.verifier_notes}</p>}
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

      <Composer
        effort={session?.reasoning_effort || 'high'}
        onEffortChange={handleEffortChange}
        onSend={handleSend}
        busy={!!live}
      />
    </main>
  );
}
