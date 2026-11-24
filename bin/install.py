#!/usr/bin/env python3
"""把软件交付专家团安装到目标项目。

用法:
    python bin/install.py --platform all --target <项目>
    python bin/install.py --platform trae --target .
    python bin/install.py --platform claude --target D:/work/demo
    python bin/install.py --build-plugin plugins/sdlc-agent-team
    python bin/install.py --install-skill
    python bin/install.py --install-workbuddy
    python bin/install.py --list

平台: claude | codex | trae | cursor | workbuddy | dsh | generic | all
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "tools"))

import teamdef
from teamdef import CORE_DIRS, CORE_FILES, RUNTIME_DIRS, RUNTIME_FILES

CORE_DIR = "sdlc-agent-team"
TEAM = teamdef.parse_team_yaml()
VERSION = TEAM["version"]
MODE_LABELS = "、".join(mode["label"] for mode in TEAM["modes"].values())
SOURCE_CARDS = {Path("team") / card.name: meta
                for card, meta in teamdef.role_cards(PACK / "team").values()}
ROLE_COUNT = len(SOURCE_CARDS)
MARK_BEGIN = "<!-- sdlc-agent-team:begin -->"
MARK_END = "<!-- sdlc-agent-team:end -->"
GITIGNORE_BEGIN = "# sdlc-agent-team:begin"
GITIGNORE_END = "# sdlc-agent-team:end"
INSTALL_MARKER = ".sdlc-agent-team-install"
PROJECT_INSTALL_KIND = "sdlc-agent-team project install"
INSTALL_MARKER_TEXT = PROJECT_INSTALL_KIND + "\n"
PLUGIN_INSTALL_KIND = "sdlc-agent-team claude plugin"
DSH_PRESET = "DSH_PRESETS.md"
DSH_PRESET_HEADING = "# DSH Agent Preset 配置"
WORKBUDDY_NAME = "软件交付专家团"
LEGACY_MODES = "新建、二次开发、迭代和热修"
GATE_LOOKUP = " 的“门禁办理”中对应门 ID 的完成标准。"

PACKAGE_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")
IGNORE = shutil.ignore_patterns(
    "bin", "__pycache__", "*.pyc", ".git", ".gitignore", "docs", ".claude",
    "dist", "plugins", ".claude-plugin", ".github", "install.sh",
    "SKILL.md",
)


def read_text(path):
    return path.read_text(encoding="utf-8")


def write_text(path, text):
    with teamdef.atomic_text_writer(path) as stream:
        stream.write(text)
    return path


def copy_tree(src, dst):
    """复制目录到暂存区。"""
    shutil.copytree(src, dst, ignore=PACKAGE_IGNORE)


def copy_package(dest, *, files=CORE_FILES, dirs=CORE_DIRS):
    """复制插件资源或暂存技能资源。"""
    dest.mkdir(parents=True, exist_ok=True)
    for name in files:
        shutil.copy2(PACK / name, dest / name)
    for name in dirs:
        copy_tree(PACK / name, dest / name)


def skill_document(base, front_matter):
    """生成技能入口正文。base 是 AGENTS.md 所在相对路径。"""
    return (
        f"{front_matter.strip()}\n\n"
        f"读 `{base}/AGENTS.md` 和 `{base}/team/00-orchestrator.md`。\n"
        "你是总控。先判定项目模式，再按门禁推进。\n"
        f"准备或检查当前门时，只读 `{base}/protocol.md` 的对应章节。\n"
        f"角色卡在 `{base}/team/`。\n"
    )


def block_lines(path, lines, begin, end):
    markers = []
    for index, line in enumerate(lines):
        label = line.rstrip("\r\n")
        if index == 0 and label.startswith("\ufeff"):
            label = label[1:]
        if label in (begin, end):
            markers.append((index, label))
    if not markers:
        return None
    if [label for _, label in markers] != [begin, end]:
        raise SystemExit("项目文件的安装标记须成对且唯一: %s" % path)
    return markers[0][0], markers[1][0]


def plan_block(path, block, begin=MARK_BEGIN, end=MARK_END, *, replace_only=False):
    """只改标记区块，并保留项目文件的其他内容。"""
    check_install_path(path)
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    lines = text.splitlines(keepends=True)
    span = block_lines(path, lines, begin, end)
    newline = "\r\n" if "\r\n" in text else "\n"
    if span is not None:
        first, last = span
        if lines[first].endswith("\n"):
            newline = "\r\n" if lines[first].endswith("\r\n") else "\n"
        prefix = "".join(lines[:first]) + ("\ufeff" if first == 0 and text.startswith("\ufeff") else "")
        suffix = lines[last][len(end):] + "".join(lines[last + 1:])
    elif replace_only:
        return None
    else:
        prefix = text
        if text and text != "\ufeff":
            prefix += newline if text.endswith("\n") else newline * 2
        suffix = newline
    body = newline.join((begin, block.strip().replace("\n", newline), end))
    updated = prefix + body + suffix
    return updated if updated != text else None


def ensure_target(target):
    """拒绝源目录和源目录的子目录，避免覆盖或嵌套复制。"""
    if target == PACK or PACK in target.parents:
        raise SystemExit("目标目录不能是专家团源目录或其子目录: %s" % target)


def check_install_path(path, *, directory=False):
    """拒绝链接、目录联接和类型冲突。"""
    matches = path.is_dir() if directory else path.is_file()
    if path.is_symlink() or path.resolve() != path or (path.exists() and not matches):
        raise SystemExit("安装路径冲突: %s" % path)


def check_relative_file(root, relative):
    for parent in reversed(relative.parents):
        if parent.parts:
            check_install_path(root / parent, directory=True)
    check_install_path(root / relative)


def matches_generated(path, *versions):
    try:
        return read_text(path) in versions
    except UnicodeError:
        return False


def has_team_identity(dest):
    rules = dest / "AGENTS.md"
    definition = dest / "team.yaml"
    for path in (rules, definition):
        check_install_path(path)
    return (
        f"name: {CORE_DIR}" in read_text(definition).splitlines()
        and read_text(rules).startswith("# 软件交付专家团（SDLC Agent Team）\n")
    )


def project_marker(dest):
    marker = dest / INSTALL_MARKER
    check_install_path(marker)
    if not marker.exists():
        return None
    content = read_text(marker)
    if content == INSTALL_MARKER_TEXT:
        return {}
    record = json.loads(content)
    if (not isinstance(record, dict) or record.get("kind") != PROJECT_INSTALL_KIND
            or not isinstance(record.get("entries"), dict)):
        raise ValueError("项目安装标记格式错误")
    return record["entries"]


def is_managed_core(target, dest):
    try:
        if project_marker(dest) is not None:
            return True

        # 旧版在项目 .gitignore 中写标记，在核心目录内写团队定义。
        ignore = target / ".gitignore"
        check_install_path(ignore)
        return (
            block_lines(ignore, read_text(ignore).splitlines(), GITIGNORE_BEGIN, GITIGNORE_END) is not None
            and has_team_identity(dest)
        )
    except (OSError, ValueError):
        return False


def check_core_destination(target, *, include_dsh):
    dest = target / CORE_DIR
    check_install_path(dest, directory=True)
    if dest.exists() and not is_managed_core(target, dest):
        raise SystemExit("已有同名目录，无法确认由安装器创建: %s" % dest)
    if include_dsh:
        preset = dest / DSH_PRESET
        check_install_path(preset)
        if preset.exists():
            with preset.open("rb") as old_preset:
                heading = old_preset.readline().rstrip(b"\r\n")
            if heading != DSH_PRESET_HEADING.encode("utf-8"):
                raise SystemExit("已有 DSH 配置，无法确认由安装器创建: %s" % preset)
    return dest


def copy_core(target, *, include_dsh=False, marker_text=INSTALL_MARKER_TEXT):
    dest = check_core_destination(target, include_dsh=include_dsh)
    upgrade = dest.exists()
    with tempfile.TemporaryDirectory(prefix=f".{CORE_DIR}-", dir=target) as tmp:
        staged = Path(tmp) / CORE_DIR
        staged.mkdir()
        for name in CORE_FILES:
            shutil.copy2(PACK / name, staged / name)
        for name in CORE_DIRS:
            shutil.copytree(PACK / name, staged / name, ignore=IGNORE)
        if include_dsh:
            write_text(staged / DSH_PRESET, dsh_presets())
        return apply_staged_install(staged, dest, marker_text, upgrade=upgrade)


def apply_staged_install(staged, dest, marker_text, *, upgrade, remove=()):
    """只更新打包文件。写入失败时恢复原文件。"""
    paths = sorted(staged.rglob("*"))
    paths.append(write_text(staged / INSTALL_MARKER, marker_text))
    check_install_path(dest, directory=True)
    if upgrade != dest.exists():
        raise SystemExit("安装期间目标目录发生变化: %s" % dest)
    if not upgrade:
        staged.rename(dest)
        return dest

    changed = []
    for source in paths:
        path = dest / source.relative_to(staged)
        check_install_path(path, directory=source.is_dir())
        if not path.exists() or (source.is_file() and source.read_bytes() != path.read_bytes()):
            changed.append(source)
    for relative in remove:
        check_relative_file(dest, relative)
    if not changed and not remove:
        return dest

    files = [source.relative_to(staged) for source in changed if source.is_file()]
    backup = staged.parent / "previous"
    backup.mkdir()
    for relative in (*files, *remove):
        path = dest / relative
        if path.exists():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)

    applied = []
    created_dirs = []
    try:
        for relative in remove:
            path = dest / relative
            path.unlink()
            applied.append(path)
        for source in changed:
            path = dest / source.relative_to(staged)
            if source.is_dir():
                if not path.exists():
                    path.mkdir()
                    created_dirs.append(path)
            else:
                source.replace(path)
                applied.append(path)
    except OSError:
        try:
            for path in reversed(applied):
                saved = backup / path.relative_to(dest)
                if saved.exists():
                    saved.replace(path)
                else:
                    path.unlink()
            for path in reversed(created_dirs):
                path.rmdir()
        except OSError as error:
            recovery_dir = Path(tempfile.mkdtemp(prefix=f".{CORE_DIR}-backup-", dir=dest.parent))
            recovery = backup.rename(recovery_dir / CORE_DIR)
            raise SystemExit("恢复安装失败。请保留备份目录: %s" % recovery) from error
        raise
    parents = {parent for path in remove for parent in path.parents if parent.parts}
    for relative in sorted(parents, key=lambda path: len(path.parts), reverse=True):
        # 只清理空目录。目录中可能有用户文件。
        try:
            (dest / relative).rmdir()
        except OSError:
            pass
    return dest


def init_docs(target):
    docs = target / "docs"
    (docs / "cr").mkdir(parents=True, exist_ok=True)
    state = docs / "status.md"
    if state.exists():
        return
    text = read_text(PACK / "templates" / "PROJECT_STATE.md")
    text = re.sub(r"^模式[:：][^\n]*", "模式: 未判定", text, count=1, flags=re.M)
    text = text.replace(
        "更新时间: YYYY-MM-DD", "更新时间: %s" % date.today().isoformat())
    text = re.sub(r"^<!-- RENDER:.*?-->\s*$", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    write_text(state, text)


def platform_block(count=ROLE_COUNT, modes=MODE_LABELS):
    when = f"启动{modes}流程时" if modes else "新建、二次开发、迭代或热修时"
    return (
        "本项目使用 `%s/` 中的 %d 个 Agent 团队。\n"
        "%s，先读 `%s/AGENTS.md` "
        "和 `%s/team/00-orchestrator.md`。\n"
        "总控先判定模式，再按门禁推进。\n" % (
            CORE_DIR, count, when, CORE_DIR, CORE_DIR))


def claude_project_block():
    return """
