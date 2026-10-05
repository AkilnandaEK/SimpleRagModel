# Week 9 — Application-Level MCP Tool Discovery and Dispatch

**Run of record:** both MCP servers live on this host · `mcp_config.json` · Python 3.14 · Node v24.19.0 · `mcp` 1.30.0 · `chromadb` 1.5.9
**Machine-readable evidence:** [`mcp_integration_report.json`](mcp_integration_report.json) (written by the verification script, not hand-edited)
**Companion deliverables:** [`error_before_after.md`](error_before_after.md) · [`risk_note.md`](risk_note.md)

Reproduce:

```bash
# 1. Both servers start, discovery + one successful call per server
.venv\Scripts\python.exe scripts\verify_mcp_integration.py --tool package-registry:get-npm-package-details

# 2. Tests — hermetic group, then the live integration group, then everything
.venv\Scripts\python.exe -m pytest tests\test_week9.py -m "not live" -q
.venv\Scripts\python.exe -m pytest tests\test_week9.py -m "live" -q
.venv\Scripts\python.exe -m pytest tests\ -q
```

> **Cost warning.** The live group spawns two OS processes and `npx -y` downloads the npm package. First run also loads the `all-MiniLM-L6-v2` embedding model in the `doc-search` child. Budget ~90 s per live run. Use `-m "not live"` for a fast suite.

---

## What is and is not claimed

**Proven.** The agent application can load **both** configured MCP servers in a single host instance, discover each server's tools over the MCP protocol without hardcoding, and dispatch a call to either server with correct routing and faithful results. This is application-level MCP tool discovery and dispatch.

**Not claimed, not implemented.** The LLM does **not** receive these tool schemas. No model chooses, selects or invokes an MCP tool. `app/services/llm_provider.py` and `agent/agent_loop.py` are byte-identical to `HEAD`, and no MCP type crosses into either. MCP tools are invoked explicitly, by name, through `McpHost.call(name, arguments)`. Autonomous LLM tool calling was deliberately removed — see §9.

---

## The headline

| Claim | Result | Where proven |
|---|---|---|
| Application loads **both** configured MCP servers in one host instance | 2/2 connected, 0 errors | §1, §2 |
| Agent core (`agent/agent_loop.py`) modified | **No** — byte-identical to `HEAD` | §6 |
| LLM provider (`app/services/llm_provider.py`) modified | **No** — byte-identical to `HEAD` | §6 |
| Tool names/counts hardcoded in the implementation | **No** — all read from live `tools/list` | §3 |
| Combined inventory holds every discovered tool | 20 = 4 + 16, asserted against the merged list | §4 |
| Successful call per server, correct routing | `doc-search__list_collections`, `package-registry__get-npm-package-details` | §5 |
| Tests | **134 passed** (97 pre-existing + 37 new), 0 failed | §7 |

---

## 1. What was missing

The first thing checked was whether the application already loaded both servers. It did not, and the gap was larger than "the config was not read":

Before this task a repo-wide scan found **no MCP client code at all** — no `stdio_client`, `ClientSession`, `StdioServerParameters`, `list_tools`, `call_tool` or `mcp.client` import anywhere in `app/`, `agent/`, `tools/`, `scripts/` or `tests/`. `mcp==1.30.0` was installed and pinned in `requirements.txt` but never imported. `mcp_config.json` declared two servers that nothing ever read.

That is why [`wire.json`](../wire.json) records 20 tools while stating under `tool_counts.critical_distinction` that the figure is "an arithmetic sum across two independent OS processes" and that "no single captured MCP session ever exposed a combined 20-tool list". That was accurate about the wire capture. `app/services/mcp_host.py` adds the missing application-level layer, and §4 records what it now actually discovers.

**What was added** — `app/services/mcp_host.py`, the client-side half MCP requires, and the only module in the project that knows MCP exists:

1. parses `mcp_config.json` into `McpServerSpec` records;
2. spawns every configured server over stdio and runs `initialize` against each one independently;
3. asks each server for its **actual** `tools/list` (following `nextCursor` pagination) and merges the per-server lists into one inventory;
4. namespaces tools so two servers advertising the same name cannot collide, keeping a route back to the original server and original tool name;
5. dispatches a call to the owning server and surfaces `isError`/`content` faithfully.

