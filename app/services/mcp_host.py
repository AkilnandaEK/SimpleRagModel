"""
app/services/mcp_host.py
------------------------
Configuration-driven MCP host for the application.

Adding a server to ``mcp_config.json`` is **not** by itself integration. MCP has
no cross-server aggregation: every server is an independent OS process with its
own tool list, and a client must spawn, initialise, query and route to each one
separately. This module is that missing client-side half, and it is the only
place in the project that knows MCP servers exist.

Responsibilities, all driven by configuration — no server name, tool name or
tool count is hardcoded anywhere below:

1. Parse ``mcp_config.json`` into :class:`McpServerSpec` records.
2. Launch every configured server over stdio and run the ``initialize``
   handshake against each one independently.
3. Discover tools dynamically from each server's *actual* ``tools/list``
   response (following ``nextCursor`` pagination), then merge the per-server
   lists into one combined inventory.
4. Namespace tools so that two servers advertising the same bare name cannot
   collide, while keeping a route back to the original server + original tool.
5. Dispatch a call to the right server with the right original tool name and
   surface ``isError``/``content`` faithfully.

Scope: this is application-level tool discovery and dispatch. It gives the
application access to every configured server's tools; callers invoke them
explicitly by name via :meth:`McpHost.call`. It deliberately does **not** feed
tool schemas to an LLM, and it does not let a model choose or invoke tools.

The agent core (``agent/agent_loop.py``) and the LLM provider
(``app/services/llm_provider.py``) are untouched by this module. Adding,
removing or renaming a server is a configuration edit.

Environment note: the MCP SDK spawns servers with a conservative environment
allowlist (``APPDATA``, ``PATH``, ``USERPROFILE``, …) rather than the full parent
environment, so ``.env`` credentials are not handed to third-party servers. Any
variable a server genuinely needs must be declared in its ``env`` block.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

#: Separator between server name and tool name in a qualified tool name.
NAMESPACE_SEPARATOR = "__"

#: Repo root, used to resolve the default config path.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Environment variable that overrides the location of the MCP config file.
CONFIG_PATH_ENV = "MCP_CONFIG_PATH"

#: Default config file name, looked up at the repo root.
DEFAULT_CONFIG_NAME = "mcp_config.json"


# ── Errors ───────────────────────────────────────────────────────────────────

class McpHostError(RuntimeError):
    """Base class for host-level failures (config, spawn, handshake, routing)."""


class McpConfigError(McpHostError):
    """``mcp_config.json`` is missing, unreadable or structurally wrong."""


class McpUnknownToolError(McpHostError):
    """A call named a tool that discovery never returned."""

    def __init__(self, name: str, known: Sequence[str]) -> None:
        self.name = name
        self.known = list(known)
        preview = ", ".join(sorted(self.known)[:10]) or "<none discovered>"
        super().__init__(
            f"Unknown MCP tool {name!r}. Discovered tools: {preview}"
            + (" …" if len(self.known) > 10 else "")
        )


# ── Configuration ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class McpServerSpec:
    """One entry of the ``mcpServers`` object in ``mcp_config.json``."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None

    def to_stdio_parameters(self) -> StdioServerParameters:
        return StdioServerParameters(
            command=self.command,
            args=list(self.args),
            env=dict(self.env) if self.env is not None else None,
            cwd=self.cwd,
        )

    def describe(self) -> str:
        return " ".join([self.command, *self.args])


def default_config_path() -> Path:
    """Resolve the MCP config path: ``$MCP_CONFIG_PATH`` else ``<repo>/mcp_config.json``."""
    override = os.getenv(CONFIG_PATH_ENV)
    return Path(override) if override else REPO_ROOT / DEFAULT_CONFIG_NAME


