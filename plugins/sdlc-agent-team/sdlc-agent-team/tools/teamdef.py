"""团队定义的共享解析器。

team.yaml 是唯一注册表。角色卡只在 front matter 中保留 name、description、handoff。
本模块放在 tools/ 下，安装到项目或插件后仍可使用。
"""

import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

PACK = Path(__file__).resolve().parent.parent
TEAM_YAML = PACK / "team.yaml"
TEAM_DIR = PACK / "team"
OWNER_LABELS = {"requester": "请求变更的 Agent"}
GATE_OWNER_LABELS = {
    "human_and_orchestrator": "人 + 总控",
    "human": "人",
    "orchestrator": "总控",
    "reviewer": "reviewer",
}
HUMAN_GATE_OWNERS = {"human", "human_and_orchestrator"}
GATE_ARTIFACT_KEYS = (
    "artifacts", "artifacts_brownfield", "artifacts_ui", "artifacts_backend",
    "artifacts_hotfix", "artifacts_hotfix_any", "artifacts_hotfix_security",
    "artifacts_quick",
)
RUNTIME_FILES = ("AGENTS.md", "protocol.md", "team.yaml")
RUNTIME_DIRS = ("team", "templates", "tools")
CORE_FILES = (*RUNTIME_FILES, "README.md", "CLAUDE.md", "PLATFORMS.md", "LICENSE")
CORE_DIRS = RUNTIME_DIRS
SKILL_FILES = (*CORE_FILES, "SKILL.md", "install.sh")
SKILL_DIRS = (*CORE_DIRS, "bin")


class StatusFormatError(ValueError):
    """项目状态板包含歧义或无效的结构。"""


def resolve_project(project=None):
    """读取指定项目目录，或根据安装位置和当前目录判断。"""
    if project:
        return Path(project).resolve()
    if (PACK.parent / "docs" / "status.md").exists():
        return PACK.parent
    return Path.cwd()


def read(path):
    return Path(path).read_text(encoding="utf-8")


def retry_windows_access(operation, *args):
    """在 Windows 上遇到权限错误时重试，最长等待 5 秒。"""
    if os.name != "nt":
        return operation(*args)
    deadline = time.monotonic() + 5
    while True:
        try:
            return operation(*args)
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