**Failure isolation is deliberate.** A server that cannot spawn or handshake has the failure recorded on its own `McpServerState`; the remaining servers still load. One broken entry in the config must not silently hide the tools of every healthy server.

---

## 2. Both servers initialise in one host instance

```
=== Week 9 combined MCP integration ===
  doc-search           ok      2025-11-25   error=-
  package-registry     ok      2025-06-18   error=-
  per-server counts : {'doc-search': 4, 'package-registry': 16}
  combined (host)   : 20
  call doc-search__list_collections                     ok routed=True
  call package-registry__get-npm-package-details        ok routed=True
  report -> E:\week3\eval\mcp_integration_report.json
```

| Server | Command | Connected | Protocol | `serverInfo` | Tools | Error |
|---|---|---|---|---|---|---|
| `doc-search` | `E:\week3\.venv\Scripts\python.exe E:\week3\mcp servers\doc_search_server.py` | yes | `2025-11-25` | `{"name": "doc-search", "version": "1.30.0"}` | 4 | none |
| `package-registry` | `npx -y package-registry-mcp` | yes | `2025-06-18` | `{"name": "package-registry", "version": "1.0.0"}` | 16 | none |

Two independent OS processes, one `McpHost` instance, two live `ClientSession` objects. They disagree on protocol version (`2025-11-25` vs `2025-06-18`) and on the `tools.listChanged` capability (`false` vs `true`); the host tolerates both. `doc-search` reports version `1.30.0` because `FastMCP("doc-search")` passes no explicit version — that is the SDK version, not the tool's.

---

## 3. Tools are discovered dynamically over the protocol

No server name, tool name or tool count appears as a literal in `app/services/mcp_host.py` or `scripts/verify_mcp_integration.py`. The only tool-name-adjacent constants are `ZERO_ARG_PREFERENCE` — a *preference ordering* for which discovered tool to probe — and `DEFAULT_PROBE_VALUE`, a string used to fill a required string parameter.

Discovery walks every page until `nextCursor` is empty, and copies each tool's own `name`, `description`, `inputSchema` and `outputSchema` verbatim:

```python
while True:
    page = await session.list_tools(cursor=cursor) if cursor else await session.list_tools()
    for tool in page.tools:
        collected.append({"name": tool.name, "description": tool.description,
                          "inputSchema": tool.inputSchema, "outputSchema": tool.outputSchema})
    cursor = getattr(page, "nextCursor", None)
    if not cursor:
        break
```

Probe arguments are derived from each tool's own `inputSchema.required`, so the verification script works unchanged for a server added later. `McpTool` is a faithful record of the `tools/list` entry plus a namespaced handle; `McpTool.describe()` exposes exactly that record for logs and evidence files. Nothing reshapes a tool into a model-facing payload.

Two tests pin this: `test_load_server_specs_reads_every_declared_server` compares parsed specs against the raw JSON, and `test_discovery_preserves_the_servers_own_name_description_and_input_schema` asserts the descriptor is byte-equal to what the server advertised.

---

## 4. The combined inventory

### 4.1 Count — discovery, not addition

| Source | Value |
|---|---|
| `doc-search` live `tools/list` | 4 |
| `package-registry` live `tools/list` | 16 |
| **Combined, held by the host** | **20** |

The host keeps one merged list, and the figure is a *result* of merging two live responses. `tests/test_week9.py` asserts both `combined_tool_count == sum(per_server_tool_counts.values())` **and** `len(tools) == combined_tool_count`, so the two can only agree if the merged list genuinely holds every tool both servers returned. `test_inventory_always_counts_each_server_separately_from_the_sum` does the same against a synthetic 3 + 7 pair (combined 10). The report records the two figures side by side so a reviewer can see they were checked against each other:

```json
"tool_counts": {
  "per_server": { "doc-search": 4, "package-registry": 16 },
  "combined_discovered": 20,
  "arithmetic_sum": 20,
  "combined_equals_arithmetic": true,
  "basis": "host merged N live tools/list responses; not a hardcoded constant"
}
```

### 4.2 Names — all 20, as held by the host

`doc-search` (4):

```
doc-search__list_collections      doc-search__list_documents
doc-search__search_documents      doc-search__get_chunk
```

`package-registry` (16):

