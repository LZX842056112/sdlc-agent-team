#!/usr/bin/env python3
"""校验专家团定义的一致性。

检查项:
1. 角色卡与 team.yaml 的角色、数量一致。
2. 每张角色卡有必需章节。
3. 文档表格与 team.yaml 一致，无渲染漂移。
4. 工件、模板、门、模式和批准配置可解析。
5. README、角色卡头部和平台入口与注册表一致。
6. 状态板模板不含示例数据，并包含关键说明。
7. 门负责人不等于工件负责人。
8. 插件、Trae Skill、WorkBuddy 副本与源一致。`--source-only` 跳过外部副本。
9. 版本号与角色数量在所有入口一致。
"""

import argparse
import json
import re
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import render
import teamdef
import gates
from install import (
    CORE_DIR, CORE_DIRS, CORE_FILES, INSTALLERS, packaged_cards,
    plugin_entries, plugin_file_hash, plugin_managed_paths, plugin_ownership,
)

TEAM_DIR = PACK / "team"
TEAM_YAML = PACK / "team.yaml"
CLAUDE_AGENTS = PACK / ".claude" / "agents"
REQUIRED_SECTIONS = ["## 使命", "## 输入", "## 工作步骤", "## 输出", "## 完成标准", "## 边界", "## 交接"]
HUMAN_OWNERS = teamdef.HUMAN_GATE_OWNERS
SPECIAL_OWNERS = set(teamdef.OWNER_LABELS)
PHASE_LABELS = {"REQ", "DESIGN", "BUILD", "TEST", "RELEASE", "OPS", "RETRO"}
APPROVAL_RULES = gates.APPROVAL_RULES

errors = []


def fail(message):
    errors.append(message)


def read(path):
    return path.read_text(encoding="utf-8")


def compare_tree(src, dst, label):
    if not dst.exists():
        fail("%s 缺少目录: %s" % (label, dst))
        return
    for source in src.rglob("*"):
        if source.is_dir() or "__pycache__" in source.parts:
            continue
        target = dst / source.relative_to(src)
        if not target.exists():
            fail("%s 缺少文件: %s" % (label, source.relative_to(src)))
        elif source.read_bytes() != target.read_bytes():
            fail("%s 内容漂移: %s" % (label, source.relative_to(src)))


def check_copy(base, label, files=CORE_FILES, dirs=CORE_DIRS):
    if not base.exists():
        return
    for name in files:
        source = PACK / name
        target = base / name
        if not target.exists():
            fail("%s 缺少文件: %s" % (label, name))
        elif source.read_bytes() != target.read_bytes():
            fail("%s 内容漂移: %s" % (label, name))
    for name in dirs:
        compare_tree(PACK / name, base / name, label)


def check_plugin_ownership(plugin_dir, entries):
    try:
        files, _ = plugin_ownership(plugin_dir)
    except SystemExit as exc:
        fail("插件归属清单无效: %s" % exc)
        return
    if files is None:
        fail("插件缺少归属清单")
        return

    paths = {path.as_posix(): path for path in plugin_managed_paths(PACK, entries)}
    for name, relative in sorted(paths.items()):
        path = plugin_dir / relative
        if name not in files:
            fail("插件归属清单缺少: %s" % name)
        elif not path.is_file():
            fail("插件归属清单引用的文件缺失: %s" % name)
        elif plugin_file_hash(path) != files[name]:
            fail("插件归属清单摘要不一致: %s" % name)
    for name in sorted(files.keys() - paths.keys()):
        fail("插件归属清单多出: %s" % name)


