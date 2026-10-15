"""
§9.1: "On submit, before anything is written, the backend performs an MCP handshake
(a list-tools call) and shows the resulting tool list — names and descriptions —
before it's active anywhere."

This implements that handshake against the MCP "Streamable HTTP" transport: a plain
JSON-RPC 2.0 POST to the server's URL, `initialize` then `tools/list`. This covers
the common case (most current remote MCP servers speak Streamable HTTP). A server
that only speaks the older SSE-only transport, or that requires a session/OAuth
handshake beyond what auth_mode captures, will surface its real error in
last_handshake_error rather than silently appearing to work — see
/docs/PHASE1_NOTES.md for what to check if a specific server doesn't connect.
"""
from dataclasses import dataclass

import httpx

MCP_PROTOCOL_VERSION = "2025-06-18"


@dataclass
class HandshakeResult:
    ok: bool
    tools: list[dict]
    error: str | None


def _headers(auth_mode: str, auth_token: str | None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if auth_mode == "static_token" and auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    elif auth_mode == "oauth" and auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    return headers


async def handshake(url: str, auth_mode: str, auth_token: str | None) -> HandshakeResult:
    headers = _headers(auth_mode, auth_token)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            init_resp = await client.post(
                url,
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
                return HandshakeResult(ok=False, tools=[], error=str(init_body["error"]))

            # Some servers hand back a session id header on initialize that must be
            # echoed on subsequent calls.
            session_id = init_resp.headers.get("mcp-session-id")
            call_headers = dict(headers)
            if session_id:
                call_headers["mcp-session-id"] = session_id

            tools_resp = await client.post(
                url,
                headers=call_headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            tools_resp.raise_for_status()
            tools_body = _parse_json_or_sse(tools_resp)
            if "error" in tools_body:
                return HandshakeResult(ok=False, tools=[], error=str(tools_body["error"]))

            raw_tools = tools_body.get("result", {}).get("tools", [])
            tools = [
                {
                    "name": t.get("name"),
                    "description": t.get("description", ""),
                    # Phase 3 fix: the handshake previously discarded inputSchema —
                    # fine when nothing called a connector tool (Phase 2 had no
                    # turn loop), but §9.4's runtime tool-schema merge needs the
                    # real input schema to hand the model, not just name+description.
                    # Falls back to an empty open-object schema for a server that
                    # omits it, rather than failing the whole handshake over one
                    # malformed tool.
                    "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}},
                    # MCP's optional tool annotations (2025-03-26+): readOnlyHint is
                    # what §16.2 means by "explicitly marked side-effect-free at
                    # connection time" — captured here, at handshake time, exactly
                    # as that line describes, rather than guessed at call time.
                    # Missing/absent annotation defaults to False (mutating) — the
                    # conservative default when a server doesn't say either way.
                    "read_only": bool((t.get("annotations") or {}).get("readOnlyHint", False)),
                }
                for t in raw_tools
                if t.get("name")
            ]
            return HandshakeResult(ok=True, tools=tools, error=None)
    except httpx.HTTPStatusError as exc:
        return HandshakeResult(ok=False, tools=[], error=f"HTTP {exc.response.status_code} from server")
    except httpx.RequestError as exc:
        return HandshakeResult(ok=False, tools=[], error=f"Could not reach server: {exc}")
    except Exception as exc:  # noqa: BLE001 — surfaced to the user as last_handshake_error, not raised
        return HandshakeResult(ok=False, tools=[], error=f"Unexpected error during handshake: {exc}")


def _parse_json_or_sse(resp: httpx.Response) -> dict:
    """Streamable HTTP servers may respond with a single JSON object, or with an
    SSE-framed body containing one `data: {...}` event — handle both."""
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                import json

                return json.loads(line[len("data:"):].strip())
        return {"error": "No data event in SSE response"}
    return resp.json()