```
package-registry__get-cargo-package-details        package-registry__search-cargo-packages
package-registry__list-cargo-package-versions      package-registry__get-github-advisory
package-registry__search-github-advisories         package-registry__get-package-advisories
package-registry__get-golang-package-details       package-registry__list-golang-package-versions
package-registry__get-npm-package-details          package-registry__search-npm-packages
package-registry__list-npm-package-versions        package-registry__get-nuget-package-details
package-registry__search-nuget-packages            package-registry__list-nuget-package-versions
package-registry__get-pypi-package-details         package-registry__list-pypi-package-versions
```

### 4.3 Namespacing and collision routing

MCP has no cross-server namespace, so two servers may legitimately both expose `search_documents`. The integration layer resolves this:

* every tool gets a canonical qualified name `<server>__<tool>`, so two servers can never collide in a lookup;
* a bare `<tool>` alias is added **only** when that name is unique across the whole host;
* on collision the bare name is dropped entirely rather than bound to an arbitrary winner.

Routing is a `call name -> (server, original tool name)` table, and dispatch always sends the server **its own unmodified tool name** — `McpTool.call_name` returns `self.name`, never the qualified form. Verified live: the bare alias `list_collections` resolves to `("doc-search", "list_collections")`, the same route as the qualified handle.

These two servers do not currently collide (`collisions: []` in the report), so the collision path is proven by four unit tests instead: two-way collision, three-way collision, a tool whose own name contains the separator (`c__t__z` → `("c", "t__z")`), and an inventory snapshot reporting the collision list.

### 4.4 Tool metadata is preserved verbatim

`McpTool` keeps the server's own `name`, `description`, `inputSchema` and `outputSchema` unchanged. From the report:

```
doc-search__list_collections
  description  : "List every ChromaDB collection available to search, with chunk counts."
  input_schema : {"properties": {}, "title": "list_collectionsArguments", "type": "object"}

doc-search__list_documents
  description  : "List the source documents indexed in a collection, with per-file chunk counts."
  input_schema : {"properties": {"collection_name": {"default": "sdk-v3-strategy-b",
                   "title": "Collection Name", "type": "string"}},
                  "title": "list_documentsArguments", "type": "object"}
```

The `default: "sdk-v3-strategy-b"` is carried through from `mcp_config.json`'s `DOC_SEARCH_COLLECTION`. The JSON-Schema `title` keys are the server's own and are passed through rather than rewritten, because rewriting them would misrepresent what the server declared.

---

## 5. Dispatch — one successful call per server

Both calls went through the single host instance, i.e. one `McpHost` holding two live sessions.

### 5.1 `doc-search__list_collections` — local, no network

```
host_route        : {"server": "doc-search", "tool": "list_collections"}
routed_correctly  : True        is_error: False
content_block_types: ["text"]   result_length: 458   elapsed_s: 0.24
→ {"collections":[{"name":"recipe_rag_test_corpus","count":33}, …,
                  {"name":"sdk-v3-strategy-b","count":66}, …],
   "default_collection": "sdk-v3-strategy-b"}
```

Real local ChromaDB inventory, including the `sdk-v3-strategy-b` collection this project indexes.

### 5.2 `package-registry__get-npm-package-details` — third-party, live HTTP

```
host_route        : {"server": "package-registry", "tool": "get-npm-package-details"}
routed_correctly  : True        is_error: False
required_params   : ["name"]    arguments: {"name": "react"}   (from the tool's own inputSchema)
content_block_types: ["text"]   result_length: 2831   elapsed_s: 0.47
→ {"package":{"name":"react",
              "description":"React is a JavaScript library for building user interfaces.",
              "latestVersion":"19.3.0","license":"MIT",
              "homepage":"https://react.dev/", …}}
```

The 2 831-byte result matches the byte length of the `get-npm-package-details {"name":"react"}` capture in `wire.json` — two independent sessions agree.

### 5.3 How correct routing is established

Three independent checks, so a single mis-routed call cannot pass:

1. **Host route** — `host.resolve(handle)` returned `("doc-search", "list_collections")` and `("package-registry", "get-npm-package-details")` before the call was made.
2. **Response attribution** — each result names the owning server and the server's own unmodified tool name.
3. **Payload distinctness** — `payloads_distinct: true`. The two servers returned different content (`True` in the report, and asserted in the live test). Had the host cross-wired the calls, both payloads would be identical and the `routed_correctly` flags would prove nothing.