## 软件交付专家团

本项目的团队定义在 `%s/`。
启动交付流程时，主 Agent 读 `%s/AGENTS.md` 和 `%s/team/00-orchestrator.md`。
准备或检查当前门时，只读 `%s/protocol.md` 的对应章节。
`.claude/agents/` 提供 %d 个薄壳子 Agent。
""" % (CORE_DIR, CORE_DIR, CORE_DIR, CORE_DIR, ROLE_COUNT)


def project_blocks(target, chosen, *, replace_only):
    ignore = ("docs/flow.json\ndocs/.flow.json.lock\ndocs/.status.md.lock\n"
              "docs/.flow.json.*.tmp\ndocs/status.md.bak\n__pycache__/\n")
    blocks = {target / ".gitignore": plan_block(
        target / ".gitignore", ignore, GITIGNORE_BEGIN, GITIGNORE_END)}
    agents = target / "AGENTS.md"
    blocks[agents] = plan_block(agents, "## 软件交付专家团\n\n" + platform_block(),
                                replace_only=replace_only)
    if "claude" in chosen:
        path = target / "CLAUDE.md"
        blocks[path] = plan_block(path, claude_project_block())
    return blocks


def packaged_cards(core):
    cards = []
    for relative, source_meta in sorted(SOURCE_CARDS.items()):
        path = core / relative
        check_relative_file(core, relative)
        if path.exists():
            meta = source_meta if core == PACK else teamdef.parse_front(path)
            cards.append((path, meta))
    return cards


def project_agent_entries(platform, core, cards, filters, *, legacy=False,
                          resource_prefix=f"{CORE_DIR}/"):
    entries = {}
    out = Path(f".{platform}") / "agents"
    protocol = f"{resource_prefix}protocol.md"
    for card, meta in cards:
        role = meta.get("name")
        if not role or (platform == "trae" and role == "orchestrator"):
            continue
        name = f"sdlc-{role}"
        description = meta.get("description", role)
        tools = teamdef.claude_tools(filters.get(role, ""))
        card_path = resource_prefix + card.relative_to(core).as_posix()
        if legacy:
            body = (
                f"读 `{resource_prefix}AGENTS.md` 和 `{protocol}`。\n"
                f"读 `{card_path}`。\n"
                "严格按角色卡执行。不要超出边界。\n"
            )
        else:
            description = json.dumps(description, ensure_ascii=False)
            body = (
                f"读 `{card_path}`。按角色卡执行任务单。\n"
                f"如果任务单未写完成标准，只读 `{protocol}`{GATE_LOOKUP}\n"
            )
        entries[out / f"{name}.md"] = (
            f"---\nname: {name}\ndescription: {description}\ntools: {tools}\n---\n\n{body}"
        )
    return entries


TRAE_RULE = """---
alwaysApply: false
---