def check_plugin(plugin_dir, filters, version):
    manifest = json.loads(read(plugin_dir / ".claude-plugin" / "plugin.json"))
    if manifest.get("version") != version:
        fail("插件版本 %s 与 AGENTS.md %s 不一致" % (manifest.get("version"), version))
    if {"agents", "skills", "commands"} & manifest.keys():
        fail("插件使用默认的 agents 和 skills 目录")
    entries = plugin_entries(packaged_cards(PACK), filters)
    check_plugin_ownership(plugin_dir, entries)
    actual = {path.relative_to(plugin_dir)
              for pattern in ("agents/**/*.md", "skills/*/SKILL.md")
              for path in plugin_dir.glob(pattern) if path.is_file()}
    for path, expected in entries.items():
        if path not in actual:
            fail("插件缺少入口: %s，请重跑 --build-plugin" % path.as_posix())
        elif read(plugin_dir / path) != expected:
            fail("插件入口内容漂移: %s，请重跑 --build-plugin" % path.as_posix())
    for path in sorted(actual - entries.keys()):
        fail("插件存在多余入口: %s，请重跑 --build-plugin" % path.as_posix())
    if list((plugin_dir / "commands").glob("*.md")):
        fail("插件含重复的命令入口，请重跑 --build-plugin")
    core = plugin_dir / CORE_DIR
    if core.is_dir():
        check_copy(core, "插件")
    else:
        fail("插件缺少目录: %s" % core)


def check_rendered():
    try:
        documents = render.build_documents()
    except SystemExit as exc:
        fail("渲染检查失败: %s" % exc)
        return
    for path, expected in documents.items():
        if not path.is_file() or read(path) != expected:
            fail("%s 生成内容缺失或过期，请运行 python bin/render.py" % path.relative_to(PACK))


def template_index():
    rows = []
    for line in read(PACK / "templates" / "README.md").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or cells[0] in ("模板", "") or set(cells[0]) <= set("-"):
            continue
        rows.append(cells)
    return rows


def check_templates(artifacts):
    files = sorted(
        path.name for path in (PACK / "templates").glob("*.md")
        if path.name != "README.md")
    rows = template_index()
    listed = [row[0] for row in rows]
    if sorted(listed) != files:
        missing = sorted(set(files) - set(listed))
        extra = sorted(set(listed) - set(files))
        if missing:
            fail("templates/README.md 缺少模板: %s" % ", ".join(missing))
        if extra:
            fail("templates/README.md 列出不存在的模板: %s" % ", ".join(extra))
    for row in rows:
        if len(row) < 3:
            fail("templates/README.md 行缺少对应工件: %s" % row[0])
            continue
        for item in re.split(r"[、,，]", row[2]):
            item = item.strip()
            if item and item not in artifacts:
                fail("模板 %s 对应的工件不存在: %s" % (row[0], item))


def check_state_template():
    text = read(PACK / "templates" / "PROJECT_STATE.md")
    if "## 评审分工" not in text:
        fail("PROJECT_STATE.md 缺少评审分工章节")
    if "## 人工确认" not in text:
        fail("PROJECT_STATE.md 缺少人工确认章节")
    if "模式判定或切换时填写" not in text:
        fail("PROJECT_STATE.md 缺少模式历史填写说明")
    if "后端: 待判定" not in text:
        fail("PROJECT_STATE.md 缺少后端字段")
    if "`后端` 表示本次变更是否涉及后端" not in text:
        fail("PROJECT_STATE.md 缺少后端字段说明")
    if "规模: 标准" not in text:
        fail("PROJECT_STATE.md 缺少规模字段")
    if "`规模` 表示项目配置" not in text:
        fail("PROJECT_STATE.md 缺少规模字段说明")
    if "`DONE` 只表示本模式流程结束" not in text:
        fail("PROJECT_STATE.md 缺少 DONE 语义说明")
    if re.search(r"^门[:：]", text, re.M):
        fail("PROJECT_STATE.md 应从门禁表计算通过数")
    if "脚本检查本表的确认人、时间和结论" not in text:
        fail("PROJECT_STATE.md 缺少人工确认脚本说明")
    if "| 1 | | | | | | BLOCKED |" in text:
        fail("PROJECT_STATE.md 仍含示例阻塞项")
    if "| docs/01-requirements.md | DRAFT |" in text:
        fail("PROJECT_STATE.md 仍含示例产出物")
    if "| 1 | | | | | |" in text:
        fail("PROJECT_STATE.md 仍含示例并行任务")