### 5.4 Error propagation is faithful

An early probe with `{}` on `get-cargo-package-details` returned `is_error=True` carrying the server's own `-32602 Input validation error`, surfaced rather than swallowed. But the same server returned `is_error=False` with the body `Error fetching package details: The request failed with status 403: Forbidden.` — it reports an upstream HTTP failure as a **successful** tool result. The host passes `isError` through untouched, because overriding a server's own protocol signal would be worse than reporting it, and the script additionally flags `text_reports_error_despite_is_error_false`. This is a third-party server behaviour, carried into [`risk_note.md`](risk_note.md) line 4.

---

## 6. Agent core and LLM provider unchanged

```
> git diff --name-only -- agent/ workflow/ app/services/llm_provider.py app/routes/ \
      benchmark/ safety/ telemetry/ tools/corpus_facts.py tools/migration_analyzer.py \
      tools/reference_search.py
(no output)
```

`agent/agent_loop.py` and `app/services/llm_provider.py` are byte-identical to `HEAD`. Four tests pin this so it cannot regress silently:

* `test_agent_loop_has_no_mcp_specific_logic` — the string `mcp` does not appear anywhere in `agent/agent_loop.py`;
* `test_agent_tool_vocabulary_is_unchanged_and_disjoint_from_mcp_tools` — `KNOWN_ACTIONS` is still exactly `{reference_search, chunk_retrieval, migration_analyzer, finish}`, with no MCP-derived namespaced name leaked in;
* `test_host_exposes_no_llm_function_calling_shim` — `McpHost.tool_schemas`, `McpTool.to_schema` and `McpToolCall.to_observation` do not exist, and `mcp_host.py` contains no `openai`, `function_calling` or `tool_choice` string;
* `test_inventory_always_counts_each_server_separately_from_the_sum` — discovery stays independent of the agent.

**Why no core change was needed.** The host is consumed through `McpHost.call(name, arguments)`, which takes an explicit tool name and returns an `McpToolCall` dataclass. Nothing in the project converts MCP tools into LLM function-calling schemas, and no MCP type crosses into the agent or the provider, so no MCP concept had to enter either one's vocabulary.

---

## 7. Tests and commands actually run

**Mocked / hermetic — no processes, no network, no vector store:**

```
> .venv\Scripts\python.exe -m pytest tests\test_week9.py -m "not live" -q
35 passed, 2 deselected, 1 warning in 10.54s
```

**Live — spawns both real MCP servers, real stdio, real registry HTTP:**

```
> .venv\Scripts\python.exe -m pytest tests\test_week9.py -m "live" -q
2 passed, 35 deselected, 1 warning in 42.40s
```

**Everything:**

```
> .venv\Scripts\python.exe -m pytest tests\ -q
134 passed, 1 warning in 65.10s
```

134 = 21 (`test_week7.py`) + 76 (`test_week8.py`) + 37 (`test_week9.py`, collected: 35 hermetic + 2 live). No pre-existing test was modified, skipped or deleted; no regression. The single warning is a pre-existing `chromadb`/`asyncio.iscoroutinefunction` deprecation, unrelated to this work.

**Integration verification script — live:**

```
> .venv\Scripts\python.exe scripts\verify_mcp_integration.py --tool package-registry:get-npm-package-details
=== Week 9 combined MCP integration ===
  doc-search           ok      2025-11-25   error=-
  package-registry     ok      2025-06-18   error=-
  per-server counts : {'doc-search': 4, 'package-registry': 16}
  combined (host)   : 20
  call doc-search__list_collections                     ok routed=True
  call package-registry__get-npm-package-details        ok routed=True
exit=0
```

`test_week9.py` sections: config parsing and validation; namespacing and routing (no processes); the two `live` tests; `chunk_retrieval` success paths; `chunk_retrieval` recoverable-error paths; docstring contract; agent-core/LLM-provider guards. The `live` marker is registered in `tests/conftest.py` via `pytest_configure` (the project has no `pytest.ini`/`pyproject.toml`). Tool-hardening detail is in [`error_before_after.md`](error_before_after.md).

---

## 8. Limitations

