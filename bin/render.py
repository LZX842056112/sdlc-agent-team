#!/usr/bin/env python3
"""从 team.yaml 生成角色资料、平台入口和文档区块。

用法:
    python bin/render.py
    python bin/render.py --check
"""

import argparse
import json
import re
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "tools"))

import teamdef
from install import project_agent_entries

TEAM_YAML = PACK / "team.yaml"
AGENTS_MD = PACK / "AGENTS.md"
PROTOCOL_MD = PACK / "protocol.md"
PROJECT_STATE_MD = PACK / "templates" / "PROJECT_STATE.md"
CLAUDE_MD = PACK / "CLAUDE.md"
SKILL_MD = PACK / "SKILL.md"
README_MD = PACK / "README.md"
PLATFORMS_MD = PACK / "PLATFORMS.md"
MARKETPLACE = PACK / ".claude-plugin" / "marketplace.json"

BLOCKS = {
    AGENTS_MD: (
        "AGENTS_TEAM", "AGENTS_STAGES", "AGENTS_STATE_MACHINE",
        "AGENTS_MODES", "AGENTS_PROFILES", "AGENTS_ROUTES",
        "AGENTS_ARTIFACTS", "RELEASE_HEADER", "RULES_SUMMARY",
    ),
    PROTOCOL_MD: ("VERSION", "PROTOCOL_GATES", "PROTOCOL_HOTFIX", "PROTOCOL_HOTFIX_CHECKS"),
    PROJECT_STATE_MD: ("PROJECT_STATE_GATES",),
    CLAUDE_MD: ("RELEASE_HEADER",),
    SKILL_MD: ("RELEASE_HEADER",),
    PLATFORMS_MD: ("RELEASE_HEADER",),
    README_MD: ("RELEASE_HEADER", "README_OVERVIEW"),
}


def artifact_conditions(gates, normal=None, profiles=None):
    """从门的工件清单和规模配置推导条件工件。返回 {路径: [条件]}。"""
    if normal is None:
        normal = set()
        for gate in gates:
            normal.update(teamdef.parse_list(gate.get("artifacts")))
    conditions = {}

    def add(paths, label, skip_normal=True):
        for path in paths:
            if skip_normal and path in normal:
                continue
            labels = conditions.setdefault(path, [])
            if label not in labels:
                labels.append(label)

    for gate in gates:
        add(teamdef.parse_list(gate.get("artifacts_brownfield")), "二次开发")
        add(teamdef.parse_list(gate.get("artifacts_ui")), "有界面")
        add(teamdef.parse_list(gate.get("artifacts_backend")), "有后端")
        add(teamdef.parse_list(gate.get("artifacts_hotfix")), "热修")
        add(teamdef.parse_list(gate.get("artifacts_hotfix_any")), "热修候选",
            skip_normal=False)
        add(teamdef.parse_list(gate.get("artifacts_hotfix_security")), "有安全影响的热修",
            skip_normal=False)
    for key, profile in (profiles or {}).items():
        label = profile.get("label", key)
        display = "小项目" if label == "小" else label
        for path in teamdef.parse_list(profile.get("skip_artifacts", "")):
            labels = conditions.setdefault(path, [])
            if "%s跳过" % display not in labels:
                labels.append("%s跳过" % display)
        for source, targets in teamdef.parse_pairs(
                profile.get("replace_artifacts", "")).items():
            for target in targets:
                labels = conditions.setdefault(source, [])
                if "%s可合并到 %s" % (display, target) not in labels:
                    labels.append("%s可合并到 %s" % (display, target))
                labels = conditions.setdefault(target, [])
                if "%s合并文档" % display not in labels:
                    labels.append("%s合并文档" % display)
        for path, _, heading in teamdef.profile_sections(profile):
            label_text = "%s替代章节（%s）" % (display, heading)
            labels = conditions.setdefault(path, [])
            if label_text not in labels:
                labels.append(label_text)
    return conditions


def artifact_table(artifacts, optional, gates, profiles=None):
    normal = set()
    for gate in gates:
        normal.update(teamdef.parse_list(gate.get("artifacts")))
    conditions = artifact_conditions(gates, normal, profiles)
    rows = ["| 工件 | 负责人 | 类型 | 条件 |", "|---|---|---|---|"]
    for path, owner in artifacts.items():
        if path in optional:
            kind = "状态源" if path == "docs/status.md" else "按需"
        elif path in normal:
            kind = "门禁"
        elif path in conditions:
            kind = "条件门禁"
        else:
            kind = "门禁"
        labels = " / ".join(conditions.get(path, ())) or "—"
        rows.append("| %s | %s | %s | %s |" % (
            path, teamdef.OWNER_LABELS.get(owner, owner), kind, labels))
    return "\n".join(rows)


