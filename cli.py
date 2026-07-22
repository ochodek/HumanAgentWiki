#!/usr/bin/env python3
"""HumanAgentWiki — unified command line.

  python cli.py init-db            # create tables + extensions + indexes (schema.sql)
  python cli.py index [--full]     # (re)index your notes  (incremental by default)
  python cli.py search "query"     # quick hybrid search from the terminal
  python cli.py serve              # run the MCP server for your agents
  python cli.py web [--port 8808]  # web UI: manage categories, write/link notes, search
  python cli.py selftest           # health checks
"""
import os
import sys
import argparse
import json

HERE = os.path.dirname(os.path.abspath(__file__))


def cmd_init_db(_):
    import psycopg
    from common import DSN, EMB_DIM
    with open(os.path.join(HERE, "schema.sql"), encoding="utf-8") as f:
        sql = f.read().replace("vector(1024)", f"vector({EMB_DIM})")
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(sql)
    print(f"Database initialized - schema.sql applied (embedding dim {EMB_DIM}).")


def cmd_index(args):
    import index
    index.run(full=args.full)


def cmd_search(args):
    from server import search
    rows = search(
        args.query,
        k=args.k,
        category=args.category,
        node_type=args.node_type,
        memory_status=args.memory_status,
        memory_scope=args.memory_scope,
    )
    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        print("(no results)"); return
    for r in rows:
        print(f"- [{r['category']}] {r['title']}\n  {r['snippet']}\n")


def cmd_serve(_):
    import server
    server.serve()


def cmd_web(args):
    import uvicorn
    from common import WEB_HOST, WEB_PORT
    port = args.port or WEB_PORT
    print(f"HumanAgentWiki web UI: http://{WEB_HOST}:{port}", flush=True)
    uvicorn.run("web:app", host=WEB_HOST, port=port)


def cmd_selftest(_):
    import selftest
    sys.exit(selftest.run())


def build_parser():
    p = argparse.ArgumentParser(prog="humanagentwiki")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)
    pi = sub.add_parser("index"); pi.add_argument("--full", action="store_true"); pi.set_defaults(fn=cmd_index)
    ps = sub.add_parser("search")
    ps.add_argument("query")
    ps.add_argument("-k", type=int, default=8)
    ps.add_argument("--category", default="")
    ps.add_argument("--node-type", default="")
    ps.add_argument("--memory-status", default="")
    ps.add_argument("--memory-scope", default="")
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(fn=cmd_search)
    sub.add_parser("serve").set_defaults(fn=cmd_serve)
    pw = sub.add_parser("web"); pw.add_argument("--port", type=int, default=None); pw.set_defaults(fn=cmd_web)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    return p


def main():
    p = build_parser()
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