def load_server_specs(config_path: str | Path | None = None) -> list[McpServerSpec]:
    """Read every server declared in the config file, in declaration order.

    Raises :class:`McpConfigError` for anything the host cannot act on, so a
    typo in configuration surfaces immediately instead of silently exposing
    fewer tools than the operator expects.
    """
    path = Path(config_path) if config_path is not None else default_config_path()
    if not path.is_file():
        raise McpConfigError(f"MCP config not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise McpConfigError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("mcpServers"), dict):
        raise McpConfigError(f'{path} must be an object with an "mcpServers" object')

    specs: list[McpServerSpec] = []
    for name, entry in raw["mcpServers"].items():
        if not isinstance(entry, dict):
            raise McpConfigError(f'{path}: server {name!r} must be an object')
        command = entry.get("command")
        if not command or not isinstance(command, str):
            raise McpConfigError(f'{path}: server {name!r} has no "command" string')
        args = entry.get("args") or []
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise McpConfigError(f'{path}: server {name!r} has a non-string "args" list')
        env = entry.get("env")
        if env is not None and (
            not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
        ):
            raise McpConfigError(f'{path}: server {name!r} has a non-string "env" mapping')
        cwd = entry.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise McpConfigError(f'{path}: server {name!r} has a non-string "cwd"')
        specs.append(McpServerSpec(name=name, command=command, args=list(args), env=env, cwd=cwd))

    if not specs:
        raise McpConfigError(f"{path} declares no servers")
    return specs


# ── Discovered tool inventory ────────────────────────────────────────────────

@dataclass(frozen=True)
class McpTool:
    """A tool exactly as one server advertised it, plus a namespaced handle."""

    server: str
    name: str
    description: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    qualified_name: str = ""
    aliases: tuple[str, ...] = ()

    @property
    def call_name(self) -> str:
        """Name to send in ``tools/call`` — the server's own name, unmodified."""
        return self.name

    def describe(self) -> dict[str, Any]:
        """The tool as its server advertised it, for logs and evidence files.

        This is a faithful copy of the MCP ``tools/list`` entry under the
        namespaced handle. It is not a model-facing payload: nothing in this
        project converts MCP tools into LLM function-calling schemas.
        """
        return {
            "server": self.server,
            "tool": self.name,
            "qualified_name": self.qualified_name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True)
class McpToolCall:
    """Normalised ``tools/call`` result, faithful to the server's own signalling."""

    server: str
    tool: str
    is_error: bool
    text: str
    structured: dict[str, Any] | None = None
    block_types: tuple[str, ...] = ()


@dataclass
class McpServerState:
    """Per-server negotiation outcome, kept for evidence and error messages."""

    spec: McpServerSpec
    session: ClientSession | None = None
    server_info: dict[str, Any] = field(default_factory=dict)
    protocol_version: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)
    tool_names: list[str] = field(default_factory=list)
    error: str = ""


def _join(server: str, tool: str) -> str:
    return f"{server}{NAMESPACE_SEPARATOR}{tool}"


def build_inventory(
    per_server: dict[str, list[dict[str, Any]]],
) -> tuple[list[McpTool], dict[str, tuple[str, str]]]:
    """Merge per-server tool lists into one host inventory.

    Namespacing policy, chosen so routing is always unambiguous:

    * Every tool gets a canonical qualified name ``<server>__<tool>``. This is
      what the host advertises, so two servers can never collide in a lookup.
    * A bare ``<tool>`` alias is added **only** when that name is unique across
      every server in this host. On collision the bare name is dropped entirely
      rather than bound to an arbitrary winner.

    Returns the inventory and the routing table ``call name -> (server, tool)``.
    """
    by_bare_name: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for server, tools in per_server.items():
        for raw in tools:
            by_bare_name.setdefault(raw["name"], []).append((server, raw))

    inventory: list[McpTool] = []
    routes: dict[str, tuple[str, str]] = {}
    for server, tools in per_server.items():
        for raw in tools:
            bare = raw["name"]
            qualified = _join(server, bare)
            owners = by_bare_name[bare]
            aliases = (bare,) if len(owners) == 1 and bare != qualified else ()
            inventory.append(
                McpTool(
                    server=server,
                    name=bare,
                    description=raw.get("description"),
                    input_schema=raw.get("inputSchema") or {},
                    output_schema=raw.get("outputSchema"),
                    qualified_name=qualified,
                    aliases=aliases,
                )
            )
            routes[qualified] = (server, bare)
            for alias in aliases:
                routes[alias] = (server, bare)
    return inventory, routes