def team_table(agents, cards):
    rows = ["| 角色 ID | 角色 | 角色卡 | 参与阶段 | 门禁职责 | 交接对象 |",
            "|---|---|---|---|---|---|"]
    for agent in agents:
        agent_id = agent["id"]
        card = cards.get(agent_id)
        if not card:
            raise SystemExit("team.yaml 角色没有角色卡: %s" % agent_id)
        gates = agent.get("gate_label") or "、".join(
            teamdef.parse_list(agent.get("gate")))
        handoff = agent["handoff"]
        recipients = "全体角色" if handoff == "all" else "、".join(teamdef.parse_list(handoff))
        rows.append("| `%s` | %s | [%s](%s) | %s | %s | %s |" % (
            agent_id,
            agent.get("title", agent_id),
            Path(card).name,
            card,
            agent.get("stage_label", ""),
            gates or "—",
            recipients,
        ))
    return "\n".join(rows)


def stage_table(stages, gates):
    owner_labels = {
        gate["id"]: teamdef.GATE_OWNER_LABELS.get(
            gate.get("gate_owner", ""), gate.get("gate_owner", ""))
        for gate in gates
    }
    rows = ["| 阶段 | 工作 | 交付负责人 | 门 | 门负责人 |", "|---|---|---|---|---|"]
    for stage in stages:
        rows.append("| %s %s | %s | %s | %s | %s |" % (
            stage.get("id", ""),
            stage.get("label", ""),
            stage.get("work", ""),
            "、".join(teamdef.parse_list(stage.get("owners"))),
            stage.get("gate", ""),
            owner_labels.get(stage.get("gate", ""), ""),
        ))
    return "\n".join(rows)


def route_table(routes):
    rows = ["| 任务 | Agent |", "|---|---|"]
    for route in routes:
        rows.append("| %s | %s |" % (
            route.get("task", ""), route.get("agent", "")))
    return "\n".join(rows)


def state_machine(modes):
    rows = []
    for mode in modes.values():
        stages = teamdef.parse_list(mode.get("stages"))
        rows.append("%s: INIT → %s → DONE" % (
            mode.get("label", ""), " → ".join(stages)))
    return "```\n%s\n```" % "\n".join(rows)


def project_gate_table(gates):
    rows = ["| 门 | 名称 | 状态 | 门负责人 | 返工次数 | 缺项 |", "|---|---|---|---|---|---|"]
    for gate in gates:
        owner = teamdef.GATE_OWNER_LABELS.get(
            gate.get("gate_owner", ""), gate.get("gate_owner", ""))
        rows.append("| %s | %s | %s | %s | 0 | |" % (
            gate["id"], gate.get("name", ""),
            gate.get("default_status", "pending"), owner))
    return "\n".join(rows)


def mode_rules(modes):
    return "\n".join(
        "- %s。使用%s模式。" % (mode["detect"].rstrip("。"), mode["label"])
        for mode in modes.values())


def profile_table(profiles):
    rows = ["| 配置 | 可兼任的工件职责 | 跳过工件 | 合并文档 | 替代章节 |",
            "|---|---|---|---|---|"]
    for key, profile in profiles.items():
        aliases = ["%s 可负责 %s 的工件" % (owner, "、".join(roles))
                   for owner, roles in teamdef.parse_pairs(
                       profile.get("owner_aliases", "")).items()]
        skip = "、".join(teamdef.parse_list(profile.get("skip_artifacts", "")))
        replacements = [
            "%s → %s" % (source, "、".join(targets))
            for source, targets in teamdef.parse_pairs(
                profile.get("replace_artifacts", "")).items()
        ]
        sections = [
            "%s → %s（%s）" % (source, target, heading) if source else
            "%s（%s）" % (target, heading)
            for target, source, heading in teamdef.profile_sections(profile)
        ]
        label = profile.get("label", key)
        display = "小项目" if label == "小" else label
        rows.append("| %s | %s | %s | %s | %s |" % (
            display, "；".join(aliases) or "无", skip or "无",
            "；".join(replacements) or "无", "；".join(sections) or "无"))
    return "\n".join(rows)