在内置 Agent 中选择 `/sdlc-agent-team` 技能，启动软件交付专家团。
"""
TRAE_GUIDANCE = (
    "在内置 Agent 中执行总控流程。\n"
    "调用 `.trae/agents/` 中的 `sdlc-<角色 ID>` 子 Agent 来执行专责任务。\n"
    "无法调用子 Agent 时，主 Agent 每次只按本次任务的角色卡执行。\n"
)


def project_entry_contents(core, data, cards, *, legacy=False):
    entries = {}
    count = len(data["agents"]) or ROLE_COUNT
    modes = "、".join(mode["label"] for mode in data["modes"].values())
    filters = {agent["id"]: agent.get("tool_filter", "") for agent in data["agents"]}
    rule_header = "---\ndescription: 软件交付专家团入口\n"
    rule_body = "alwaysApply: true\n---\n" + platform_block(count, "" if legacy else modes)
    for platform in PLATFORMS:
        if platform in ("claude", "trae"):
            entries.update(project_agent_entries(platform, core, cards, filters, legacy=legacy))
        if platform == "trae":
            rule = rule_header + 'globs: ["**/*"]\n' + rule_body if legacy else TRAE_RULE
            entries[Path(".trae/rules/sdlc-agent-team.md")] = rule
        if platform == "cursor":
            entries[Path(".cursor/rules/sdlc-agent-team.mdc")] = rule_header + rule_body
        if platform in ("trae", "workbuddy", "dsh"):
            directory = ".agents" if platform == "dsh" else f".{platform}"
            guidance = TRAE_GUIDANCE if platform == "trae" and not legacy else ""
            entries[Path(directory) / "skills" / CORE_DIR / "SKILL.md"] = project_skill(
                count, modes, guidance, legacy=legacy)
    return entries


def install_workbuddy_global():
    """安装为 WorkBuddy 全局技能，自带 references，避免相对路径失效。"""
    return install_native_skill(".workbuddy")


def read_workbuddy_json(path):
    check_install_path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise SystemExit("无法读取 WorkBuddy 元数据: %s" % path) from error
    if not isinstance(data, dict):
        raise SystemExit("WorkBuddy 元数据必须为 JSON 对象: %s" % path)
    return data


def write_workbuddy_skill(staged, installed):
    desc_zh = "%d 个 Agent 按 8 个主阶段交付软件，支持%s。" % (ROLE_COUNT, MODE_LABELS)
    desc_en = "A %d-agent SDLC team with gates, reviews, release and retrospective." % ROLE_COUNT
    name_zh = WORKBUDDY_NAME
    name_en = "SDLC Agent Team"
    front = """---