def check_profiles(profiles, agents, artifacts):
    """检查规模配置的角色、跳过工件和替代章节。"""
    agent_ids = {agent.get("id") for agent in agents}
    if "standard" not in profiles:
        fail("缺少 standard 规模配置")
    if "small" not in profiles:
        fail("缺少 small 规模配置")
    for key, profile in profiles.items():
        if not profile.get("label"):
            fail("规模配置 %s 缺少 label" % key)
        merges = teamdef.parse_pairs(profile.get("owner_aliases", ""))
        covered_all = []
        for primary, covered in merges.items():
            if primary not in agent_ids:
                fail("规模 %s 的合并主角色不存在: %s" % (key, primary))
            if primary in ("reviewer", "orchestrator"):
                fail("规模 %s 不能合并评审或总控: %s" % (key, primary))
            for role in covered:
                if role not in agent_ids:
                    fail("规模 %s 的合并角色不存在: %s" % (key, role))
                if role in ("reviewer", "orchestrator"):
                    fail("规模 %s 不能合并评审或总控: %s" % (key, role))
                if role == primary:
                    fail("规模 %s 的角色不能合并到自身: %s" % (key, role))
                if role in covered_all:
                    fail("规模 %s 的角色被重复合并: %s" % (key, role))
                covered_all.append(role)
        skipped = teamdef.parse_list(profile.get("skip_artifacts", ""))
        for path in skipped:
            if path not in artifacts:
                fail("规模 %s 跳过未登记工件: %s" % (key, path))
        for source, targets in teamdef.parse_pairs(
                profile.get("replace_artifacts", "")).items():
            if source not in artifacts:
                fail("规模 %s 合并源工件不存在: %s" % (key, source))
            if not targets:
                fail("规模 %s 的合并目标为空: %s" % (key, source))
            for target in targets:
                if target not in artifacts:
                    fail("规模 %s 合并目标工件不存在: %s" % (key, target))
        for target, source, heading in teamdef.profile_sections(profile):
            if target not in artifacts:
                fail("规模 %s 的替代章节工件不存在: %s" % (key, target))
            if not heading:
                fail("规模 %s 的替代章节为空: %s" % (key, target))
            if source and source not in skipped:
                fail("规模 %s 的替代章节源工件未列入 skip_artifacts: %s" % (key, source))


def check_content_rules():
    """门禁关键词必须存在于对应模板。"""
    mapping = {}
    for row in template_index():
        if len(row) < 3:
            continue
        for item in re.split(r"[、,，]", row[2]):
            item = item.strip()
            if item:
                mapping[item] = row[0]
    for artifact, keywords in gates.CONTENT_RULES.items():
        template = mapping.get(artifact)
        if not template:
            fail("门禁内容规则缺少模板: %s" % artifact)
            continue
        text = read(PACK / "templates" / template)
        for keyword in keywords:
            if keyword not in text:
                fail("模板 %s 缺少门禁关键词: %s" % (template, keyword))