@contextmanager
def atomic_text_writer(path, *, before_replace=None):
    """写入临时文件。每次替换前执行调用方的检查。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent,
        prefix=".%s." % path.name, suffix=".tmp", delete=False)
    try:
        with stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())

        def replace():
            if before_replace is not None:
                before_replace()
            os.replace(stream.name, path)

        retry_windows_access(replace)
    finally:
        Path(stream.name).unlink(missing_ok=True)


@contextmanager
def lock_file(path):
    """用目标文件旁的锁文件保护写入。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(".%s.lock" % path.name)
    # 保留锁文件。等待中的写入者使用同一个锁。
    with lock_path.open("a+b") as lock:
        if os.name == "nt":
            lock.seek(0)
            retry_windows_access(msvcrt.locking, lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def unquote(value):
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_front(path):
    """读取角色卡 front matter 的简单键值。"""
    text = read(path)
    match = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
    meta = {}
    if not match:
        return meta
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = unquote(value)
    return meta


def read_body(path):
    """去掉 front matter，返回正文。"""
    text = read(path)
    match = re.match(r"^---\r?\n.*?\r?\n---\r?\n", text, re.S)
    return text[match.end():].strip() + "\n" if match else text


def parse_list(value):
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    value = (value or "").strip()
    if value.startswith("[") and value.endswith("]"):
        return [part.strip() for part in value[1:-1].split(",") if part.strip()]
    return [value] if value else []


def parse_pairs(value):
    """读取 a=b,c;d=[e,f] 形式的配置。"""
    pairs = {}
    for part in (value or "").split(";"):
        key, separator, raw = part.partition("=")
        key = key.strip()
        if not separator or not key:
            continue
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            raw = raw[1:-1]
        pairs[key] = [item.strip() for item in raw.split(",") if item.strip()]
    return pairs


def profile_sections(profile):
    """返回 (目标工件, 被替代工件, 章节)。旧配置可省略被替代工件。"""
    for target, specs in parse_pairs(profile.get("extra_sections", "")).items():
        for spec in specs or [""]:
            source, separator, heading = spec.partition("#")
            if separator:
                yield target, source.strip(), heading.strip()
            else:
                yield target, "", source


def parse_team_yaml(path=TEAM_YAML):
    """解析 team.yaml 的 version、modes、agents、gates、artifacts。"""
    data = {
        "version": "",
        "monitoring": {},
        "rules": {},
        "modes": {},
        "profiles": {},
        "stages": [],
        "hotfix_stages": [],
        "hotfix_checks": [],
        "mode_base_stages": [],
        "rule_summary": [],
        "agents": [],
        "gates": [],
        "routes": [],
        "artifacts": {},
        "optional_artifacts": [],
    }
    section = None
    item = None
    mode = None
    profile = None
    list_key = None

    for raw in read(path).splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if not line[0].isspace():
            if stripped.endswith(":"):
                section = stripped[:-1]
                item = None
                mode = None
                profile = None
                list_key = None
                continue
            key, _, value = stripped.partition(":")
            if key.strip() == "version":
                data["version"] = unquote(value)
            elif key.strip() == "mode_base_stages":
                data["mode_base_stages"] = parse_list(unquote(value))
            elif key.strip() == "optional_artifacts":
                data["optional_artifacts"] = parse_list(unquote(value))
            continue

        if section == "monitoring":
            match = re.match(r"^  ([A-Za-z_]+):\s*(.*)$", line)
            if match:
                data["monitoring"][match.group(1)] = unquote(match.group(2))
            continue

        if section == "rules":
            match = re.match(r"^  ([A-Za-z_]+):\s*(.*)$", line)
            if match:
                data["rules"][match.group(1)] = unquote(match.group(2))
            continue

        if section == "modes":
            match = re.match(r"^  ([A-Za-z_]+):\s*$", line)
            if match:
                mode = match.group(1)
                data["modes"][mode] = {}
                continue
            match = re.match(r"^    ([A-Za-z_]+):\s*(.*)$", line)
            if match and mode:
                data["modes"][mode][match.group(1)] = unquote(match.group(2))
            continue

        if section == "profiles":
            match = re.match(r"^  ([A-Za-z_]+):\s*$", line)
            if match:
                profile = match.group(1)
                data["profiles"][profile] = {}
                continue
            match = re.match(r"^    ([A-Za-z_]+):\s*(.*)$", line)
            if match and profile:
                data["profiles"][profile][match.group(1)] = unquote(match.group(2))
            continue

        if section in ("hotfix_checks", "rule_summary"):
            match = re.match(r"^  - (.*)$", line)
            if match:
                data[section].append(match.group(1).strip())
            continue

        if section in ("agents", "gates", "stages", "hotfix_stages", "routes"):
            match = re.match(r"^  - (\w+):\s*(.*)$", line)
            if match:
                item = {match.group(1): unquote(match.group(2))}
                if section == "gates":
                    item["checks"] = []
                data[section].append(item)
                list_key = None
                continue
            match = re.match(r"^    ([A-Za-z_]+):\s*(.*)$", line)
            if match and item is not None:
                key = match.group(1)
                value = unquote(match.group(2))
                if key in ("checks", "checks_quick", "checks_hotfix"):
                    item[key] = []
                    list_key = key
                else:
                    item[key] = value
                continue
            match = re.match(r"^      - (.*)$", line)
            if match and item is not None and list_key:
                item[list_key].append(match.group(1).strip())
            continue

        if section == "artifacts":
            match = re.match(r"^  (\S+):\s*(\S+)", line)
            if match:
                data["artifacts"][match.group(1)] = match.group(2)

    for mode in data["modes"].values():
        if "stages" in mode:
            mode["stages"] = parse_list(mode.get("stages"))
        elif data["mode_base_stages"]:
            mode["stages"] = (parse_list(mode.get("prefix_stages"))
                              + data["mode_base_stages"])

    return data


def claude_tools(tool_filter):
    """把 tool_filter 映射为 Claude 插件的工具列表。括号内的限制说明不参与判断。"""
    value = re.sub(r"[（(][^）)]*[）)]", "", tool_filter or "")
    if "全部" in value:
        return "Read, Write, Edit, Bash, Grep, Glob"
    tools = ["Read"]
    if "写" in value:
        tools.append("Write")
    if "执行" in value:
        tools.append("Bash")
    tools += ["Grep", "Glob"]
    return ", ".join(tools)


def status_fields(text):
    """读取状态板头部的模式、范围和阶段。只读首个二级标题前的内容。"""
    header = re.split(r"^## ", text, maxsplit=1, flags=re.M)[0]
    fields = {}
    for label, key in (("模式", "mode"), ("变更编号", "change_id"), ("界面", "ui"),
                       ("后端", "backend"), ("数据库", "database"),
                       ("热修安全影响", "hotfix_security"), ("规模", "profile"),
                       ("发布", "release"), ("阶段", "stage")):
        matches = re.findall(r"^%s[:：][ \t]*(.+)$" % label, header, re.M)
        if len(matches) > 1:
            raise StatusFormatError("状态板头部有重复字段: %s" % label)
        if matches:
            fields[key] = matches[0].strip()
    return fields


def table_rows(text, heading):
    """读取指定标题下的 Markdown 表格行。"""
    rows = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == heading
            continue
        if not inside or not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`").strip()
                 for cell in line.strip().strip("|").split("|")]
        if cells[0] and not re.fullmatch(r":?-+:?", cells[0]):
            rows.append(cells)
    return rows


def _unique_record_rows(text, name, heading):
    rows = {}
    for cells in table_rows(text, "## " + name):
        key = cells[0]
        if key == heading:
            continue
        if key in rows:
            raise StatusFormatError("%s表有重复记录: %s" % (name, key))
        rows[key] = cells
    return rows


def status_record_rows(text):
    """统一读取门禁和产出物表。每个门和文件各登记一次。"""
    gates = _unique_record_rows(text, "门禁", "门")
    artifacts = _unique_record_rows(text, "产出物", "文件")
    for key, row in gates.items():
        if len(row) < 5:
            raise StatusFormatError("门禁表行格式错误: %s（至少 5 列）" % key)
        if row[2].lower() not in ("pending", "pass", "fail", "n/a", "na"):
            raise StatusFormatError(
                "门禁表状态无效: %s（%s）。填写 pending、pass、fail 或 n/a。"
                % (key, row[2] or "空"))
    for key, row in artifacts.items():
        if len(row) < 2:
            raise StatusFormatError("产出物表行格式错误: %s（至少 2 列）" % key)
    return gates, artifacts


def passed_gate_ids(text):
    gates, _ = status_record_rows(text)
    return {gate_id for gate_id, cells in gates.items()
            if cells[2].lower() == "pass"}


def resolve_mode_id(team, mode):
    """把状态板中的模式 ID 或配置名称解析为模式 ID。"""
    modes = team["modes"]
    if mode in modes:
        return mode
    return next((key for key, entry in modes.items()
                 if entry.get("label") == mode), "")


def mode_gate_ids(team, mode):
    config = team["modes"].get(resolve_mode_id(team, mode), {})
    ids = {gate["id"] for gate in team["gates"]}
    return [stage for stage in config.get("stages", []) if stage in ids]


def role_cards(team_dir=TEAM_DIR):
    """返回按角色名索引的卡片路径和头部信息。"""
    cards = {}
    for card in sorted(Path(team_dir).glob("*.md")):
        meta = parse_front(card)
        name = meta.get("name")
        if name:
            cards[name] = (card, meta)
    return cards


def card_map(team_dir=TEAM_DIR):
    """返回 {角色名: 'team/xx.md'}。"""
    return {name: "team/%s" % card.name for name, (card, _) in role_cards(team_dir).items()}