name: sdlc-agent-team
display_name: %s
display_name_zh: %s
display_name_en: %s
description: %s
description_zh: %s
description_en: %s
version: %s
---""" % (name_zh, name_zh, name_en, desc_zh, desc_zh, desc_en, VERSION)
    skill = skill_document("references", front)
    skill += "模板在 `references/templates/`，监控工具在 `references/tools/`。\n"
    write_text(staged / "SKILL.md", skill)
    descriptions = {"description_zh": desc_zh, "description_en": desc_en}
    registration = {
        "display_name": name_zh,
        "display_name_en": name_en,
        **read_workbuddy_json(installed / "workbuddy.json"),
        **descriptions,
    }
    metadata = {
        "name": name_zh,
        "display_name": name_zh,
        "display_name_en": name_en,
        "installedAt": int(time.time() * 1000),
        "source": "local",
        "version": VERSION,
        "pay_mode": 0,
        **descriptions,
        "iconSource": "letter:auto",
    }
    metadata.update(read_workbuddy_json(installed / "_skillhub_meta.json"))
    metadata.update(descriptions, version=VERSION)
    write_text(staged / "workbuddy.json", json.dumps(registration, ensure_ascii=False, indent=2) + "\n")
    write_text(staged / "_skillhub_meta.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")


def is_managed_skill(dest, marker_text, *, workbuddy):
    marker = dest / INSTALL_MARKER
    check_install_path(marker)
    try:
        if marker.exists():
            return read_text(marker) == marker_text

        # 旧版没有安装标记。用技能入口和团队定义确认来源。
        skill = dest / "SKILL.md"
        check_install_path(skill)
        if teamdef.parse_front(skill).get("name") != CORE_DIR:
            return False
        core = dest / "references" if workbuddy else dest
        check_install_path(core, directory=True)
        if not has_team_identity(core):
            return False
        if workbuddy:
            return read_workbuddy_json(dest / "_skillhub_meta.json").get("name") == WORKBUDDY_NAME
        return True
    except (OSError, UnicodeError):
        return False


def install_native_skill(platform):
    dest = Path.home().resolve() / platform / "skills" / CORE_DIR
    check_install_path(dest, directory=True)
    ensure_target(dest)
    workbuddy = platform == ".workbuddy"
    marker_text = f"{CORE_DIR} {platform[1:]} skill install\n"
    upgrade = dest.exists()
    if upgrade and not is_managed_skill(dest, marker_text, workbuddy=workbuddy):
        raise SystemExit("已有同名目录，无法确认由安装器创建: %s" % dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{CORE_DIR}-", dir=dest.parent) as tmp:
        staged = Path(tmp) / CORE_DIR
        if workbuddy:
            copy_package(staged / "references")
            write_workbuddy_skill(staged, dest)
        else:
            copy_package(staged, files=teamdef.SKILL_FILES, dirs=teamdef.SKILL_DIRS)
        return apply_staged_install(staged, dest, marker_text, upgrade=upgrade)


def dsh_presets():
    cards = {meta["name"]: path.as_posix() for path, meta in SOURCE_CARDS.items()}
    rows = ["| 角色 | 文件 | 建议 toolFilter |", "|---|---|---|"]
    for agent in TEAM["agents"]:
        rows.append("| %s | `%s` | %s |" % (
            agent["id"],
            cards[agent["id"]],
            agent.get("tool_filter", "按需")))
    return """%s

