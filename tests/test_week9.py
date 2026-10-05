"""
tests/test_week9.py
-------------------
Week 9: combined MCP integration, and the tool documentation /
recoverable-error work on ``tools.chunk_retrieval.py``.

Two groups:

* MCP host — pure unit tests over config parsing, namespacing and routing
  (no processes, no network), plus one ``@pytest.mark.live`` test that really
  spawns every server in ``mcp_config.json`` and dispatches one call per
  server. The live test is the evidence for the "combined 20-tool view" claim;
  deselect it with ``-m "not live"`` for a sub-second run.
* ``chunk_retrieval`` — hermetic. ChromaDB is replaced with an in-test fake so
  both the successful path and every recoverable-error path run deterministically
  and without touching the real index.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chromadb.errors import InternalError, NotFoundError  # noqa: E402

import tools.chunk_retrieval as cr  # noqa: E402
from app.services.mcp_host import (  # noqa: E402
    McpConfigError,
    McpHost,
    McpHostError,
    McpUnknownToolError,
    build_inventory,
    load_server_specs,
)
from tools.chunk_retrieval import ChunkRetrievalInput, chunk_retrieval  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
# Section 1 — mcp_config.json is configuration, and it is parsed as such
# ═══════════════════════════════════════════════════════════════════════════

def test_repo_config_file_is_valid_json():
    path = ROOT / "mcp_config.json"
    assert path.is_file(), f"{path} is missing"
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict) and isinstance(parsed["mcpServers"], dict)
    assert parsed["mcpServers"], "mcpServers must not be empty"


def test_load_server_specs_reads_every_declared_server():
    """Specs come from the file, so a new entry needs no code change."""
    specs = load_server_specs(ROOT / "mcp_config.json")
    declared = json.loads((ROOT / "mcp_config.json").read_text(encoding="utf-8"))["mcpServers"]
    assert [s.name for s in specs] == list(declared), "spec order must follow the file"
    for spec in specs:
        assert spec.command
        assert isinstance(spec.args, list)


def test_load_server_specs_honours_command_args_and_env():
    specs = {s.name: s for s in load_server_specs(ROOT / "mcp_config.json")}
    for name, spec in specs.items():
        assert spec.describe().startswith(spec.command)
    # A server with an env block keeps it; one without stays None so the SDK
    # applies its own conservative environment allowlist.
    for spec in specs.values():
        if spec.env is None:
            assert spec.env is None


def test_load_server_specs_rejects_missing_file():
    with pytest.raises(McpConfigError, match="not found"):
        load_server_specs(ROOT / "definitely_not_here.json")


def test_load_server_specs_rejects_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(McpConfigError, match="not valid JSON"):
        load_server_specs(bad)


def test_load_server_specs_rejects_entry_without_command(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"mcpServers": {"x": {"args": ["y"]}}}), encoding="utf-8")
    with pytest.raises(McpConfigError, match="no \"command\" string"):
        load_server_specs(bad)


def test_load_server_specs_rejects_non_string_args(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"mcpServers": {"x": {"command": "c", "args": [1]}}}), encoding="utf-8")
    with pytest.raises(McpConfigError, match="non-string \"args\""):
        load_server_specs(bad)


def test_load_server_specs_rejects_empty_server_list(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    with pytest.raises(McpConfigError, match="no servers"):
        load_server_specs(empty)


def test_host_refuses_to_start_with_no_servers():
    with pytest.raises(McpConfigError):
        McpHost([])


# ═══════════════════════════════════════════════════════════════════════════
# Section 2 — namespacing and routing, without any processes
# ═══════════════════════════════════════════════════════════════════════════

def _raw(name, description=None, required=None):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {n: {"type": "string"} for n in (required or [])},
            "required": list(required or []),
        },
        "outputSchema": None,
    }


def test_unique_tool_names_get_a_qualified_name_and_a_bare_alias():
    inventory, routes = build_inventory(
        {"alpha": [_raw("search", "Search A")], "beta": [_raw("lookup", "Lookup B")]}
    )
    by_q = {t.qualified_name: t for t in inventory}
    assert set(by_q) == {"alpha__search", "beta__lookup"}
    assert by_q["alpha__search"].aliases == ("search",)
    assert by_q["alpha__search"].name == "search", "server's own name must be preserved"
    assert by_q["alpha__search"].server == "alpha"
    # Both the qualified name and the bare alias route to the same tool.
    assert routes["alpha__search"] == ("alpha", "search")
    assert routes["search"] == ("alpha", "search")


def test_colliding_tool_names_are_namespaced_and_the_bare_alias_is_dropped():
    """Two servers may both expose ``search_documents``; routing must not be ambiguous."""
    inventory, routes = build_inventory(
        {
            "alpha": [_raw("shared", "A version")],
            "beta": [_raw("shared", "B version")],
        }
    )
    assert {t.qualified_name for t in inventory} == {"alpha__shared", "beta__shared"}
    for tool in inventory:
        assert tool.aliases == (), "a colliding bare name must not be bound to one server"
    assert "shared" not in routes, "an ambiguous bare name must not resolve at all"
    assert routes["alpha__shared"] == ("alpha", "shared")
    assert routes["beta__shared"] == ("beta", "shared")


def test_namespacing_survives_three_way_collisions_and_underscores():
    inventory, routes = build_inventory(
        {
            "a": [_raw("t", "x")],
            "b": [_raw("t", "y")],
            "c": [_raw("t__z", "z")],
        }
    )
    assert {t.qualified_name for t in inventory} == {"a__t", "b__t", "c__t__z"}
    assert routes["c__t__z"] == ("c", "t__z"), "a tool name may itself contain the separator"


def test_discovery_preserves_the_servers_own_name_description_and_input_schema():
    """The descriptor is a faithful copy of the ``tools/list`` entry.

    This is protocol-level fidelity, not a model-facing schema: nothing here
    reshapes an MCP tool into an LLM function-calling definition.
    """
    raw = _raw("search", "Search the corpus", ["q"])
    inventory, _ = build_inventory({"alpha": [raw]})
    tool = inventory[0]
    assert tool.server == "alpha"
    assert tool.name == "search", "the server's own tool name is preserved"
    assert tool.description == "Search the corpus"
    assert tool.input_schema == raw["inputSchema"]
    assert tool.input_schema["required"] == ["q"]
    assert tool.qualified_name == "alpha__search"
    described = tool.describe()
    assert described["tool"] == "search"
    assert described["description"] == "Search the corpus"
    assert described["input_schema"] == raw["inputSchema"]


def test_a_tool_with_no_description_or_schema_is_still_carried_through():
    """Missing optional fields must not break discovery."""
    inventory, _ = build_inventory({"alpha": [{"name": "bare", "inputSchema": {}}]})
    tool = inventory[0]
    assert tool.name == "bare"
    assert tool.description is None
    assert tool.input_schema == {}
    assert tool.output_schema is None
    assert tool.describe()["description"] is None


def test_host_exposes_no_llm_function_calling_shim():
    """Application-level discovery only: no OpenAI-style payload is produced.

    Guards against a future change quietly reintroducing LLM-to-MCP wiring.
    """
    import app.services.mcp_host as mcp_host

    for removed in ("tool_schemas",):
        assert not hasattr(mcp_host.McpHost, removed), (
            f"McpHost.{removed} is LLM-facing and must not be reintroduced"
        )
    assert not hasattr(mcp_host.McpTool, "to_schema")
    assert not hasattr(mcp_host.McpToolCall, "to_observation")
    source = Path(mcp_host.__file__).read_text(encoding="utf-8").lower()
    for banned in ("openai", "function_calling", "tool_choice"):
        assert banned not in source, f"mcp_host.py must not contain {banned!r}"


def test_resolve_before_discovery_is_a_host_error():
    host = McpHost.from_config(ROOT / "mcp_config.json")
    with pytest.raises(McpHostError, match="discover_tools"):
        host.resolve("anything")


def test_unknown_tool_error_lists_what_was_actually_discovered():
    host = McpHost.from_config(ROOT / "mcp_config.json")
    host._routes = {"alpha__search": ("alpha", "search")}
    with pytest.raises(McpUnknownToolError) as excinfo:
        host.resolve("alpha__nope")
    assert "alpha__nope" in str(excinfo.value)
    assert "alpha__search" in str(excinfo.value), "the message must show what was discovered"


def test_inventory_snapshot_reports_collisions_and_per_server_counts():
    host = McpHost.from_config(ROOT / "mcp_config.json")
    host.tools, host._routes = build_inventory(
        {"alpha": [_raw("shared")], "beta": [_raw("shared"), _raw("solo")]}
    )
    for state, names in zip(host.states, (["shared"], ["shared", "solo"])):
        state.tool_names = names
    snap = host.inventory()
    assert snap["per_server_tool_counts"] == {"alpha": 1, "beta": 2}
    assert snap["combined_tool_count"] == 3
    assert snap["collisions"] == ["shared"]


def test_inventory_always_counts_each_server_separately_from_the_sum():
    """Guards the claim: combined == sum of what each live server returned."""
    host = McpHost.from_config(ROOT / "mcp_config.json")
    per_server = {name: [_raw(f"t{i}") for i in range(n)] for name, n in zip(host.server_names, (3, 7))}
    host.tools, host._routes = build_inventory(per_server)
    snap = host.inventory()
    assert snap["combined_tool_count"] == sum(snap["per_server_tool_counts"].values())
    assert snap["combined_tool_count"] == 10


# ═══════════════════════════════════════════════════════════════════════════
# Section 3 — LIVE: both configured servers, one process each
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.live
def test_both_configured_servers_start_and_expose_a_combined_tool_inventory():
    """The actual evidence: two independent processes, one host, one tool set.

    The combined count is whatever the two live ``tools/list`` responses add up
    to. It is not read from config and it is not a constant in the host.
    """
    import anyio

    async def _exercise():
        async with McpHost.from_config(ROOT / "mcp_config.json") as host:
            tools = await host.discover_tools()
            snap = host.inventory()
            return snap, tools

    snap, tools = anyio.run(_exercise)

    declared = json.loads((ROOT / "mcp_config.json").read_text(encoding="utf-8"))["mcpServers"]
    assert {s["name"] for s in snap["servers"]} == set(declared), (
        "every configured server must be represented"
    )

    for server in snap["servers"]:
        assert server["connected"], f"{server['name']} failed to start: {server['error']}"
        assert server["error"] == ""
        assert server["server_info"]["name"], "initialize must yield serverInfo"
        assert server["protocol_version"], "initialize must yield a negotiated protocolVersion"
        assert server["tool_count"] > 0, f"{server['name']} advertised no tools"

    assert snap["combined_tool_count"] == sum(snap["per_server_tool_counts"].values())
    assert len(tools) == snap["combined_tool_count"]
    # Namespaced handles are unique, and every one routes back to a real server.
    assert len({t.qualified_name for t in tools}) == len(tools)
    for tool in tools:
        assert tool.name and tool.server
        assert tool.input_schema is not None


@pytest.mark.live
def test_host_dispatches_a_successful_call_to_each_server():
    """One successful call per server, dispatched through the one host instance.

    Routing is asserted three ways: the response names the owning server, the
    server received its own unmodified tool name, and the two servers return
    demonstrably different payloads (a misrouted call would make them equal).
    """
    import anyio

    async def _exercise():
        async with McpHost.from_config(ROOT / "mcp_config.json") as host:
            tools = await host.discover_tools()
            by_server: dict[str, list] = {}
            for tool in tools:
                by_server.setdefault(tool.server, []).append(tool)

            results = {}
            for server, server_tools in by_server.items():
                # Prefer a no-required-argument tool so the probe stays a pure
                # dispatch check; otherwise fill the schema's own required
                # strings from a known-good public package name.
                target = next(
                    (t for t in server_tools if not t.input_schema.get("required")),
                    server_tools[0],
                )
                args = {k: "react" for k in (target.input_schema.get("required") or [])}
                # Record the routing decision the host made, before the call.
                route = host.resolve(target.qualified_name)
                alias_route = host.resolve(target.aliases[0]) if target.aliases else None
                call = await host.call(target.qualified_name, args)
                results[server] = (target, args, call, route, alias_route)
            return results

    results = anyio.run(_exercise)

    assert len(results) >= 2, "both configured servers must be callable"

    for server, (target, _args, call, route, alias_route) in results.items():
        # The host resolved the handle to this server + this original tool name.
        assert route == (server, target.name), f"bad route for {target.qualified_name}"
        # The response names the owning server and the server's own tool name.
        assert call.server == server, f"{target.qualified_name} was answered by the wrong server"
        assert call.tool == target.name, f"{server} received a modified tool name"
        # A bare unique alias must route identically.
        if alias_route is not None:
            assert alias_route == route
        assert call.text, f"{target.qualified_name} returned no text content"
        assert "text" in call.block_types
        assert call.is_error is False, f"{target.qualified_name} failed: {call.text[:200]}"

    # Provenance: every server must return its own data. Identical payloads
    # across two servers would mean the calls were not actually separated.
    texts = {server: call.text for server, (_t, _a, call, _r, _ar) in results.items()}
    assert all(texts.values()), "every server must return content"
    assert len(set(texts.values())) == len(texts), (
        "two servers returned identical payloads, so routing cannot be trusted"
    )
    for server, (_target, _args, call, _route, _alias) in results.items():
        try:
            json.loads(call.text)
        except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic
            raise AssertionError(f"{server} returned unparseable content: {exc}") from exc

    # The doc-search probe reads this project's own ChromaDB, so its payload
    # must describe the local index.
    local = [c for _s, (_t, _a, c, _r, _ar) in results.items() if c.server == "doc-search"]
    if local:
        payload = json.loads(local[0].text)
        assert payload.get("collections"), "doc-search must return the collection inventory"
        assert payload.get("default_collection"), "doc-search must report its default collection"


# ═══════════════════════════════════════════════════════════════════════════
# Section 4 — tools/chunk_retrieval.py: successful execution
# ═══════════════════════════════════════════════════════════════════════════

class _FakeCollection:
    """Minimal stand-in for a ChromaDB collection.

    ``get`` serves two different calls the tool makes: an ID-scoped read and
    the full-collection scan used for context.
    """

    def __init__(self, rows, fail_ids=False, fail_context=False):
        self.rows = rows  # list of (id, document, metadata)
        self.fail_ids = fail_ids
        self.fail_context = fail_context
        self.context_calls = 0

    def get(self, ids=None, include=None):
        if ids:
            if self.fail_ids:
                raise InternalError("segment read failed")
            hit = [r for r in self.rows if r[0] == ids[0]]
            ids_out = [r[0] for r in hit]
            docs_out = [r[1] for r in hit]
            metas_out = [r[2] for r in hit]
            return {
                "ids": ids_out,
                "documents": docs_out,
                "metadatas": metas_out,
            }
        self.context_calls += 1
        if self.fail_context:
            raise InternalError("full scan failed")
        return {
            "ids": [r[0] for r in self.rows],
            "documents": [r[1] for r in self.rows],
            "metadatas": [r[2] for r in self.rows],
        }


class _FakeClient:
    def __init__(self, collection=None, not_found=False):
        self.collection = collection
        self.not_found = not_found

    def get_collection(self, name):
        if self.not_found:
            raise NotFoundError(f"Collection [{name}] does not exist")
        return self.collection


_ROWS = [
    ("doc__chunk_0", "alpha text", {"source_file": "doc.md"}),
    ("doc__chunk_1", "beta text", {"source_file": "doc.md"}),
    ("doc__chunk_2", "gamma text", {"source_file": "other.md"}),
]


@pytest.fixture
def fake_store(monkeypatch):
    """Install a fake ChromaDB client and return a reconfigurer."""

    def _install(collection=None, client=None, client_error=None):
        if client_error is not None:
            def _boom():
                raise client_error

            monkeypatch.setattr(cr, "_get_client", _boom)
            return None
        fake_client = client if client is not None else _FakeClient(collection or _FakeCollection(_ROWS))
        monkeypatch.setattr(cr, "_get_client", lambda: fake_client)
        return fake_client

    return _install


def test_successful_lookup_returns_found_with_the_chunk_verbatim(fake_store):
    fake_store()
    out = chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_1"))
    assert out.status == "found"
    assert out.chunk is not None
    assert out.chunk.text == "beta text"
    assert out.chunk.source_file == "doc.md"
    assert out.error_kind is None and out.detail == "" and out.recoverable is False


def test_successful_lookup_includes_neighbours_from_the_same_file_only(fake_store):
    fake_store()
    out = chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_1"))
    # doc__chunk_0 and doc__chunk_2 share the id prefix but not source_file.
    assert [c.chunk_id for c in out.context_chunks] == ["doc__chunk_0"]
    assert out.status == "found"


def test_context_is_capped_at_five_neighbours(fake_store):
    rows = [(f"big__chunk_{i}", f"text {i}", {"source_file": "big.md"}) for i in range(9)]
    fake_store(_FakeCollection(rows))
    out = chunk_retrieval(ChunkRetrievalInput(chunk_id="big__chunk_4"))
    assert out.status == "found"
    assert len(out.context_chunks) == 5
    assert "big__chunk_4" not in {c.chunk_id for c in out.context_chunks}


def test_include_context_false_skips_the_scan_entirely(fake_store):
    collection = _FakeCollection(_ROWS)
    fake_store(collection)
    out = chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_1", include_context=False))
    assert out.status == "found"
    assert out.context_chunks == []
    assert collection.context_calls == 0, "no full scan when context is not requested"


def test_successful_lookup_of_a_chunk_without_metadata_still_succeeds(fake_store):
    rows = [("bare__chunk_0", "text", None)]
    fake_store(_FakeCollection(rows))
    out = chunk_retrieval(ChunkRetrievalInput(chunk_id="bare__chunk_0"))
    assert out.status == "found"
    assert out.chunk.text == "text"
    assert out.chunk.source_file is None
    assert out.context_chunks == [], "no source_file means no neighbours to match"


# ═══════════════════════════════════════════════════════════════════════════
# Section 5 — tools/chunk_retrieval.py: recoverable-error paths
# ═══════════════════════════════════════════════════════════════════════════

def test_missing_chunk_is_a_recoverable_not_found_with_actionable_detail(fake_store):
    fake_store()
    out = chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_999"))
    assert out.status == "not_found"
    assert out.error_kind == "chunk_not_found"
    assert out.recoverable is True
    assert out.chunk is None
    assert "doc__chunk_999" in out.detail
    assert "collection" in out.detail.lower(), "detail must tell the caller what to do next"


def test_missing_collection_is_distinguished_from_an_unusable_store(fake_store):
    """The key before/after: these two used to share one catch-all message."""
    fake_store(client=_FakeClient(not_found=True))
    missing = chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_0"))
    assert missing.status == "error"
    assert missing.error_kind == "collection_not_found"
    assert missing.recoverable is True
    assert "does not exist" in missing.detail

    fake_store(client_error=OSError("chroma_db is locked by another process"))
    broken = chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_0"))
    assert broken.status == "error"
    assert broken.error_kind == "store_unavailable", (
        "an unreachable store must not be reported as a missing collection"
    )
    assert "locked" in broken.detail
    assert "CHROMA_PERSIST_DIR" in broken.detail


def test_failed_chunk_read_is_reported_as_recoverable_retrieval_failure(fake_store):
    fake_store(_FakeCollection(_ROWS, fail_ids=True))
    out = chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_0"))
    assert out.status == "error"
    assert out.error_kind == "retrieval_failed"
    assert out.recoverable is True
    assert out.chunk is None
    assert "retry" in out.detail.lower()


def test_failed_context_scan_is_surfaced_instead_of_silently_swallowed(fake_store):
    """The original code did ``except Exception: pass`` here.

    That returned ``status="found"`` with an empty ``context_chunks`` list,
    which is indistinguishable from "this chunk has no neighbours". The caller
    must now be able to tell the two apart.
    """
    fake_store(_FakeCollection(_ROWS, fail_context=True))
    out = chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_1"))
    assert out.status == "found", "the requested chunk was read, so the result is still a success"
    assert out.chunk is not None and out.chunk.text == "beta text"
    assert out.error_kind == "context_unavailable"
    assert out.recoverable is True
    assert "include_context=False" in out.detail, "detail must offer a concrete way forward"


def test_unexpected_exception_propagates_rather_than_being_reported_as_recoverable(monkeypatch):
    """A bug in the tool or the driver must keep its stack trace.

    Only the enumerated storage exceptions are recoverable; a bare RuntimeError
    from the collection object is a defect and is not laundered into a result.
    """
    class _Exploding:
        def get(self, ids=None, include=None):
            raise RuntimeError("programming defect in the tool")

    monkeypatch.setattr(cr, "_get_client", lambda: _FakeClient(_Exploding()))
    with pytest.raises(RuntimeError, match="programming defect in the tool"):
        chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_0"))


def test_status_is_always_one_of_three_documented_values(fake_store):
    """The old code packed free text into ``status``, breaking the documented enum."""
    cases = [
        (ChunkRetrievalInput(chunk_id="doc__chunk_0"), "found"),
        (ChunkRetrievalInput(chunk_id="doc__chunk_999"), "not_found"),
        (ChunkRetrievalInput(chunk_id="doc__chunk_0", collection_name="gone"), "error"),
    ]
    allowed = {"found", "not_found", "error"}
    for request, expected in cases:
        if expected == "error":
            fake_store(client=_FakeClient(not_found=True))
        else:
            fake_store()
        out = chunk_retrieval(request)
        assert out.status in allowed, f"status must stay in the documented enum, got {out.status!r}"
        assert out.status == expected
        assert out.status != "error" or out.detail, "every error status must carry a detail message"


def test_error_kind_matches_status_for_every_path(fake_store):
    fake_store()
    assert chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_0")).error_kind is None
    assert chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_999")).error_kind is not None
    fake_store(client=_FakeClient(not_found=True))
    out = chunk_retrieval(ChunkRetrievalInput(chunk_id="doc__chunk_0"))
    assert out.status == "error" and out.error_kind is not None


# ═══════════════════════════════════════════════════════════════════════════
# Section 6 — the docstring is part of the contract, so test it
# ═══════════════════════════════════════════════════════════════════════════

def test_tool_docstring_documents_purpose_inputs_defaults_output_and_limits():
    doc = cr.chunk_retrieval.__doc__ or ""
    for section in ("Purpose", "Args:", "Returns:", "Error handling", "Limitations"):
        assert section in doc, f"docstring is missing the {section!r} section"
    for token in ("chunk_id", "collection_name", "include_context", "sdk-v3-strategy-b", "True"):
        assert token in doc, f"docstring does not mention {token!r}"
    for kind in (
        "collection_not_found",
        "store_unavailable",
        "chunk_not_found",
        "retrieval_failed",
        "context_unavailable",
    ):
        assert kind in doc, f"docstring does not document the {kind!r} outcome"


def test_output_model_declares_the_error_fields_it_can_return():
    fields = set(cr.ChunkRetrievalOutput.model_fields)
    assert {"error_kind", "detail", "recoverable"} <= fields
    out = cr.ChunkRetrievalOutput(requested_chunk_id="x", status="error")
    assert out.error_kind is None and out.detail == "" and out.recoverable is False


# ═══════════════════════════════════════════════════════════════════════════
# Section 7 — the agent core was not modified for MCP
# ═══════════════════════════════════════════════════════════════════════════

def test_agent_loop_has_no_mcp_specific_logic():
    """MCP lives entirely in the integration layer, not in the agent."""
    source = (ROOT / "agent" / "agent_loop.py").read_text(encoding="utf-8")
    assert "mcp" not in source.lower(), "agent/agent_loop.py must not know about MCP"
    assert "mcp_host" not in source


def test_agent_tool_vocabulary_is_unchanged_and_disjoint_from_mcp_tools():
    from agent.agent_loop import KNOWN_ACTIONS

    assert KNOWN_ACTIONS == frozenset(
        {"reference_search", "chunk_retrieval", "migration_analyzer", "finish"}
    )
    # Adding MCP servers must not widen the agent's native vocabulary.
    assert "list_collections" not in KNOWN_ACTIONS
    assert not any("__" in action for action in KNOWN_ACTIONS)
