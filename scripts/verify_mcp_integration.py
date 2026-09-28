"""
scripts/verify_mcp_integration.py
--------------------------------
Evidence runner for the Week 9 combined-MCP-integration check.

Loads every server in ``mcp_config.json`` through :mod:`app.services.mcp_host`,
discovers tools from each server's real ``tools/list``, then dispatches one
call per server through the single integrated host and writes the result to
``eval/mcp_integration_report.json``.

Nothing about the servers, tool names or tool counts is hardcoded: the call
targets are chosen from the discovered inventory at runtime.

Usage:
    .venv\\Scripts\\python.exe scripts\\verify_mcp_integration.py
    .venv\\Scripts\\python.exe scripts\\verify_mcp_integration.py --no-calls
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.mcp_host import McpHost  # noqa: E402

DEFAULT_REPORT = ROOT / "eval" / "mcp_integration_report.json"

#: Probe input used to fill a required *string* parameter when a server offers
#: no zero-argument tool. This is test input only — it never influences the
#: discovered tool list, names or counts.
DEFAULT_PROBE_VALUE = "react"

#: Preferred zero-argument tools, tried before falling back to schema synthesis.
ZERO_ARG_PREFERENCE = ("list_collections", "list_collections_and_docs", "list")

#: Substrings that mark a server response as an error report even when the MCP
#: ``isError`` flag is false. The third-party registry server returns upstream
#: HTTP failures inside a successful envelope, so the host also inspects text.
ERROR_TEXT_MARKERS = (
    "error fetching",
    "request failed",
    "forbidden",
    "not found",
    "failed with status",
)


def _looks_like_error(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ERROR_TEXT_MARKERS)


def _synthesise_args(schema: dict[str, Any], probe_value: str) -> dict[str, Any]:
    """Build a minimal valid argument object from a tool's own input schema.

    Required string properties get ``probe_value``; required numbers/booleans get
    a conservative default. Nothing is hardcoded per tool, so this works for any
    server added to the config later.
    """
    args: dict[str, Any] = {}
    properties = schema.get("properties") or {}
    for name in schema.get("required") or []:
        declared = (properties.get(name) or {}).get("type")
        if declared == "integer" or declared == "number":
            args[name] = 1
        elif declared == "boolean":
            args[name] = False
        elif declared == "array":
            args[name] = []
        else:
            args[name] = probe_value
    return args


def _pick_call_targets(
    tools: list[Any], explicit: list[str], probe_value: str, pinned: list[str] | None = None
) -> list[dict[str, Any]]:
    """Choose one real tool per server, deriving arguments from its own schema.

    ``pinned`` entries look like ``server:tool``; a pinned tool replaces that
    server's automatic choice, letting a reviewer reproduce a specific capture.
    """
    by_server: dict[str, list[Any]] = {}
    for tool in tools:
        by_server.setdefault(tool.server, []).append(tool)

    pins: dict[str, str] = {}
    for entry in pinned or []:
        server, _, tool_name = entry.partition(":")
        pins[server or next(iter(by_server), "")] = tool_name

    targets: list[dict[str, Any]] = []
    for server, server_tools in by_server.items():
        names = {t.name: t for t in server_tools}
        chosen = names.get(pins.get(server, ""))
        if chosen is None:
            chosen = next((t for t in server_tools if t.name in ZERO_ARG_PREFERENCE), None)
        if chosen is None:
            chosen = server_tools[0]
        targets.append(
            {
                "server": server,
                "tool": chosen.name,
                "qualified_name": chosen.qualified_name,
                "arguments": _synthesise_args(chosen.input_schema, probe_value),
                "required_params": list(chosen.input_schema.get("required") or []),
                "arguments_source": "synthesised from the tool's own inputSchema",
            }
        )
    return targets


async def _run(
    config_path: Path | None,
    make_calls: bool,
    extra_args: str,
    probe_value: str,
    pinned: list[str] | None = None,
) -> dict[str, Any]:
    started = time.time()
    report: dict[str, Any] = {
        "artifact": "Week 9 combined MCP integration verification",
        "config_path": str(config_path) if config_path else "<default: repo root mcp_config.json>",
        "tool_counts": {},
        "discovery": {},
        "handshake": [],
        "calls": [],
    }

    async with McpHost.from_config(config_path) as host:
        report["config_servers"] = host.server_names
        tools = await host.discover_tools()
        inventory = host.inventory()
        report["discovery"] = inventory
        report["tool_counts"] = {
            "per_server": inventory["per_server_tool_counts"],
            "combined_discovered": inventory["combined_tool_count"],
            "arithmetic_sum": sum(inventory["per_server_tool_counts"].values()),
            "combined_equals_arithmetic": (
                inventory["combined_tool_count"] == sum(inventory["per_server_tool_counts"].values())
            ),
            "basis": "host merged N live tools/list responses; not a hardcoded constant",
        }
        report["discovered_tool_sample"] = [t.describe() for t in host.tools[:2]]
        report["handshake"] = [
            {
                "server": s["name"],
                "connected": s["connected"],
                "server_info": s["server_info"],
                "protocol_version": s["protocol_version"],
                "error": s["error"],
            }
            for s in inventory["servers"]
        ]

        # Alias routing: a bare unique name must reach the same server+tool.
        alias_checks = []
        for tool in tools:
            if tool.aliases:
                alias_checks.append(
                    {
                        "alias": tool.aliases[0],
                        "qualified_name": tool.qualified_name,
                        "resolves_to": list(host.resolve(tool.aliases[0])),
                    }
                )
                break
        report["alias_routing"] = alias_checks

        if make_calls:
            override = json.loads(extra_args) if extra_args else None
            for target in _pick_call_targets(tools, [], probe_value, pinned):
                if override is not None:
                    target["arguments"] = override
                    target["arguments_source"] = "--args override"
                # Record the routing decision the host made for this handle.
                route = host.resolve(target["qualified_name"])
                target["host_route"] = {"server": route[0], "tool": route[1]}
                t0 = time.time()
                try:
                    result = await host.call(target["qualified_name"], target["arguments"])
                    target.update(
                        {
                            "ok": not result.is_error,
                            "is_error": result.is_error,
                            "response_server": result.server,
                            "response_tool": result.tool,
                            "routed_correctly": (
                                result.server == target["server"] and result.tool == target["tool"]
                            ),
                            "content_block_types": list(result.block_types),
                            "result_preview": result.text[:400],
                            "result_length": len(result.text),
                            "text_reports_error_despite_is_error_false": (
                                not result.is_error and _looks_like_error(result.text)
                            ),
                            "elapsed_s": round(time.time() - t0, 2),
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - reported, not hidden
                    target.update({"ok": False, "exception": f"{type(exc).__name__}: {exc}"})
                report["calls"].append(target)

        # Provenance check: two servers must not return the same payload, or the
        # "routed_correctly" flags above would not prove anything.
        succeeded = [c for c in report["calls"] if c.get("ok")]
        payloads = [c["result_preview"] for c in succeeded]
        report["payloads_distinct"] = len(set(payloads)) == len(payloads) if payloads else None

    report["elapsed_s"] = round(time.time() - started, 2)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="Path to an MCP config file.")
    parser.add_argument("--out", default=str(DEFAULT_REPORT), help="Where to write the JSON report.")
    parser.add_argument("--no-calls", action="store_true", help="Discover tools but skip tools/call.")
    parser.add_argument("--args", default="", help="JSON object of arguments for each probe call.")
    parser.add_argument(
        "--probe-value",
        default=DEFAULT_PROBE_VALUE,
        help="String used to fill a required string parameter on the probe call.",
    )
    parser.add_argument(
        "--tool",
        action="append",
        default=[],
        metavar="SERVER:TOOL",
        help="Pin the probe tool for one server (repeatable).",
    )
    args = parser.parse_args()

    import anyio

    report = anyio.run(
        _run,
        Path(args.config) if args.config else None,
        not args.no_calls,
        args.args,
        args.probe_value,
        args.tool,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    counts = report["tool_counts"]
    print("\n=== Week 9 combined MCP integration ===")
    for entry in report["handshake"]:
        mark = "ok" if entry["connected"] else "FAILED"
        print(f"  {entry['server']:<20} {mark:<7} {entry['protocol_version']:<12} error={entry['error'] or '-'}")
    print(f"  per-server counts : {counts['per_server']}")
    print(f"  combined (host)   : {counts['combined_discovered']}")
    for call in report["calls"]:
        status = "ok" if call.get("ok") else f"FAILED {call.get('exception') or call.get('is_error')}"
        print(f"  call {call['qualified_name']:<48} {status} routed={call.get('routed_correctly')}")
    print(f"  report -> {out}")
    return 0 if all(c.get("ok") for c in report["calls"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