DSH 自动读取 `AGENTS.md` 与 `CLAUDE.md`。
角色需要手动建 Preset：设置 → Agent Preset → 新建，粘贴对应角色卡正文。

%s

## toolFilter 要点

- 评审与安全角色只写报告，不改源码或工件。
- 测试角色拒绝写源码，避免边测边改。
- 总控可读写状态文件，但不直接改业务代码。
""" % (DSH_PRESET_HEADING, "\n".join(rows))


HOOK_MARK = "# sdlc-agent-team:gate-hook"


def git_hooks_dir(target):
    """返回 Git 钩子目录。支持普通仓库和 worktree。"""
    marker = target / ".git"
    if not marker.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--git-path", "hooks"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            encoding="utf-8")
    except OSError:
        if marker.is_dir():
            return marker / "hooks"
        return None
    if result.returncode != 0:
        if marker.is_dir():
            return marker / "hooks"
        return None
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = target / path
    return path


def checked_hook_path(target):
    hooks_dir = git_hooks_dir(target)
    if hooks_dir is None:
        return None
    hook = hooks_dir / "pre-commit"
    if hook.is_symlink() or (hook.exists() and (
            not hook.is_file() or HOOK_MARK.encode("utf-8") not in hook.read_bytes())):
        raise SystemExit("已有预提交钩子，不覆盖: %s" % hook)
    return hook


def install_hooks(target):
    """安装 Git 预提交钩子。已有钩子时不覆盖。"""
    hook = checked_hook_path(target)
    if hook is None:
        print("未找到 Git 仓库，跳过预提交钩子")
        return
    hook.parent.mkdir(parents=True, exist_ok=True)
    text = """#!/bin/sh
%s
# 提交前检查已通过的门和失败门。没有已通过门且没有失败门时跳过。检查失败时阻止提交。
if python3 -c 'pass' >/dev/null 2>&1; then
  PYTHON=python3
else
  PYTHON=python