def gate_sections(gates, profiles=None):
    rows = []
    for gate in gates:
        title = gate.get("name", "")
        rows.append("### %s %s" % (gate["id"], title))
        rows.append("")
        for check in gate.get("checks", []):
            rows.append("- %s。" % check.rstrip("。"))
        rows.append("")
        for key, mode in (("checks_quick", "轻量变更"), ("checks_hotfix", "热修")):
            if gate.get(key):
                rows.extend(["%s使用以下检查项。" % mode, ""])
                rows.extend("- %s。" % check.rstrip("。") for check in gate[key])
                rows.append("")
        required = teamdef.parse_list(gate.get("artifacts"))
        if required:
            rows.append("必需工件: %s。" % "、".join(required))
        extra = teamdef.parse_list(gate.get("artifacts_brownfield"))
        if extra:
            rows.append("二次开发另需: %s。" % "、".join(extra))
        extra = teamdef.parse_list(gate.get("artifacts_ui"))
        if extra:
            rows.append("有界面时另需: %s。" % "、".join(extra))
        extra = teamdef.parse_list(gate.get("artifacts_backend"))
        if extra:
            rows.append("有后端时另需: %s。" % "、".join(extra))
        extra = teamdef.parse_list(gate.get("artifacts_hotfix"))
        if extra:
            rows.append("热修改为: %s。" % "、".join(extra))
        extra = teamdef.parse_list(gate.get("artifacts_hotfix_any"))
        if extra:
            rows.append("热修按界面和后端的改动范围提交构建说明。"
                        "未确定必需说明时，从适用候选中提交至少一份。候选工件为 %s。"
                        % "、".join(extra))
        extra = teamdef.parse_list(gate.get("artifacts_hotfix_security"))
        if extra:
            rows.append("热修安全影响为有时，另需 %s。" % "、".join(extra))
        extra = teamdef.parse_list(gate.get("artifacts_quick"))
        if extra:
            rows.append("轻量变更只需 %s。" % "、".join(extra))
        gate_paths = []
        for key in teamdef.GATE_ARTIFACT_KEYS:
            for path in teamdef.parse_list(gate.get(key)):
                if path not in gate_paths:
                    gate_paths.append(path)
        for key, profile in (profiles or {}).items():
            label = profile.get("label", key)
            display = "小项目" if label == "小" else label
            skipped = [path for path in gate_paths
                       if path in teamdef.parse_list(
                           profile.get("skip_artifacts", ""))]
            if skipped:
                rows.append("%s跳过: %s。" % (display, "、".join(skipped)))
            replaces = []
            for source, targets in teamdef.parse_pairs(
                    profile.get("replace_artifacts", "")).items():
                if source in gate_paths:
                    replaces.append("%s 可合并为 %s" % (
                        source, "、".join(targets)))
            if replaces:
                rows.append("%s合并: %s。" % (display, "；".join(replaces)))
            sections = []
            for path, source, heading in teamdef.profile_sections(profile):
                if path in gate_paths and (not source or source in skipped):
                    text = "%s（%s）" % (path, heading)
                    if source:
                        text += "替代 %s" % source
                    sections.append(text)
            if sections:
                rows.append("%s替代章节: %s。" % (display, "、".join(sections)))
        rows.append("")
    return "\n".join(rows).strip()


def hotfix_table(stages):
    rows = ["| 阶段 | 工作 | 负责人 |", "|---|---|---|"]
    for stage in stages:
        rows.append("| %s %s | %s | %s |" % (
            stage.get("id", ""),
            stage.get("label", ""),
            stage.get("work", ""),
            "、".join(teamdef.parse_list(stage.get("owners"))),
        ))
    return "\n".join(rows)


def hotfix_checks(items):
    rows = []
    for item in items:
        rows.append("- %s。" % item.rstrip("。"))
    return "\n".join(rows)


def readme_overview(data):
    rows = ["| 模式 | 适用条件 | 适用门 |", "|---|---|---|"]
    for mode_id, mode in data["modes"].items():
        gates = " → ".join(teamdef.mode_gate_ids(data, mode_id))
        rows.append("| %s | %s | %s |" % (mode["label"], mode["detect"], gates))
    return "\n".join(rows)