# ── The host ─────────────────────────────────────────────────────────────────

class McpHost:
    """Spawns every configured MCP server and exposes their tools as one set.

    Usage::

        async with McpHost.from_config() as host:
            tools = await host.discover_tools()
            result = await host.call("doc-search__list_collections", {})

    or, from synchronous code, :func:`run_host`.
    """

    def __init__(self, specs: Sequence[McpServerSpec]) -> None:
        if not specs:
            raise McpConfigError("McpHost requires at least one server spec")
        self._specs = list(specs)
        self._stack: AsyncExitStack | None = None
        self._sessions: dict[str, ClientSession] = {}
        self.states: list[McpServerState] = [McpServerState(spec=s) for s in self._specs]
        self.tools: list[McpTool] = []
        self._routes: dict[str, tuple[str, str]] = {}

    # -- construction -------------------------------------------------------

    @classmethod
    def from_config(cls, config_path: str | Path | None = None) -> "McpHost":
        return cls(load_server_specs(config_path))

    @property
    def server_names(self) -> list[str]:
        return [s.name for s in self._specs]

    # -- lifecycle ----------------------------------------------------------

    async def __aenter__(self) -> "McpHost":
        await self.start()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.stop()

    async def start(self) -> None:
        """Spawn every server and complete the ``initialize`` handshake.

        One server failing does not abort the others: its failure is recorded on
        its :class:`McpServerState` so a single broken entry in the config
        cannot silently hide the tools of every healthy server.
        """
        if self._stack is not None:
            raise McpHostError("McpHost is already started")
        self._stack = AsyncExitStack()
        for state in self.states:
            # Each server is spawned inside its own try, and its context managers
            # are entered on the shared stack, so one failing spawn cannot
            # unwind an already-healthy server.
            try:
                read_stream, write_stream = await self._stack.enter_async_context(
                    stdio_client(state.spec.to_stdio_parameters())
                )
                session = await self._stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                init = await session.initialize()
                self._sessions[state.spec.name] = session
                state.protocol_version = init.protocolVersion
                state.server_info = init.serverInfo.model_dump()
                state.capabilities = init.capabilities.model_dump(exclude_none=True)
            except Exception as exc:  # noqa: BLE001 - recorded per server, not raised
                state.error = f"{type(exc).__name__}: {exc}"

    async def stop(self) -> None:
        stack, self._stack = self._stack, None
        self._sessions.clear()
        if stack is not None:
            await stack.aclose()

    # -- discovery ----------------------------------------------------------

    async def discover_tools(self, refresh: bool = False) -> list[McpTool]:
        """Ask every connected server for its real ``tools/list``.

        Tool counts and names come from the servers, never from configuration
        and never from a constant in this file.
        """
        if self._stack is None:
            raise McpHostError("McpHost.start() must be awaited before discovery")

        per_server: dict[str, list[dict[str, Any]]] = {}
        for state in self.states:
            session = self._sessions.get(state.spec.name)
            if session is None:
                state.tool_names = []
                continue
            collected: list[dict[str, Any]] = []
            cursor: str | None = None
            try:
                while True:
                    page = await session.list_tools(cursor=cursor) if cursor else await session.list_tools()
                    for tool in page.tools:
                        collected.append(
                            {
                                "name": tool.name,
                                "description": tool.description,
                                "inputSchema": tool.inputSchema,
                                "outputSchema": tool.outputSchema,
                            }
                        )
                    cursor = getattr(page, "nextCursor", None)
                    if not cursor:
                        break
            except Exception as exc:  # noqa: BLE001 - one bad server is recorded
                state.error = f"tools/list failed: {type(exc).__name__}: {exc}"
            state.tool_names = [t["name"] for t in collected]
            per_server[state.spec.name] = collected

        self.tools, self._routes = build_inventory(per_server)
        return self.tools

    # -- routing / dispatch -------------------------------------------------

    def resolve(self, call_name: str) -> tuple[str, str]:
        """Map a host-level tool name back to ``(server, original tool name)``."""
        if not self._routes:
            raise McpHostError("discover_tools() must run before resolving tool names")
        try:
            return self._routes[call_name]
        except KeyError as exc:
            raise McpUnknownToolError(call_name, list(self._routes)) from exc

    async def call(self, call_name: str, arguments: dict[str, Any] | None = None) -> McpToolCall:
        """Dispatch a call to the owning server under the server's own tool name."""
        server_name, tool_name = self.resolve(call_name)
        session = self._sessions.get(server_name)
        if session is None:
            state = next(s for s in self.states if s.spec.name == server_name)
            raise McpHostError(
                f"MCP server {server_name!r} is not connected"
                + (f" ({state.error})" if state.error else "")
            )
        result = await session.call_tool(tool_name, arguments or {})
        blocks = tuple(getattr(b, "type", "unknown") for b in result.content)
        text = "\n".join(
            getattr(b, "text", "") for b in result.content if getattr(b, "type", "") == "text"
        )
        return McpToolCall(
            server=server_name,
            tool=tool_name,
            is_error=bool(result.isError),
            text=text,
            structured=getattr(result, "structuredContent", None),
            block_types=blocks,
        )

    # -- reporting ----------------------------------------------------------

    def inventory(self) -> dict[str, Any]:
        """Machine-readable snapshot of what the host actually discovered."""
        by_server: dict[str, int] = {}
        for tool in self.tools:
            by_server[tool.server] = by_server.get(tool.server, 0) + 1
        return {
            "servers": [
                {
                    "name": s.spec.name,
                    "command": s.spec.describe(),
                    "connected": s.spec.name in self._sessions,
                    "server_info": s.server_info,
                    "protocol_version": s.protocol_version,
                    "tools": s.tool_names,
                    "tool_count": len(s.tool_names),
                    "error": s.error,
                }
                for s in self.states
            ],
            "per_server_tool_counts": by_server,
            "combined_tool_count": len(self.tools),
            "tool_names": [t.qualified_name for t in self.tools],
            "aliases": {t.qualified_name: list(t.aliases) for t in self.tools if t.aliases},
            "collisions": sorted(
                n for n, tools in _bare_names(self.tools).items() if len(tools) > 1
            ),
        }


def _bare_names(tools: Iterable[McpTool]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for t in tools:
        out.setdefault(t.name, []).append(t.server)
    return out


# ── Synchronous bridge ───────────────────────────────────────────────────────

def run_host(
    operation: Callable[[McpHost], Any],
    config_path: str | Path | None = None,
) -> Any:
    """Run one async host operation from synchronous code.

    ``operation`` receives a started, discovered :class:`McpHost` and may be a
    coroutine function (awaited) or a plain function.
    """
    import anyio

    async def _main() -> Any:
        async with McpHost.from_config(config_path) as host:
            await host.discover_tools()
            outcome = operation(host)
            if hasattr(outcome, "__await__"):
                outcome = await outcome
            return outcome

    return anyio.run(_main)


__all__ = [
    "NAMESPACE_SEPARATOR",
    "McpConfigError",
    "McpHost",
    "McpHostError",
    "McpServerSpec",
    "McpServerState",
    "McpTool",
    "McpToolCall",
    "McpUnknownToolError",
    "build_inventory",
    "default_config_path",
    "load_server_specs",
    "run_host",
]