1. **Tools are invoked explicitly, not discovered-and-used by a model.** Every call is a hardcoded name plus arguments in the caller. The host makes the tools *reachable*; it does not decide when to use them. Automatic selection by the agent is out of scope and unimplemented.
2. **`package-registry` reports HTTP failures as success.** `isError=false` with a 403 in the body. The host passes the signal through faithfully; the script flags it heuristically by scanning the text for error markers. No host-level fix is possible without second-guessing a server's own protocol signal.
3. **The `npx` dependency is unpinned and network-dependent.** `mcp_config.json` says `"package-registry-mcp"` with no version, so the tool set can change between runs. This week it happened to match `wire.json`'s 16, but nothing guarantees it. See [`risk_note.md`](risk_note.md) line 1.
4. **No `tools/list_changed` subscription.** `package-registry` advertises `tools.listChanged: true`; the host re-runs `discover_tools()` on demand but does not subscribe to notifications, so a mid-session tool-list change is not noticed.
5. **No auth, no sandboxing.** Both servers run as local subprocesses with the user's own permissions. `doc-search` additionally runs the project interpreter with `DOC_SEARCH_REPO_ROOT` pointing at the repo, so it loads the real `.env`.
6. **Live tests are slow and network-bound.** They spawn two processes and download the npm package, and will fail offline. `-m "not live"` is the fast path.
7. **Collision routing is proven synthetically.** No two real servers in this config collide, so that path is unit-tested with fabricated inventories rather than exercised end-to-end over a real transport.
8. **Discovery does not cross into retrieval.** The agent's own tool vocabulary is unchanged, so MCP tools sit beside the native tools rather than being reachable from inside an agent run.

---

## 9. Autonomous LLM tool calling — removed

An earlier pass added a small model-facing surface alongside the host. It was **not** part of proving host access and has been removed:

| Removed | Was |
|---|---|
| `McpTool.to_schema()` | built an OpenAI-style `{"type": "function", …}` definition |
| `McpHost.tool_schemas()` | returned one per discovered tool, "for every discovered tool" |
| `McpToolCall.to_observation()` | rendered a ReAct-style `observation=` line with an `ERROR: ` prefix |
| `report["schema_sample"]` in the verification script | sampled the OpenAI payload into the evidence file |
| 2 tests asserting OpenAI payload shape | `test_tool_schema_is_openai_shaped…`, `…falls_back_to_a_generated_description…` |

None of it was used by the host, the agent, the provider or the verification script's actual checks — `to_observation` had zero call sites, and the two schema tests only asserted the shape of a payload nothing consumed. Removing it changes no proven behaviour. In its place:

* `McpTool.describe()` returns the tool exactly as its server advertised it, for logs and evidence files.
* Three tests replace the two removed ones, and one of them (`test_host_exposes_no_llm_function_calling_shim`) actively fails if any LLM-facing shim is reintroduced.

`app/services/llm_provider.py` was never modified at any point in Week 9 — see §6.

---

## Files

| Path | Change | Role |
|---|---|---|
| `app/services/mcp_host.py` | **new** | Configuration-driven MCP host: config parsing, spawn + `initialize`, dynamic `tools/list`, namespacing, routing, dispatch. The only MCP-aware module. |
| `scripts/verify_mcp_integration.py` | **new** | Evidence runner. Picks probe tools from the discovered inventory, dispatches one call per server, writes the JSON report. |
| `tests/test_week9.py` | **new** | 37 tests: 35 hermetic + 2 `@pytest.mark.live`. |
| `tests/conftest.py` | modified (+8) | Registers the `live` marker. Nothing else touched. |
| `eval/mcp_integration_report.json` | **new** | Machine-readable evidence, written by the script. |
| `eval/error_before_after.md` | **new** | Tool documentation + recoverable-error before/after with measured outputs. |
| `eval/risk_note.md` | **new** | Third-party security assessment, 5 lines. |
| `eval/WEEK9_SUBMISSION.md` | **new** | This report. |
| `tools/chunk_retrieval.py` | modified (+221/−28) | Documented contract, closed `status` enum, 5 recoverable error kinds, unexpected errors now propagate. |
| `mcp_config.json` | unchanged | Both servers were already declared correctly. |
| `agent/agent_loop.py` | **unchanged** | §6. |
| `app/services/llm_provider.py` | **unchanged** | §6. |