def render_role_cards(agents):
    documents = {}
    cards = {}
    metadata = []
    role_ids = {agent["id"] for agent in agents}
    for agent in agents:
        role = agent["id"]
        relative = Path(agent.get("card", ""))
        path = PACK / relative
        if relative.parent != Path("team") or relative.suffix != ".md" or not path.is_file():
            raise SystemExit("角色 %s 的角色卡路径无效: %s" % (role, relative))
        if role in cards or path in documents:
            raise SystemExit("重复登记角色或角色卡: %s" % role)
        if not all(agent.get(key) for key in ("title", "summary", "handoff")):
            raise SystemExit("角色缺少 title、summary 或 handoff: %s" % role)
        recipients = teamdef.parse_list(agent["handoff"])
        if recipients != ["all"] and (not recipients or set(recipients) - role_ids):
            raise SystemExit("角色 %s 有无效的交接对象" % role)
        meta = {
            "name": role,
            "description": "%s。%s" % (agent["title"], agent["summary"]),
            "handoff": "、".join(recipients),
        }
        body = teamdef.read_body(path)
        heading = "# %s（%s）" % (agent["title"], role)
        if body.startswith("# "):
            body = body.partition("\n")[2]
        front = "---\nname: %s\ndescription: %s\nhandoff: %s\n---" % (
            role, json.dumps(meta["description"], ensure_ascii=False), meta["handoff"])
        documents[path] = "%s\n\n%s\n\n%s" % (front, heading, body.lstrip("\n"))
        cards[role] = relative.as_posix()
        metadata.append((path, meta))
    return cards, metadata, documents


def replace_block(text, key, body):
    begin = "<!-- RENDER:%s:BEGIN -->" % key
    end = "<!-- RENDER:%s:END -->" % key
    if begin not in text or end not in text:
        raise SystemExit("缺少渲染标记: %s" % key)
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.S)
    replacement = "%s\n%s\n%s" % (begin, body, end)
    return pattern.sub(lambda _: replacement, text, count=1)


def build_documents():
    data = teamdef.parse_team_yaml(TEAM_YAML)
    if not data["version"]:
        raise SystemExit("team.yaml 缺少 version")
    cards, metadata, documents = render_role_cards(data["agents"])
    version = "当前版本 `%s`" % data["version"]
    bodies = {
        "VERSION": version,
        "RELEASE_HEADER": "%s · %d 个角色" % (version, len(data["agents"])),
        "README_OVERVIEW": readme_overview(data),
        "AGENTS_TEAM": team_table(data["agents"], cards),
        "AGENTS_STAGES": stage_table(data["stages"], data["gates"]),
        "AGENTS_STATE_MACHINE": state_machine(data["modes"]),
        "AGENTS_MODES": mode_rules(data["modes"]),
        "AGENTS_PROFILES": profile_table(data["profiles"]),
        "AGENTS_ROUTES": route_table(data["routes"]),
        "AGENTS_ARTIFACTS": artifact_table(
            data["artifacts"], data["optional_artifacts"], data["gates"],
            data["profiles"]),
        "PROTOCOL_GATES": gate_sections(data["gates"], data["profiles"]),
        "PROTOCOL_HOTFIX": hotfix_table(data["hotfix_stages"]),
        "PROTOCOL_HOTFIX_CHECKS": hotfix_checks(data["hotfix_checks"]),
        "PROJECT_STATE_GATES": project_gate_table(data["gates"]),
        "RULES_SUMMARY": "\n".join("- %s" % rule for rule in data["rule_summary"]),
    }
    for path, keys in BLOCKS.items():
        text = teamdef.read(path)
        for key in keys:
            text = replace_block(text, key, bodies[key])
        documents[path] = text
    if MARKETPLACE.is_file():
        marketplace = json.loads(teamdef.read(MARKETPLACE))
        plugin = next((item for item in marketplace["plugins"]
                       if item.get("name") == "sdlc-agent-team"), None)
        if plugin is None:
            raise SystemExit("插件市场缺少 sdlc-agent-team")
        plugin["version"] = data["version"]
        documents[MARKETPLACE] = json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n"
        filters = {agent["id"]: agent["tool_filter"] for agent in data["agents"]}
        entries = project_agent_entries("claude", PACK, metadata, filters, resource_prefix="")
        documents.update({PACK / path: text for path, text in entries.items()})
    return documents


def main():
    parser = argparse.ArgumentParser(description="从 team.yaml 生成文档区块")
    parser.add_argument("--check", action="store_true", help="只检查，不写文件")
    args = parser.parse_args()

    stale = []
    for path, text in build_documents().items():
        if path.is_file() and teamdef.read(path) == text:
            continue
        stale.append(path)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    if args.check:
        if stale:
            print("渲染区块过期:")
            for path in stale:
                print(" - %s" % path.relative_to(PACK))
            return 1
        print("渲染区块一致")
        return 0

    if stale:
        for path in stale:
            print("已更新: %s" % path.relative_to(PACK))
    else:
        print("渲染区块无需更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