fi
"$PYTHON" sdlc-agent-team/tools/gates.py --gate passed --quiet --allow-empty --fail-on-fail || exit 1
""" % HOOK_MARK
    hook.write_bytes(text.encode("utf-8"))
    try:
        os.chmod(str(hook), 0o755)
    except OSError:
        pass
    print("已安装预提交钩子: %s" % hook)


def project_skill(count, modes, guidance, *, legacy=False):
    if legacy:
        return (
            f"---\nname: {CORE_DIR}\n"
            f"description: 软件交付专家团。{count} 个 Agent 按 8 个主阶段交付软件，支持{LEGACY_MODES}。"
            "当任务涉及新建项目、从零开发、二次开发、迭代或热修时使用。\n---\n\n"
            f"读 `{CORE_DIR}/AGENTS.md` 和 `{CORE_DIR}/protocol.md`。\n"
            f"读 `{CORE_DIR}/team/00-orchestrator.md`。你是总控。\n"
            "先判定项目模式，再按门禁推进。\n"
            f"角色卡在 `{CORE_DIR}/team/`。\n"
        )
    front = (
        f"---\nname: {CORE_DIR}\n"
        f"description: 软件交付专家团。{count} 个 Agent 按阶段交付软件，支持{modes}。"
        "当用户请求使用专家团或按门禁交付软件时使用。\n---"
    )
    return skill_document(CORE_DIR, front) + guidance


def previous_project_entries(core, current, source_cards):
    definition = core / "team.yaml"
    check_install_path(definition)
    if not definition.exists():
        return current, project_entry_contents(PACK, TEAM, source_cards, legacy=True)
    try:
        data = teamdef.parse_team_yaml(definition)
        cards = packaged_cards(core)
        return (project_entry_contents(core, data, cards),
                project_entry_contents(core, data, cards, legacy=True))
    except (OSError, ValueError):
        return {}, {}


def check_project_entries(target, chosen, core):
    """检查所选入口，并记录核心更新前可确认归属的入口。"""
    check_install_path(target / "docs", directory=True)
    check_install_path(target / "docs" / "cr", directory=True)
    check_install_path(target / "docs" / "status.md")

    source_cards = packaged_cards(PACK)
    current = project_entry_contents(PACK, TEAM, source_cards)
    directories = {".agents" if platform == "dsh" else f".{platform}" for platform in chosen}
    updates = {relative: content for relative, content in current.items()
               if relative.parts[0] in directories}
    recorded = project_marker(core) or {}
    verified = {}
    previous = None
    for relative in sorted(current):
        try:
            check_relative_file(target, relative)
        except SystemExit:
            if relative in updates:
                raise
            continue
        path = target / relative
        if not path.exists():
            continue
        try:
            payload = path.read_bytes()
            content = payload.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except (OSError, UnicodeError):
            if relative in updates:
                raise SystemExit("无法读取项目入口: %s" % path)
            continue
        name = relative.as_posix()
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if digest == recorded.get(name) or content == current[relative]:
            verified[name] = digest
            if payload == current[relative].encode("utf-8"):
                updates.pop(relative, None)
            continue
        if previous is None:
            previous, legacy = previous_project_entries(core, current, source_cards)
        previous_content = previous.get(relative)
        earlier_content = (previous_content.replace(
            GATE_LOOKUP, " 第 4 节中对应门的完成标准。") if previous_content else None)
        if content in (previous_content, earlier_content, legacy.get(relative)):
            verified[name] = digest
        elif relative in updates:
            raise SystemExit("已有同名项目入口，无法确认由安装器创建: %s" % path)

    marker = {"kind": PROJECT_INSTALL_KIND, "entries": verified}
    return updates, json.dumps(marker, sort_keys=True, indent=2) + "\n"


def plugin_entries(cards, filters):
    """生成插件入口的相对路径和内容。"""
    entries = {}
    root = "${CLAUDE_PLUGIN_ROOT}/" + CORE_DIR
    for card, meta in cards:
        name = meta.get("name")
        if not name:
            continue
        description = json.dumps(meta.get("description", name), ensure_ascii=False)
        front = f"---\nname: {name}\ndescription: {description}\n"
        body = (
            f"先用 `Read` 读 `{root}/team/{card.name}`。按角色卡执行任务。\n"
            f"团队资源位于 `{root}/`。角色卡中的 `AGENTS.md`、"
            "`protocol.md`、`team.yaml`、`team/`、`templates/` 和 `tools/` 路径以此目录为准。\n"
            "在当前项目 `${CLAUDE_PROJECT_DIR}` 读写项目文件和 `docs/`。从该目录运行工具。\n"
        )
        tools = teamdef.claude_tools(filters.get(name, ""))
        entries[Path("agents") / f"{name}.md"] = (
            f"{front}tools: {tools}\nmodel: inherit\n---\n\n{body}")
        if name == "orchestrator":
            entries[Path("skills") / name / "SKILL.md"] = f"{front}---\n\n{body}"
    return entries


PLUGIN_MANIFEST = Path(".claude-plugin/plugin.json")
PLUGIN_README = Path("README.md")


def plugin_managed_paths(core, entries):
    """列出插件归属清单所覆盖的路径。"""
    yield from (PLUGIN_MANIFEST, PLUGIN_README)
    yield from entries
    prefix = Path(CORE_DIR)
    for name in CORE_FILES:
        yield prefix / name
    for directory in CORE_DIRS:
        for path in (core / directory).rglob("*"):
            relative = path.relative_to(core)
            if path.is_file() and not PACKAGE_IGNORE(core, relative.parts):
                yield prefix / relative


def plugin_manifest(data, *, legacy=False):
    count = len(data["agents"])
    modes = "、".join(mode["label"] for mode in data["modes"].values())
    manifest = {
        "name": CORE_DIR,
        "version": data["version"],
        "description": (
            "%d 角色软件交付团队。覆盖需求、设计、开发、测试、安全、评审、发布和复盘。"
            "支持%s。" % (count, modes)
        ),
        "author": {"name": "sdlc-agent-team contributors"},
        "license": "MIT",
        "keywords": ["sdlc", "agents", "gates", "brownfield", "hotfix"],
    }
    if legacy:
        manifest.update(
            description=(f"{count} 角色软件交付团队：需求、设计、开发、测试、安全、评审、"
                         "发布、复盘。支持新建、二次开发、迭代、热修。"),
            agents="./agents/", skills="./skills/", commands="./commands/",
        )
    return manifest


def plugin_readme(count, version=None):
    header = "# sdlc-agent-team 插件\n\n"
    if version:
        header += "版本: %s\n\n" % version
    return header + (
        "%d 角色软件交付团队。安装后输入 `/sdlc-agent-team:orchestrator`，启动总控技能。\n"
        "调用单个角色时，输入 `@agent-sdlc-agent-team:<角色 ID>`。\n\n"
        "本目录是生成物，不要手改。改 `team/` 或 `protocol.md` 后重跑：\n\n"
        "```\npython bin/install.py --build-plugin plugins/sdlc-agent-team\n```\n\n"
        "入口按需读取 `%s/team/` 中的角色卡。流程协议在 `%s/protocol.md`。\n"
        % (count, CORE_DIR, CORE_DIR)
    )


def legacy_plugin_components(cards, filters):
    """列出旧版插件生成过的入口内容。"""
    generated = {path: {text} for path, text in plugin_entries(cards, filters).items()}
    root = "${CLAUDE_PLUGIN_ROOT}/" + CORE_DIR
    prefix = (
        f"团队资源位于 `{root}/`。下文的 `AGENTS.md`、"
        "`protocol.md`、`team.yaml`、`team/`、`templates/` 和 `tools/` 路径以此目录为准。\n"
        "在当前项目 `${CLAUDE_PROJECT_DIR}` 读写项目文件和 `docs/`。从该目录运行工具。\n\n"
    )
    for card, meta in cards:
        role = meta.get("name")
        if not role:
            continue
        desc = meta.get("description", role).replace("\n", " ")
        agent = Path("agents") / f"{role}.md"
        skill = Path("skills") / role / "SKILL.md"
        tools = teamdef.claude_tools(filters.get(role, ""))
        front = f"---\nname: {role}\ndescription: {desc}\n"
        body = teamdef.read_body(card)
        for content in (body, prefix + body):
            generated.setdefault(agent, set()).add(
                f"{front}tools: {tools}\nmodel: inherit\n---\n\n{content}")
            generated.setdefault(skill, set()).add(f"{front}---\n\n{content}")
        generated[Path("commands") / f"{role}.md"] = {
            f"---\ndescription: 调用 {role} 角色处理当前任务\n---\n\n"
            f"先读 `{CORE_DIR}/AGENTS.md` 和 `{CORE_DIR}/protocol.md`。\n"
            "产出物写入 `docs/`，完成后更新 `docs/status.md`。\n\n"
            "任务：$ARGUMENTS\n"
        }
    return generated


def plugin_file_hash(path):
    # 插件核心文件为文本。Git 检出可能转换换行符。
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def plugin_ownership(outdir):
    """读取新版清单，或核对旧版插件的团队定义和注册信息。"""
    marker = outdir / INSTALL_MARKER
    check_install_path(marker)
    core = outdir / CORE_DIR
    manifest_path = outdir / PLUGIN_MANIFEST
    try:
        if marker.exists():
            record = json.loads(read_text(marker))
            if (isinstance(record, dict) and record.get("kind") == PLUGIN_INSTALL_KIND
                    and isinstance(record.get("files"), dict)):
                return record["files"], None
        else:
            check_relative_file(outdir, PLUGIN_MANIFEST)
            check_install_path(core, directory=True)
            if has_team_identity(core):
                data = teamdef.parse_team_yaml(core / "team.yaml")
                manifest = json.loads(read_text(manifest_path))
                if manifest in (plugin_manifest(data), plugin_manifest(data, legacy=True)):
                    return None, data
    except (OSError, ValueError):
        pass
    raise SystemExit("已有同名目录，无法确认由插件生成器创建: %s" % outdir)


def check_plugin_upgrade(staged, outdir, managed_paths):
    files, legacy_data = plugin_ownership(outdir)
    legacy = {}
    if legacy_data is not None:
        filters = {agent["id"]: agent.get("tool_filter", "") for agent in legacy_data["agents"]}
        legacy = legacy_plugin_components(packaged_cards(outdir / CORE_DIR), filters)
        readme = plugin_readme(len(legacy_data["agents"]))
        legacy_readme = readme.replace(
            f"入口按需读取 `{CORE_DIR}/team/` 中的角色卡。",
            "插件内角色是完整副本。")
        early_readme = legacy_readme.replace(
            "安装后输入 `/sdlc-agent-team:orchestrator`，启动总控技能。\n"
            "调用单个角色时，输入 `@agent-sdlc-agent-team:<角色 ID>`。",
            "安装后可用 `/orchestrator` 等命令，或用 Task 工具点名调用子 agent。")
        versioned_readme = plugin_readme(len(legacy_data["agents"]), legacy_data["version"])
        legacy[PLUGIN_README] = {readme, versioned_readme, legacy_readme, early_readme}

    for relative in managed_paths:
        check_relative_file(outdir, relative)
        path = outdir / relative
        if not path.exists():
            continue
        if files is not None:
            managed = plugin_file_hash(path) == files.get(relative.as_posix())
        else:
            core_file = relative.parts[0] == CORE_DIR
            runtime = (core_file
                       and relative.parts[1] in (*RUNTIME_FILES, *RUNTIME_DIRS))
            managed = (runtime or relative == PLUGIN_MANIFEST
                       or matches_generated(path, *legacy.get(relative, ()))
                       or (core_file and plugin_file_hash(path) == plugin_file_hash(staged / relative)))
        if not managed:
            raise SystemExit("已有同名插件文件，无法确认由插件生成器创建: %s" % path)

    recorded = legacy if files is None else {Path(name): digest for name, digest in files.items()}
    remove = []
    for relative, generated in recorded.items():
        if not relative.parts or relative.anchor or ".." in relative.parts:
            continue
        if files is None and relative.parts[0] not in ("skills", "commands"):
            continue
        if (staged / relative).exists():
            continue
        path = outdir / relative
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            continue
        unchanged = (matches_generated(path, *generated) if files is None
                     else plugin_file_hash(path) == generated)
        if unchanged:
            remove.append(relative)
    return remove


def build_plugin(outdir):
    """生成 Claude Code 插件目录，内置角色卡和轻量入口。"""
    outdir = Path(os.path.abspath(outdir))
    check_install_path(outdir, directory=True)
    upgrade = outdir.exists()
    filters = {agent["id"]: agent.get("tool_filter", "") for agent in TEAM["agents"]}
    outdir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{CORE_DIR}-", dir=outdir.parent) as tmp:
        staged = Path(tmp) / CORE_DIR
        entries = plugin_entries(packaged_cards(PACK), filters)
        for path, content in entries.items():
            write_text(staged / path, content)
        copy_package(staged / CORE_DIR)
        write_text(staged / PLUGIN_MANIFEST,
                   json.dumps(plugin_manifest(TEAM), ensure_ascii=False, indent=2) + "\n")
        write_text(staged / PLUGIN_README, plugin_readme(ROLE_COUNT, VERSION))
        paths = list(plugin_managed_paths(staged / CORE_DIR, entries))
        remove = check_plugin_upgrade(staged, outdir, paths) if upgrade and any(outdir.iterdir()) else ()
        files = {path.as_posix(): plugin_file_hash(staged / path) for path in paths}
        record = {"kind": PLUGIN_INSTALL_KIND, "files": files}
        return apply_staged_install(
            staged, outdir, json.dumps(record, sort_keys=True, indent=2) + "\n",
            upgrade=upgrade, remove=remove)


PLATFORMS = INSTALLERS = ("claude", "codex", "trae", "cursor", "workbuddy", "dsh", "generic")


def install_skill():
    """安装或同步到 Trae 用户级 Skill 目录。"""
    return install_native_skill(".trae-cn")


def main():
    parser = argparse.ArgumentParser(description="安装软件交付专家团")
    parser.add_argument("--platform", default="all", help="平台或 all")
    parser.add_argument("--target", default=".", help="目标项目目录")
    parser.add_argument("--list", action="store_true", help="列出平台")
    parser.add_argument("--build-plugin", metavar="DIR", help="生成 Claude 插件目录")
    parser.add_argument("--install-skill", action="store_true",
                        help="安装或同步到 Trae 用户级 Skill")
    parser.add_argument("--install-workbuddy", action="store_true",
                        help="安装到 WorkBuddy 全局技能目录")
    parser.add_argument("--hooks", action="store_true",
                        help="安装 Git 预提交钩子")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示项目安装计划，不写文件")
    args = parser.parse_args()

    if args.dry_run and (args.build_plugin or args.install_skill
                         or args.install_workbuddy):
        print("--dry-run 只用于项目安装")
        return 2

    if args.list:
        print("\n".join(PLATFORMS))
        return

    if args.install_workbuddy:
        dest = install_workbuddy_global()
        print("已安装到 WorkBuddy: %s" % dest)
        print("重启 WorkBuddy 后生效")
        return

    if args.install_skill:
        dest = install_skill()
        print("已同步到 Trae Skill: %s" % dest)
        return

    if args.build_plugin:
        out = build_plugin(args.build_plugin)
        print("插件已生成: %s" % out)
        print("版本: %s" % VERSION)
        print("角色: %d 个" % len(list((PACK / "team").glob("*.md"))))
        return

    if args.platform != "all" and args.platform not in PLATFORMS:
        raise SystemExit("未知平台: %s" % args.platform)

    target = Path(args.target).resolve()
    ensure_target(target)
    check_install_path(target, directory=True)
    if args.hooks:
        checked_hook_path(target)
    chosen = PLATFORMS if args.platform == "all" else [args.platform]
    blocks = project_blocks(target, chosen, replace_only=args.platform == "trae")
    dest = check_core_destination(target, include_dsh="dsh" in chosen)
    entries, marker = check_project_entries(target, chosen, dest)
    if args.dry_run:
        print("dry-run: 不写文件")
        print("目标: %s" % target)
        print("平台: %s" % ", ".join(chosen))
        print("核心目录: %s (%s)" % (dest, "升级" if dest.exists() else "新建"))
        state = target / "docs" / "status.md"
        print("状态板: %s" % ("保留" if state.exists() else "新建"))
        if args.hooks:
            print("预提交钩子: 安装或更新")
        return
    target.mkdir(parents=True, exist_ok=True)

    copy_core(target, include_dsh="dsh" in chosen, marker_text=marker)
    init_docs(target)
    for path, content in blocks.items():
        if content is not None:
            write_text(path, content)
    for relative, content in entries.items():
        write_text(target / relative, content)

    if args.hooks:
        install_hooks(target)

    print("安装完成: %s" % target)
    print("核心目录: %s/" % CORE_DIR)
    print("已启用平台: %s" % ", ".join(chosen))
    if "trae" in chosen:
        print("TRAE: 在内置 Agent 中选择 /sdlc-agent-team 技能。")
    if args.platform != "trae":
        print("下一步: 在目标项目里对 Agent 说:")
        print("  读 %s/AGENTS.md 和 %s/team/00-orchestrator.md。" % (CORE_DIR, CORE_DIR))
        print("  你是总控。先判定项目模式，再按门禁推进。")


if __name__ == "__main__":
    sys.exit(main())
