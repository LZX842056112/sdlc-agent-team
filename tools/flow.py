#!/usr/bin/env python3
"""记录 Agent 事件，或查看 docs/status.md 中的项目状态。

用法:
    python tools/flow.py start --agent analyst --stage G1 --task "写需求"
    python tools/flow.py handoff --from analyst --to reviewer --artifact docs/01-requirements.md
    python tools/flow.py done --agent analyst --artifact docs/01-requirements.md
    python tools/flow.py block --agent backend --reason "等待接口契约"
    python tools/flow.py show
    python tools/flow.py --project <项目> show
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import teamdef


class EventFileError(ValueError):
    """无法读取流程事件。"""


def known_stages(team):
    stages = {"INIT", "DONE"}
    for entry in team["stages"] + team["hotfix_stages"] + team["gates"]:
        stages.add(entry["id"])
    for mode in team["modes"].values():
        stages.update(mode.get("stages", []))
    return stages


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def project_status(path, team):
    try:
        status = teamdef.read(path)
    except FileNotFoundError:
        status = ""
    except UnicodeDecodeError as exc:
        raise teamdef.StatusFormatError("状态板不是 UTF-8: %s" % path) from exc
    try:
        fields = teamdef.status_fields(status)
        mode = fields.get("mode", "未判定")
        active = teamdef.mode_gate_ids(team, mode)
        passed = teamdef.passed_gate_ids(status).intersection(active)
    except teamdef.StatusFormatError as exc:
        raise teamdef.StatusFormatError("无法读取状态板 %s。%s" % (path, exc)) from exc
    return {
        "mode": mode,
        "stage": fields.get("stage", "INIT"),
        "gate": len(passed),
        "active_gates": active,
        "passed_gates": sorted(passed),
    }


def empty_events():
    return {"updated": "", "agents": {}, "flows": [], "handoff_count": 0}


def unique_json_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("JSON 对象有重复的键。")
    return result


def check_text_fields(item, fields, name):
    if not isinstance(item, dict):
        raise ValueError("%s 必须是对象。" % name)
    for field in fields:
        if field in item and not isinstance(item[field], str):
            raise ValueError("%s.%s 必须是字符串。" % (name, field))


def load_events(path):
    try:
        raw = json.loads(teamdef.read(path), object_pairs_hook=unique_json_object)
        if not isinstance(raw, dict):
            raise ValueError("事件数据必须是对象。")
        # 同时检查非有限数值和无效的 Unicode 字符。
        json.dumps(raw, allow_nan=False, ensure_ascii=False).encode("utf-8")
        events = empty_events()
        for field, default in events.items():
            value = raw.get(field, default)
            if type(value) is not type(default):
                raise ValueError("%s 的类型错误。" % field)
            events[field] = value
        for name, item in events["agents"].items():
            check_text_fields(item, ("status", "task", "stage", "artifact", "since"), "agents.%s" % name)
        for index, item in enumerate(events["flows"]):
            name = "flows[%d]" % index
            check_text_fields(item, ("from", "to", "artifact", "status", "note", "time"), name)
            if "from" not in item or "to" not in item:
                raise ValueError("%s 缺少 from 或 to。" % name)
        retained_count = len(events["flows"])
        if "handoff_count" not in raw:
            events["handoff_count"] = retained_count
        elif events["handoff_count"] < retained_count:
            raise ValueError("handoff_count 小于交接记录数。")
        return events
    except FileNotFoundError:
        return empty_events()
    except (OSError, ValueError, RecursionError) as exc:
        raise EventFileError("无法读取事件文件 %s。%s" % (path, exc)) from exc


def read_optional_events(path):
    try:
        return load_events(path)
    except EventFileError as exc:
        return {**empty_events(), "events_error": str(exc)}


def save(path, state):
    completed_to_keep = 50
    retained = []
    for flow in reversed(state["flows"]):
        if flow.get("status") == "done":
            if completed_to_keep == 0:
                continue
            completed_to_keep -= 1
        retained.append(flow)
    retained.reverse()
    state["flows"] = retained
    state["updated"] = now()
    with teamdef.atomic_text_writer(path) as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2)


def idle_agent():
    return {"status": "idle", "task": "", "stage": "", "artifact": "", "since": ""}


def agent(state, name, known_agents):
    if name not in state["agents"]:
        if name not in known_agents:
            raise SystemExit("未知 Agent: %s" % name)
        state["agents"][name] = idle_agent()
    return state["agents"][name]


def cmd_init(args):
    save(args.state_path, empty_events())
    print("已初始化 %s" % args.state_path)


def cmd_start(args):
    if args.stage and args.stage not in known_stages(args.team):
        raise SystemExit("未知阶段: %s" % args.stage)
    state = load_events(args.state_path)
    item = agent(state, args.agent, args.known_agents)
    item.update({
        "status": "working",
        "task": args.task or "",
        "stage": args.stage or project_status(args.status_path, args.team)["stage"],
        "artifact": "",
        "since": now(),
    })
    save(args.state_path, state)
    print("%s -> working" % args.agent)


def cmd_handoff(args):
    state = load_events(args.state_path)
    source = agent(state, args.source, args.known_agents)
    target = agent(state, args.target, args.known_agents)
    flow = {
        "from": args.source,
        "to": args.target,
        "artifact": args.artifact or "",
        "status": args.status or "in-review",
        "note": args.note or "",
        "time": now(),
    }
    state["flows"].append(flow)
    state["handoff_count"] += 1
    source["status"] = "waiting"
    target["status"] = "working"
    target["task"] = args.note or ("处理 %s" % args.artifact if args.artifact else "接收任务")
    target["artifact"] = args.artifact or ""
    target["stage"] = project_status(args.status_path, args.team)["stage"]
    target["since"] = now()
    save(args.state_path, state)
    print("%s -> %s" % (args.source, args.target))


def cmd_done(args):
    state = load_events(args.state_path)
    item = agent(state, args.agent, args.known_agents)
    target = None
    for flow in reversed(state["flows"]):
        if flow.get("status") == "done":
            continue
        if args.agent not in (flow.get("from"), flow.get("to")):
            continue
        if args.artifact and flow.get("artifact") != args.artifact:
            continue
        target = flow
        break
    if args.artifact and target is None:
        print("未找到匹配交接: %s" % args.artifact)
        return 1
    item["status"] = "idle"
    item["task"] = ""
    if args.artifact:
        item["artifact"] = args.artifact
    if target is not None:
        target["status"] = "done"
        other = target["to"] if target.get("from") == args.agent else target["from"]
        other_item = state["agents"].get(other)
        if other_item and other_item.get("status") == "waiting":
            other_item["status"] = "idle"
    save(args.state_path, state)
    print("%s -> idle" % args.agent)
    return 0


def cmd_block(args):
    state = load_events(args.state_path)
    item = agent(state, args.agent, args.known_agents)
    item["status"] = "blocked"
    item["task"] = args.reason or "阻塞"
    item["since"] = now()
    save(args.state_path, state)
    print("%s -> blocked" % args.agent)


def cmd_show(args):
    status = project_status(args.status_path, args.team)
    state = read_optional_events(args.state_path)
    print("模式: %s" % status["mode"])
    print("阶段: %s  门: %d" % (status["stage"], status["gate"]))
    if "events_error" in state:
        print(state["events_error"], file=sys.stderr)
        return
    active = [name for name, item in state["agents"].items() if item.get("status") == "working"]
    blocked = [name for name, item in state["agents"].items() if item.get("status") == "blocked"]
    print("活跃: %s" % (", ".join(active) or "无"))
    print("阻塞: %s" % (", ".join(blocked) or "无"))
    print("最近交接:")
    for flow in state["flows"][-5:]:
        print("  %s -> %s  %s  %s" % (
            flow.get("from"), flow.get("to"),
            flow.get("artifact"), flow.get("status")))


def main():
    parser = argparse.ArgumentParser(description="SDLC 流程状态")
    parser.add_argument("--project", default="",
                        help="项目根目录。默认自动判断")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="清空流程事件").set_defaults(func=cmd_init)
    sub.add_parser("sync", help="查看状态，与 show 相同").set_defaults(func=cmd_show)
    sub.add_parser("show").set_defaults(func=cmd_show)

    start = sub.add_parser("start")
    start.add_argument("--agent", required=True)
    start.add_argument("--stage", default="")
    start.add_argument("--task", default="")
    start.set_defaults(func=cmd_start)

    handoff = sub.add_parser("handoff")
    handoff.add_argument("--from", dest="source", required=True)
    handoff.add_argument("--to", dest="target", required=True)
    handoff.add_argument("--artifact", default="")
    handoff.add_argument("--status", default="in-review")
    handoff.add_argument("--note", default="")
    handoff.set_defaults(func=cmd_handoff)

    done = sub.add_parser("done")
    done.add_argument("--agent", required=True)
    done.add_argument("--artifact", default="")
    done.set_defaults(func=cmd_done)

    block = sub.add_parser("block")
    block.add_argument("--agent", required=True)
    block.add_argument("--reason", default="")
    block.set_defaults(func=cmd_block)

    args = parser.parse_args()
    root = teamdef.resolve_project(args.project)
    try:
        args.team = teamdef.parse_team_yaml()
        args.known_agents = {agent["id"] for agent in args.team["agents"]}
        args.state_path = root / args.team["monitoring"].get(
            "flow_state", "docs/flow.json")
        args.status_path = root / "docs" / "status.md"
        if args.func is cmd_show:
            return cmd_show(args)
        with teamdef.lock_file(args.state_path):
            return args.func(args)
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
