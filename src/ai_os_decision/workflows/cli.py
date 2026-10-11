"""Workflow subcommands; independent of Laya and all model dependencies."""
from __future__ import annotations

import json
from pathlib import Path

from .registry import Registry

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "data" / "workflow-library"


def configure(sub):
    parser = sub.add_parser("workflows", help="static workflow library; never executes workflows")
    parser.add_argument("--db", type=Path, default=DEFAULT_ROOT / "registry.sqlite3")
    commands = parser.add_subparsers(dest="workflow_command", required=True)
    seed = commands.add_parser("sources")
    seed.add_argument("--catalog", type=Path)
    seed.add_argument("--manifest", type=Path)
    sync = commands.add_parser("sync")
    sync.add_argument("--source", action="append", help="registered source ID; repeatable; default all")
    sync.add_argument("--cache", type=Path, default=DEFAULT_ROOT)
    sync.add_argument("--official-limit", type=int, default=0, help="0 = complete public catalog; nonzero is explicitly partial")
    search = commands.add_parser("search")
    search.add_argument("query", nargs="?", default="")
    for key in ["category", "node", "integration", "source", "risk", "status", "external-service", "exclude-integration"]:
        search.add_argument("--" + key)
    search.add_argument("--local-capable", action="store_const", const=True, default=None)
    search.add_argument("--credentials", choices=["true", "false"])
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset", type=int, default=0)
    get = commands.add_parser("get"); get.add_argument("workflow_id")
    export = commands.add_parser("export"); export.add_argument("workflow_id")
    export.add_argument("--variant"); export.add_argument("--output", type=Path, required=True)
    export.add_argument("--acknowledge-risk", action="store_true")
    commands.add_parser("stats")
    report = commands.add_parser("report"); report.add_argument("--output", type=Path, required=True)
    serve = commands.add_parser("serve"); serve.add_argument("--port", type=int, default=8766)
    commands.add_parser("mcp")


def run(args):
    command = args.workflow_command
    if command == "serve":
        from .interfaces import http_server
        http_server(args.db, args.port).serve_forever()
        return 0
    if command == "mcp":
        from .interfaces import mcp_server
        mcp_server(args.db).run(transport="stdio")
        return 0
    writable = command == "sync" or (command == "sources" and bool(args.catalog))
    registry = Registry(args.db, readonly=not writable)
    try:
        if command == "sources":
            if args.catalog:
                from .sources import seed_sources
                existing = {s["id"] for s in registry.sources()}
                for source in seed_sources(args.catalog):
                    if source["id"] not in existing:
                        registry.register(source)
            result = registry.sources()
            if args.manifest:
                args.manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        elif command == "sync":
            from .sources import sync
            if args.official_limit < 0:
                raise ValueError("official limit must be nonnegative")
            result = sync(registry, args.cache, args.official_limit, args.source)
        elif command == "search":
            result = registry.search(args.query, **{k: getattr(args, k) for k in ["category", "node", "integration", "source", "local_capable", "risk", "status", "external_service", "exclude_integration", "limit", "offset"]},
                                     credentials=None if args.credentials is None else args.credentials == "true")
        elif command == "get":
            result = registry.get(args.workflow_id)
        elif command == "export":
            result = registry.export(args.workflow_id, args.variant, args.acknowledge_risk)
            # Exclusive creation avoids overwriting an existing review artifact.
            with args.output.open("x") as file:
                json.dump(result["workflow"], file, ensure_ascii=False, indent=2)
            result = {"output": str(args.output), "review": result["review"], "warning": result["warning"]}
        elif command == "report":
            from .report import write_report
            write_report(registry, args.output)
            result = {"output": str(args.output)}
        else:
            result = registry.stats()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        registry.close()
