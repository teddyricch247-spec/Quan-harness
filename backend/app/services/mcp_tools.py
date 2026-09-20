"""
§9.4/§14 — actually calling a merged-in MCP connector tool during the turn
loop. mcp_handshake.py does the one-time discovery (`tools/list`) at connect
time; this does the per-call `tools/call` against the same Streamable HTTP
transport, reusing its header-building and JSON/SSE response parsing rather
than duplicating them (`_headers`/`_parse_json_or_sse` — both already
transport-only helpers with no handshake-specific state, so importing them
here rather than copying is the same "one implementation, not two" reasoning
as text_edit.py's check_syntax being shared instead of forked per caller).
"""
from dataclasses import dataclass

import httpx

from app.services.mcp_handshake import MCP_PROTOCOL_VERSION, _headers, _parse_json_or_sse
from app.services.tool_schemas import MergedMcpTool

CALL_TIMEOUT_SECONDS = 60


@dataclass
class McpCallResult:
    ok: bool
    content: str = ""
    error: str | None = None


async def call_tool(tool: MergedMcpTool, arguments: dict, auth_token: str | None) -> McpCallResult:
    """No OAuth refresh-on-expiry handling — a 401 from an expired oauth
    access token surfaces as a plain failed result the model sees and reports,
    same as any other tool failure, rather than being retried after a silent
    refresh. mcp_oauth.py has no refresh-exchange function yet (see
    /docs/PHASE3_NOTES.md) — flagged there as a real gap, not hidden here."""
    headers = _headers(tool.auth_mode, auth_token)
    try:
        async with httpx.AsyncClient(timeout=CALL_TIMEOUT_SECONDS + 15.0) as client:
            # Streamable HTTP is stateless per the handshake's own comment
            # (no session id survives between mcp_handshake.py's discovery
            # call and this one, run in a different request potentially
            # minutes or hours later) — initialize fresh, then call.
            init_resp = await client.post(
                tool.url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "quan-harness", "version": "0.1.0"},
                    },
                },
            )
            init_resp.raise_for_status()
            init_body = _parse_json_or_sse(init_resp)
            if "error" in init_body:
                return McpCallResult(ok=False, error=str(init_body["error"]))

            session_id = init_resp.headers.get("mcp-session-id")
            call_headers = dict(headers)
            if session_id:
                call_headers["mcp-session-id"] = session_id

            call_resp = await client.post(
                tool.url,
                headers=call_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool.real_tool_name, "arguments": arguments},
                },
                timeout=CALL_TIMEOUT_SECONDS,
            )
            call_resp.raise_for_status()
            call_body = _parse_json_or_sse(call_resp)
            if "error" in call_body:
                return McpCallResult(ok=False, error=str(call_body["error"]))

            result = call_body.get("result", {})
            text = _extract_text(result.get("content", []))
            if result.get("isError"):
                return McpCallResult(ok=False, error=text or "The tool reported an error.")
            return McpCallResult(ok=True, content=text)
    except httpx.TimeoutException:
        return McpCallResult(ok=False, error="Connector call timed out.")
    except httpx.HTTPStatusError as exc:
        return McpCallResult(ok=False, error=f"HTTP {exc.response.status_code} from connector")
    except httpx.RequestError as exc:
        return McpCallResult(ok=False, error=f"Could not reach connector: {exc}")
    except Exception as exc:  # noqa: BLE001 — surfaced to the model as a normal tool failure, not raised
        return McpCallResult(ok=False, error=f"Unexpected error calling connector tool: {exc}")


def _extract_text(content_blocks: list[dict]) -> str:
    """MCP tool results are a list of content blocks (§ MCP spec: text/image/
    resource). Only text blocks are surfaced to the model today — an
    image/resource block from a connector tool has no path into a text-only
    message list yet (Phase 6's image-input work is the natural place to
    revisit this, not Phase 3 — see /docs/PHASE3_NOTES.md)."""
    parts = [b.get("text", "") for b in content_blocks if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(p for p in parts if p)