def main():
    parser = argparse.ArgumentParser(description="校验专家团定义的一致性")
    parser.add_argument("--source-only", action="store_true",
                        help="只校验源码，跳过 Trae Skill 和 WorkBuddy 外部副本")
    args = parser.parse_args()
    cards = sorted(TEAM_DIR.glob("*.md"))
    card_names = {}
    for card in cards:
        meta = teamdef.parse_front(card)
        name = meta.get("name")
        if not name:
            fail("角色卡缺少 name: %s" % card.name)
            continue
        if name in card_names:
            fail("角色名重复: %s" % name)
        card_names[name] = card
        text = read(card)
        for section in REQUIRED_SECTIONS:
            if section not in text:
                fail("%s 缺少章节: %s" % (card.name, section))
        if "最多 2 轮" in text:
            fail("%s 硬编码返工上限，请引用 team.yaml 的 rework_limit" % (
                card.name))

    data = teamdef.parse_team_yaml(TEAM_YAML)
    agents, gates, artifacts = data["agents"], data["gates"], data["artifacts"]
    check_profiles(data.get("profiles", {}), agents, artifacts)
    filters = {agent.get("id"): agent.get("tool_filter", "")
               for agent in agents}
    yaml_ids = [agent.get("id") for agent in agents]

    if len(cards) != len(yaml_ids):
        fail("角色卡数量 %d 与 team.yaml %d 不一致" % (len(cards), len(yaml_ids)))
    if set(card_names) != set(yaml_ids):
        fail("角色卡与 team.yaml 的角色名不一致")
    known = set(yaml_ids)
    for path, owner in artifacts.items():
        if owner not in known and owner not in SPECIAL_OWNERS:
            fail("工件 %s 的负责人不存在: %s" % (path, owner))

    for agent in agents:
        if not agent.get("tool_filter"):
            fail("team.yaml 角色缺少 tool_filter: %s" % agent.get("id"))
    optional = set(data["optional_artifacts"])
    for agent in agents:
        agent_id = agent.get("id", "")
        owned = [path for path, owner in artifacts.items()
                 if owner == agent_id and path not in optional]
        if owned and "Write" not in teamdef.claude_tools(
                filters.get(agent_id, "")):
            fail("角色 %s 拥有工件，但工具权限不能写: %s" % (
                agent_id, "、".join(owned)))
    for key, mode in data["modes"].items():
        if not mode.get("label") or not mode.get("detect"):
            fail("team.yaml 模式缺少 label 或 detect: %s" % key)
        if not teamdef.parse_list(mode.get("stages")):
            fail("team.yaml 模式缺少 stages: %s" % key)

    monitoring = data["monitoring"]
    if not monitoring.get("flow_state"):
        fail("team.yaml monitoring 缺少 flow_state")
    try:
        if float(monitoring.get("refresh_seconds", "0")) <= 0:
            fail("team.yaml monitoring.refresh_seconds 必须大于 0")
    except ValueError:
        fail("team.yaml monitoring.refresh_seconds 不是数字")
    try:
        if int(data["rules"].get("rework_limit", "0")) < 1:
            fail("team.yaml rules.rework_limit 必须是正整数")
    except ValueError:
        fail("team.yaml rules.rework_limit 不是数字")

    gate_ids = {gate.get("id") for gate in gates}
    stage_ids = [stage.get("id") for stage in data["stages"]]
    if len(stage_ids) != len(set(stage_ids)):
        fail("team.yaml 阶段 ID 重复")
    stage_id_set = set(stage_ids)
    hotfix_ids = [stage.get("id") for stage in data["hotfix_stages"]]
    if not hotfix_ids:
        fail("team.yaml 缺少 hotfix_stages")
    if len(hotfix_ids) != len(set(hotfix_ids)):
        fail("team.yaml 热修阶段 ID 重复")
    hotfix_id_set = set(hotfix_ids)
    hotfix_mode_stages = set(teamdef.parse_list(
        data["modes"].get("hotfix", {}).get("stages")))
    for stage in data["hotfix_stages"]:
        for owner in teamdef.parse_list(stage.get("owners")):
            if owner not in known:
                fail("热修阶段 %s 的负责人不存在: %s" % (
                    stage.get("id"), owner))
    if not data["hotfix_checks"]:
        fail("team.yaml 缺少 hotfix_checks")
    for stage in data["mode_base_stages"]:
        if (stage not in stage_id_set and stage not in gate_ids
                and stage not in PHASE_LABELS):
            fail("mode_base_stages 含未知阶段: %s" % stage)
    for mode_key, mode in data["modes"].items():
        if not teamdef.mode_gate_ids(data, mode_key):
            fail("模式 %s 没有适用门" % mode_key)
        for stage in teamdef.parse_list(mode.get("prefix_stages")):
            if (stage not in stage_id_set and stage not in gate_ids
                    and stage not in PHASE_LABELS):
                fail("模式 %s 的入口阶段不存在: %s" % (mode_key, stage))
        for stage in teamdef.parse_list(mode.get("stages")):
            if stage.startswith("H"):
                if stage not in hotfix_id_set:
                    fail("模式 %s 的热修阶段未登记: %s" % (mode_key, stage))
            elif (stage not in stage_id_set and stage not in gate_ids
                    and stage not in PHASE_LABELS):
                fail("模式 %s 的阶段不存在: %s" % (mode_key, stage))
    for agent in agents:
        stage_value = agent.get("stage", "")
        if stage_value != "all":
            for stage in teamdef.parse_list(stage_value):
                if stage not in stage_id_set:
                    fail("角色 %s 的阶段不存在: %s" % (
                        agent.get("id"), stage))
        label = agent.get("stage_label", "")
        expected_hotfix = set(teamdef.parse_list(agent.get("hotfix_stage")))
        for stage in expected_hotfix:
            if stage not in hotfix_mode_stages:
                fail("角色 %s 的热修阶段不存在: %s" % (
                    agent.get("id"), stage))
            elif stage not in label:
                fail("角色 %s 的热修阶段未写入 stage_label: %s" % (
                    agent.get("id"), stage))
        extra = set(re.findall(r"H\d+", label)) - expected_hotfix
        if extra:
            fail("角色 %s 的 stage_label 含未登记的热修阶段: %s" % (
                agent.get("id"), "、".join(sorted(extra))))
        for gate_id in teamdef.parse_list(agent.get("gate")):
            if gate_id not in gate_ids:
                fail("角色 %s 的门不存在: %s" % (
                    agent.get("id"), gate_id))
    for stage in data["stages"]:
        if stage.get("gate") not in gate_ids:
            fail("阶段 %s 的门不存在: %s" % (
                stage.get("id"), stage.get("gate")))
        for owner in teamdef.parse_list(stage.get("owners")):
            if owner not in known:
                fail("阶段 %s 的负责人不存在: %s" % (
                    stage.get("id"), owner))
    routed = set()
    for route in data["routes"]:
        target = route.get("agent", "")
        roles = known.intersection(re.findall(r"[A-Za-z0-9_-]+", target))
        if not roles:
            fail("路由目标不存在: %s" % target)
        routed.update(roles)
    for name in sorted(card_names.keys() - routed):
        fail("team.yaml 路由缺少角色: %s" % name)

    rules = data["rule_summary"]
    if not rules:
        fail("team.yaml 的规则摘要为空")

    if not args.source_only:
        check_copy(
            Path.home() / ".trae-cn" / "skills" / "sdlc-agent-team", "Trae Skill",
            files=teamdef.SKILL_FILES, dirs=teamdef.SKILL_DIRS)
        check_copy(
            Path.home() / ".workbuddy" / "skills" / "sdlc-agent-team" / "references",
            "WorkBuddy")
    check_rendered()

    for gate in gates:
        gate_id = gate.get("id", "?")
        gate_owner = gate.get("gate_owner", "")
        if not gate_owner:
            fail("%s 缺少门负责人" % gate_id)
        owners = []
        for key in teamdef.GATE_ARTIFACT_KEYS:
            for path in teamdef.parse_list(gate.get(key)):
                if path.startswith("docs/review-"):
                    continue
                owner = artifacts.get(path, "")
                if not owner:
                    fail("%s 的工件没有负责人: %s" % (gate_id, path))
                elif owner not in known and owner not in HUMAN_OWNERS:
                    fail("%s 的工件负责人不存在: %s" % (gate_id, owner))
                elif owner not in owners:
                    owners.append(owner)
        if gate_owner in owners:
            fail("%s 的门负责人与工件负责人相同: %s" % (gate_id, gate_owner))

    gates_by_id = {gate.get("id"): gate for gate in gates}
    for gate_id in teamdef.parse_list(
            data["rules"].get("human_approval_required")):
        gate = gates_by_id.get(gate_id)
        if gate is None:
            fail("human_approval_required 的门不存在: %s" % gate_id)
        elif gate.get("gate_owner") not in HUMAN_OWNERS:
            fail("%s 必须由人批准，当前门负责人: %s" % (
                gate_id, gate.get("gate_owner", "")))
        if gate is not None:
            fields = teamdef.parse_list(gate.get("approval_fields"))
            path = gate.get("approval_artifact", "")
            rule = gate.get("approval_rule", "")
            scope_field = gate.get("approval_scope_field", "")
            text_field = gate.get("approval_text_field", "")
            if not scope_field or not text_field or not {
                    "批准人", "批准时间", scope_field, text_field}.issubset(fields):
                fail("%s 的 approval_fields 必须包含批准人、时间、范围和原文" % gate_id)
            if rule not in APPROVAL_RULES:
                fail("%s 的 approval_rule 无效: %s。允许值: %s" % (
                    gate_id, rule, "、".join(sorted(APPROVAL_RULES))))
            if path not in artifacts or path not in teamdef.parse_list(gate.get("artifacts")):
                fail("%s 的批准工件必须是必需工件: %s" % (gate_id, path))

    expected_wrappers = {"sdlc-%s" % name for name in card_names}
    actual_wrappers = {path.stem for path in CLAUDE_AGENTS.glob("*.md")}
    if expected_wrappers != actual_wrappers:
        missing = expected_wrappers - actual_wrappers
        extra = actual_wrappers - expected_wrappers
        if missing:
            fail("Claude 缺少子 Agent: %s" % ", ".join(sorted(missing)))
        if extra:
            fail("Claude 存在多余子 Agent: %s" % ", ".join(sorted(extra)))
    check_templates(artifacts)
    check_content_rules()
    check_state_template()

    for name in ("flow.py", "dashboard.py", "dashboard.html", "teamdef.py",
                 "gates.py", "audit.py"):
        if not (PACK / "tools" / name).exists():
            fail("缺少工具: tools/%s" % name)

    if "/api/meta" not in read(PACK / "tools" / "dashboard.html"):
        fail("dashboard.html 未从 /api/meta 读取团队定义")

    platforms_text = read(PACK / "PLATFORMS.md")
    for name in INSTALLERS:
        if "| %s |" % name not in platforms_text:
            fail("PLATFORMS.md 缺少平台 ID: %s" % name)

    for gate in gates:
        if not gate.get("checks"):
            fail("门禁检查项缺失: %s 没有检查项" % gate.get("id"))
        gate_artifacts = teamdef.parse_list(gate.get("artifacts"))
        if not gate_artifacts:
            fail("门禁缺少必需工件: %s" % gate.get("id"))
        for key in teamdef.GATE_ARTIFACT_KEYS:
            for path in teamdef.parse_list(gate.get(key)):
                if path not in artifacts:
                    fail("门禁 %s 的工件未登记: %s" % (gate.get("id"), path))

    version = data["version"]
    if not version:
        fail("team.yaml 缺少版本号")
    else:
        plugin_dir = PACK / "plugins" / "sdlc-agent-team"
        if plugin_dir.exists():
            check_plugin(plugin_dir, filters, version)

    if errors:
        print("校验失败:")
        for message in errors:
            print(" - %s" % message)
        return 1

    print("校验通过: %d 个角色, %d 个门, %d 个工件" % (
        len(cards), len(gates), len(artifacts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
