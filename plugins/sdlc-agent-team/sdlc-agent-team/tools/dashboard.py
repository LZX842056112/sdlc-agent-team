#!/usr/bin/env python3
"""启动本地实时看板。

用法:
    python tools/dashboard.py
    python tools/dashboard.py --port 8765 --state docs/flow.json
"""

import argparse
import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import teamdef
from flow import idle_agent, project_status, read_optional_events

ROOT = teamdef.resolve_project()
HTML = Path(__file__).resolve().parent / "dashboard.html"


TEAM_CACHE = {"mtime": None, "value": None}


def load_team():
    mtime = teamdef.TEAM_YAML.stat().st_mtime_ns
    if TEAM_CACHE["mtime"] != mtime:
        TEAM_CACHE.update(mtime=mtime, value=teamdef.parse_team_yaml())
    return TEAM_CACHE["value"]


def build_meta():
    try:
        data = load_team()
    except OSError as exc:
        return {"error": str(exc)}
    return {
        "agents": [
            {"id": agent["id"], "title": agent.get("title", agent["id"])}
            for agent in data["agents"]
        ],
        "gates": [
            {"id": gate["id"], "name": gate.get("name", gate["id"])}
            for gate in data["gates"]
        ],
        "stages": {
            stage["id"]: stage.get("label", stage["id"])
            for stage in data["stages"] + data["hotfix_stages"]
        },
        "monitoring": data["monitoring"],
    }


def load_state():
    """读取项目状态和可选的 Agent 事件。"""
    team = load_team()
    status = project_status(ROOT / "docs" / "status.md", team)
    state = read_optional_events(Handler.state_path)
    state.update(status)
    for agent in team["agents"]:
        state["agents"].setdefault(agent["id"], idle_agent())
    values = [item.get("status", "idle") for item in state["agents"].values()]
    state["stats"] = {
        "active": values.count("working"),
        "idle": values.count("idle"),
        "blocked": values.count("blocked"),
        "handoffs": state["handoff_count"],
    }
    state["source"] = "status.md"
    return state


class Handler(BaseHTTPRequestHandler):
    state_path = ROOT / "docs" / "flow.json"

    def send_body(self, body, content_type, code=200):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            if not HTML.exists():
                self.send_body(b"dashboard.html not found", "text/plain", 404)
                return
            self.send_body(HTML.read_bytes(), "text/html; charset=utf-8")
            return
        if self.path == "/api/state":
            try:
                payload = load_state()
            except (OSError, ValueError) as exc:
                payload = {
                    "error": str(exc),
                    "hint": "无法读取项目状态。%s" % exc,
                }
            self.send_body(
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8")
            return
        if self.path == "/api/meta":
            self.send_body(
                json.dumps(build_meta(), ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8")
            return
        if self.path == "/api/health":
            self.send_body(b"ok", "text/plain; charset=utf-8")
            return
        self.send_body(b"not found", "text/plain", 404)

    def log_message(self, fmt, *args):
        return


def main():
    global ROOT
    parser = argparse.ArgumentParser(description="SDLC 实时看板")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--project", help="项目根目录。默认自动判断")
    parser.add_argument("--state", help="事件文件。相对路径以当前目录为基准")
    parser.add_argument("--open", action="store_true", help="自动打开浏览器")
    args = parser.parse_args()

    ROOT = teamdef.resolve_project(args.project)
    if args.state is None:
        try:
            monitoring = load_team()["monitoring"]
        except OSError:
            monitoring = {}
        Handler.state_path = (ROOT / monitoring.get("flow_state", "docs/flow.json")).resolve()
    else:
        Handler.state_path = Path(args.state).resolve()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = "http://%s:%d" % (args.host, args.port)
    print("看板地址: %s" % url)
    print("项目状态: %s" % (ROOT / "docs" / "status.md"))
    print("事件文件: %s" % Handler.state_path)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
