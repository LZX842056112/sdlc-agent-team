#!/usr/bin/env python3
"""检查项目门禁。

自动检查项:
1. 工件文件存在且非空。
2. 状态板有门禁行和工件行。
3. 工件状态是 APPROVED。
4. 评审报告有通过结论。
5. 关键章节存在。
6. 返工次数不超过 team.yaml 的 rework_limit。
7. 状态板 `界面: 无` 时跳过界面工件。`界面: 有` 时强制界面工件。
8. 工件版本与状态板登记一致。
9. 工件不含未填写的占位内容。
10. 人工批准记录（仅 human_approval_required 中的门）。
11. G5 批准记录包括批准人、批准时间、非生产范围和批准原文。
12. 热修 G4 核对安全影响。需要安全复核时检查本次报告和准出结论。
13. G6 按数据库状态核对适用的备份和恢复证据。

`--gate <门>` 只做就绪检查，输出 `[READY]`。
`--gate <门> --require-pass` 只复核当前门的通过状态及其工件。
`--gate passed` 和 `--gate all` 检查 pass 状态，输出 `[PASS]`。
`--gate all` 按当前模式验收。适用门来自 team.yaml。

语义判断仍由门负责人完成。

用法:
    python tools/gates.py --gate passed
    python tools/gates.py --gate G1
    python tools/gates.py --gate all
    python tools/gates.py --sync-artifacts --dry-run
    python sdlc-agent-team/tools/gates.py --project <项目>
"""

import argparse
import hashlib
import re
import sys
from datetime import date
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "tools"))

import teamdef


class GateInputError(ValueError):
    """门禁输入文件无法读取。"""

CONTENT_RULES = {
    "docs/00-brief.md": ("目标", "范围", "成功指标", "主要风险"),
    "docs/00-context.md": ("现有测试基线", "不可动清单"),
    "docs/01-requirements.md": ("验收标准",),
    "docs/02-design.md": ("接口契约", "降级与回滚"),
    "docs/02-impact.md": ("直接调用方", "回滚"),
    "docs/02-threat-model.md": ("威胁模型",),
    "docs/02-ui-spec.md": ("组件", "验收"),
    "docs/02-ux.md": ("任务流", "五态", "组件", "验收"),
    "docs/03-build-notes-frontend.md": ("修改文件", "构建"),
    "docs/03-build-notes-backend.md": ("修改文件", "构建"),
    "docs/04-test-report.md": ("用例", "准出建议"),
    "docs/04-perf-report.md": ("用例", "性能", "准出建议"),
    "docs/04-security-report.md": ("用例", "安全", "准出建议"),
    "docs/05-release.md": ("回滚方案", "人工批准记录", "迁移", "告警", "公告"),
    "docs/06-ops.md": ("监控", "容量", "告警"),
    "docs/07-retro.md": ("问题与根因", "改进项"),
    "docs/08-hotfix.md": ("时间线", "回滚"),
}
REVIEW_PREFIX = "docs/review-"
UI_MARKERS = ("index.html", "src/App.tsx", "src/App.jsx",
              "next.config.js", "next.config.mjs", "next.config.ts",
              "nuxt.config.ts", "angular.json", "svelte.config.js",
              "frontend", "web", "apps/web", "src/components")
UI_OFF = ("无", "无界面", "无界面改动", "无界面变更")
BACKEND_OFF = ("无", "无后端", "无后端改动", "无后端变更")
PLACEHOLDERS = ("待补充", "待填写", "待完善")
APPROVAL_EMPTY = {"", "无", "待定", "暂无", "-", "—"}
APPROVAL_RULES = {"non_production"}
APPROVAL_SECTION = re.compile(
    r"^##[ \t]+人工批准记录[^\n]*\n(.*?)(?=^##[ \t]+|\Z)", re.M | re.S)
NON_PRODUCTION = re.compile(
    r"非生产|不涉及生产|(?:不|禁止)(?:部署|发布)(?:到)?生产")
NEGATIVE_APPROVAL = re.compile(
    r"(?:不|未|还没|不能|不予|待|没有|后再|才)\s*(?:明确)?\s*(?:同意|批准)|拒绝|否决")
APPROVAL_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?=$|[T\s])")
BACKUP_OK = ("通过", "完成", "成功")
RESTORE_ROWS_RE = re.compile(r"行数\s*(\d+)\s*=\s*(\d+)")
RESTORE_CHECKSUM_RE = re.compile(
    r"CHECKSUM\s*([0-9A-Fa-f]+)\s*=\s*([0-9A-Fa-f]+)", re.I)
EVIDENCE_PATH_RE = re.compile(
    r"docs/evidence/[A-Za-z0-9_./\-\u4e00-\u9fff]+")
SHA256_RE = re.compile(r"\b[A-Fa-f0-9]{64}\b")
FILE_SHA256_RE = re.compile(r"\bSHA-?256\b(?:\s*[:=：]?\s*`?([0-9a-f]+)\b)?", re.I)
VERSION_RE = re.compile(r"^>[ \t]*版本[:：][ \t]*(\S+)", re.M)
RELEASE_STATES = ("验证上线",)
CLOSED_BLOCKERS = {"CLOSED", "RESOLVED", "DONE", "已关闭", "已解决", "已解除", "已完成"}
POSITIVE_REVIEW_RE = re.compile(
    r"^(通过(?=$|[，。；;、：:！!\s（(])|APPROVED\b)", re.I)
CONFIRMATION_SUBJECTS = {"G0": ("变更立项", "立项", "项目章程"), "G7": ("复盘", "结项")}
CONFIRMATION_SUBJECT = "|".join(CONFIRMATION_SUBJECTS["G0"] + CONFIRMATION_SUBJECTS["G7"])
CONFIRMED_DECISION = re.compile(
    r"(?:已)?(?:确认|同意|批准|通过)(?:(?:本次|本轮)?(?P<subject>%s))?"
    r"|(?:本次|本轮)?(?P<subject_first>%s)(?:通过|获批)"
    r"|APPROVED|CONFIRMED|PASS(?:ED)?" % (CONFIRMATION_SUBJECT, CONFIRMATION_SUBJECT), re.I)


def confirmation_matches_gate(gate_id, conclusion):
    decision = CONFIRMED_DECISION.fullmatch(conclusion.rstrip("。！.!").strip())
    if not decision:
        return False
    subject = decision["subject"] or decision["subject_first"]
    expected = CONFIRMATION_SUBJECTS.get(gate_id, ())
    return not (subject and expected) or subject in expected


def scoped_change(status):
    return status["mode_id"] in ("quick", "hotfix")


def active_profile(data, status):
    """按状态板的规模值返回配置。默认标准。"""
    value = status.get("profile", "").strip()
    profiles = data.get("profiles", {})
    for key, profile in profiles.items():
        label = profile.get("label", "")
        if value and value in (key, label, label + "项目"):
            return profile
    return profiles.get("standard", {})


def gate_artifacts(gate, status, project):
    """返回当前门的必需工件、候选工件和合并章节。"""
    mode = status["mode_id"]
    quick = mode == "quick"
    ui = status.get("ui", "").strip()
    backend = status.get("backend", "").strip()
    overrides = teamdef.parse_list(gate.get("artifacts_hotfix")) if mode == "hotfix" else []
    any_of = []
    if overrides:
        paths = overrides
        any_of = teamdef.parse_list(gate.get("artifacts_hotfix_any"))
        required = []
        excluded = []
        for field, value, off in (("artifacts_ui", ui, UI_OFF),
                                  ("artifacts_backend", backend, BACKEND_OFF)):
            notes = [path for path in teamdef.parse_list(gate.get(field)) if path in any_of]
            if value.startswith("有"):
                required.extend(notes)
            elif value in off:
                excluded.extend(notes)
        if required:
            paths += required
            any_of = []
        else:
            any_of = [path for path in any_of if path not in excluded] or any_of
    else:
        paths = teamdef.parse_list(
            (gate.get("artifacts_quick") if quick else None) or gate.get("artifacts"))
        if mode == "brownfield":
            paths += teamdef.parse_list(gate.get("artifacts_brownfield"))
        if backend.startswith("有") or (not quick and backend not in BACKEND_OFF):
            paths += teamdef.parse_list(gate.get("artifacts_backend"))
        if ui.startswith("有") or (not quick and ui not in UI_OFF and any(
                (project / marker).exists() for marker in UI_MARKERS)):
            paths += teamdef.parse_list(gate.get("artifacts_ui"))
    if mode == "hotfix" and status.get("hotfix_security") == "有":
        paths += teamdef.parse_list(gate.get("artifacts_hotfix_security"))
    profile = status.get("profile_config", {})
    skipped = set(teamdef.parse_list(profile.get("skip_artifacts", "")))
    replace = teamdef.parse_pairs(profile.get("replace_artifacts", ""))
    result = []

    for path in paths:
        targets = [target for target in replace.get(path, [])
                   if (project / target).exists()]
        for target in targets or [path]:
            if target not in skipped and target not in result:
                result.append(target)

    sections = {}
    if not quick:
        for target, source, heading in teamdef.profile_sections(profile):
            if target in result and (not source or (source in paths and source in skipped)):
                sections.setdefault(target, []).append(heading)
    return result, any_of, sections


def gate_checks(gate, status):
    if scoped_change(status):
        return gate.get("checks_" + status["mode_id"]) or gate["checks"]
    return gate["checks"]


def read(path, *, newline=None):
    try:
        with Path(path).open(encoding="utf-8", newline=newline) as stream:
            return stream.read()
    except UnicodeDecodeError as exc:
        raise GateInputError("文件不是 UTF-8: %s" % path) from exc


def require_status_snapshot(path, snapshot):
    if read(path, newline="") != snapshot:
        raise GateInputError("状态板在登记期间发生变化。重新运行 --sync-artifacts。")


def write_atomic(path, text, *, expected=None):
    def check_snapshot():
        if expected is not None:
            require_status_snapshot(path, expected)

    with teamdef.atomic_text_writer(path, before_replace=check_snapshot) as stream:
        stream.write(text)


def clean(cell):
    return cell.strip().strip("`").strip()


def approval_values(text):
    values = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|"):
            cells = [clean(cell) for cell in stripped.strip("|").split("|")]
            if len(cells) < 2 or not cells[0]:
                continue
            key, value = cells[:2]
        else:
            match = re.match(r"^([^:：]+)[:：]\s*(.*)$", stripped)
            if not match:
                continue
            key, value = match.group(1).strip(), match.group(2).strip()
        # 重复字段不能作为单一批准记录使用。
        values[key] = "" if key in values else value
    return values


def has_value(value):
    value = value.strip()
    return (value not in APPROVAL_EMPTY and value.upper() not in ("N/A", "TBD")
            and not any(placeholder in value for placeholder in PLACEHOLDERS))


def approval_semantic_ok(values, rule, scope_field, text_field, hotfix=False):
    scope = values.get(scope_field, "")
    original = values.get(text_field, "")
    if rule != "non_production" or not NON_PRODUCTION.search(scope):
        return False
    if any("生产" in NON_PRODUCTION.sub("", value) for value in (scope, original)):
        return False
    return (not NEGATIVE_APPROVAL.search(original)
            and ("同意" in original or "批准" in original)
            and (not hotfix or "发布" in original or "热修" in original))


def legacy_approval_conflicts(entry, approved):
    person = entry["person"]
    conclusion = entry["conclusion"]
    old_date = APPROVAL_DATE.match(entry["time"])
    new_date = APPROVAL_DATE.match(approved["批准时间"])
    return (bool(NEGATIVE_APPROVAL.search(conclusion))
            or "生产" in NON_PRODUCTION.sub("", conclusion)
            or (has_value(person) and person != approved["批准人"])
            or (old_date is not None and new_date is not None
                and old_date.group(1) != new_date.group(1)))


def approval_problems(project, gate, prior_entries, status):
    gate_id = gate["id"]
    fields = teamdef.parse_list(gate.get("approval_fields"))
    path = gate.get("approval_artifact", "")
    rule = gate.get("approval_rule", "")
    scope_field = gate.get("approval_scope_field", "")
    text_field = gate.get("approval_text_field", "")
    if (not {"批准人", "批准时间", scope_field, text_field}.issubset(fields)
            or not scope_field or not text_field or not path
            or rule not in APPROVAL_RULES):
        return ["%s 人工批准配置不完整或无效" % gate_id]
    release = project / path
    sections = APPROVAL_SECTION.findall(read(release)) if release.is_file() else []
    values = approval_values(sections[0]) if len(sections) == 1 else {}
    hotfix = status["mode_id"] == "hotfix"
    if (not all(has_value(values.get(field, "")) for field in fields)
            or not approval_semantic_ok(values, rule, scope_field, text_field, hotfix)):
        return ["%s 缺少人工批准记录。核对 %s 的批准人、时间、非生产范围和批准原文。" %
                (gate_id, path)]
    change_id = status.get("change_id", "")
    if hotfix and (not change_id or values.get("批准变更编号") != change_id):
        return ["%s 的批准变更编号必须对应本次热修 %s" % (gate_id, change_id)]
    if any(legacy_approval_conflicts(entry, values) for entry in prior_entries):
        return ["%s 状态板旧确认与发布计划冲突。核对人工作出的实际决定后，再合并记录。" % gate_id]
    return []


def na_problem(gate, row):
    if gate.get("allow_na") != "true":
        return "当前模式要求此门通过"
    if not has_value(row.get("missing", "")):
        return "n/a 缺少原因"
    return ""


def evidence_problem(evidence, project):
    if not evidence:
        return "缺少证据"
    invalid = "证据缺少有效文件路径或 SHA256"
    paths = list(EVIDENCE_PATH_RE.finditer(evidence))
    if not paths:
        return "" if SHA256_RE.search(evidence) else invalid
    malformed = "证据文件 SHA256 格式无效。请在文件路径后填写 64 位十六进制摘要。"
    if FILE_SHA256_RE.search(evidence[:paths[0].start()]):
        return malformed
    root = (project / "docs" / "evidence").resolve()
    for index, match in enumerate(paths):
        path = match.group().rstrip(".,;:")
        if ".." in Path(path).parts:
            return invalid
        target = (project / path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return invalid
        if not target.is_file() or target.stat().st_size == 0:
            return invalid
        end = paths[index + 1].start() if index + 1 < len(paths) else len(evidence)
        digests = FILE_SHA256_RE.findall(evidence[match.end():end])
        if not digests:
            continue
        if len(digests) != 1 or len(digests[0]) != 64:
            return malformed
        digest = hashlib.sha256()
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != digests[0].lower():
            return "证据文件 SHA256 与实际文件不一致: %s" % path
    return ""


def _label(value):
    return clean(value).strip("* ").strip()


def _split_result_evidence(value):
    if "证据" in value:
        result, _, rest = value.partition("证据")
        return (result.strip(" ，,。;；"), rest.strip(" ：:，,。;；"))
    return value.strip(" ，,。;；"), ""


def _match_runbook_result(bullet):
    normalized = bullet.replace("**", "").replace("`", "").strip()
    return re.match(r"^(备份|恢复演练)[:：]\s*(.*)$", normalized)


def _evidence_from_following(lines, index):
    for follow in lines[index + 1:index + 3]:
        follow = follow.strip().lstrip("-* ").strip()
        if follow.startswith(("#", "|")) or _match_runbook_result(follow):
            break
        match = re.match(r"^证据[:：]\s*(.+)$", follow)
        if match:
            return match.group(1).strip()
    return ""


def _check_backup(problems, result, evidence, project):
    if result not in BACKUP_OK:
        problems.append("备份结果不是通过/完成/成功: %s" % (result or "空"))
    problem = evidence_problem(evidence, project)
    if problem:
        problems.append("备份" + problem)


def _check_restore(problems, result, evidence, details, project):
    if result not in BACKUP_OK:
        problems.append("恢复演练结果不是通过/完成/成功: %s" % (result or "空"))
    proof = RESTORE_ROWS_RE.sub("；", evidence)
    proof = RESTORE_CHECKSUM_RE.sub("；", proof).strip(" ，,。;；")
    problem = evidence_problem(proof, project)
    if problem:
        problems.append("恢复演练" + problem)
    counts = RESTORE_ROWS_RE.search(details)
    checksum = RESTORE_CHECKSUM_RE.search(details)
    if not counts or not checksum:
        problems.append("恢复演练缺少行数或校验和")
        return
    left, right = int(counts.group(1)), int(counts.group(2))
    sum_left = checksum.group(1).lower()
    sum_right = checksum.group(2).lower()
    if (left == 0 or left != right
            or set(sum_left) <= {"0"} or sum_left != sum_right):
        problems.append("恢复演练行数或校验和不一致")


def backup_result_problems(text, project):
    parts = re.split(r"^#{1,2}[ \t]+([^\r\n]+)\r?$", text, flags=re.M)
    sections = [(title.strip(), body) for title, body in zip(parts[1::2], parts[2::2])]
    current = [body for title, body in sections if title == "备份与恢复"]
    if len(current) > 1:
        return ["备份与恢复章节重复。只保留本轮记录。"]
    if current:
        lines = current[0].splitlines()
    else:
        # 旧手册用两个独立标题。保留标题以隔开证据记录。
        legacy = ["## " + title + body for title, body in sections
                  if title in ("备份", "恢复演练")]
        lines = "\n".join(legacy).splitlines()
    problems = []
    found_backup = False
    found_restore = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        bullet = stripped.lstrip("-* ").strip()
        if bullet.startswith("|"):
            cells = [clean(cell) for cell in bullet.strip("|").split("|")]
            label = _label(cells[0]) if cells else ""
            if len(cells) >= 2 and label == "备份":
                found_backup = True
                _check_backup(
                    problems, cells[1], cells[2] if len(cells) > 2 else "",
                    project)
            elif len(cells) >= 2 and label == "恢复演练":
                found_restore = True
                details = cells[2] if len(cells) > 2 else ""
                _check_restore(
                    problems, cells[1], details, details, project)
            continue
        record = _match_runbook_result(bullet)
        if not record:
            continue
        label, value = record.groups()
        result, evidence = _split_result_evidence(value.strip())
        if not evidence:
            evidence = _evidence_from_following(lines, index)
        if label == "备份":
            found_backup = True
            _check_backup(problems, result, evidence, project)
        else:
            found_restore = True
            _check_restore(
                problems, result, evidence, "%s %s" % (value, evidence),
                project)
    if not found_backup:
        problems.append("缺少备份结果行")
    if not found_restore:
        problems.append("缺少恢复演练结果行")
    return problems


def open_blockers(text):
    rows = teamdef.table_rows(text, "## 阻塞项")
    header = next((row for row in rows if row[0] in ("#", "编号")), None)
    description_index = 1
    state_index = None
    if header:
        if header.count("状态") != 1 or header.count("描述") != 1:
            raise teamdef.StatusFormatError("阻塞项表须有一列状态和一列描述")
        state_index = header.index("状态")
        description_index = header.index("描述")

    blocked = []
    for cells in rows:
        if cells is header or len(cells) < 2:
            continue
        # 兼容没有表头的旧行。状态在六列及七列布局中都位于末尾。
        index = state_index if state_index is not None else (6 if len(cells) >= 7 else 5)
        outcome = cells[index].upper() if index < len(cells) else ""
        if outcome not in CLOSED_BLOCKERS:
            description = cells[description_index] if description_index < len(cells) else ""
            blocked.append(description or "阻塞项 %s" % cells[0])
    return blocked


def parse_status(path):
    """解析 docs/status.md 的模式、门禁和工件。"""
    text = read(path, newline="")
    gates, artifacts = teamdef.status_record_rows(text)
    status = {"mode": "", "ui": "", "backend": "", "profile": "", "release": "",
              **teamdef.status_fields(text), "gates": {}, "artifacts": {},
              "confirmations": {}, "blockers": open_blockers(text), "source_text": text}
    for gate_id, cells in gates.items():
        status["gates"][gate_id] = {
            "name": cells[1],
            "status": cells[2].lower(),
            "owner": cells[3],
            "rework": cells[4],
            "missing": cells[5] if len(cells) > 5 else "",
        }
    for rel, cells in artifacts.items():
        status["artifacts"][rel] = {
            "status": cells[1].upper(),
            "version": cells[2] if len(cells) > 2 else "",
            "owner": cells[3] if len(cells) > 3 else "",
        }
    for cells in teamdef.table_rows(text, "## 人工确认"):
        if len(cells) < 4 or cells[0] == "门":
            continue
        status["confirmations"].setdefault(cells[0], []).append({
            "person": cells[1],
            "time": cells[2],
            "conclusion": cells[3],
        })
    return status


def normalize_owner(value):
    return re.sub(r"\s+", "", value or "")


def owner_names(owner, aliases):
    """负责人可写的名字: 角色 ID 和岗位名。"""
    names = [owner]
    names.extend(aliases.get(owner, ()))
    return names


def owner_ok(actual, names):
    value = normalize_owner(actual)
    return any(value == normalize_owner(name) for name in names if name)


def has_content(path):
    """文件非空，或目录至少有一个非空文件。"""
    try:
        if path.is_dir():
            return any(item.is_file() and item.stat().st_size > 0
                       for item in path.rglob("*"))
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def check_review(path, text=None):
    """评审报告必须有通过结论。未替换的模板结论视为失败。"""
    if text is None:
        text = read(path)
    match = re.search(r"^#{1,6}\s*结论[:：]\s*(.+)$", text, re.M)
    if not match:
        return ["%s 缺少结论" % path.name]
    verdict = match.group(1).strip()
    plain = verdict.strip(" \t*`_")
    if POSITIVE_REVIEW_RE.match(plain):
        if (("需返工" in verdict or "需要返工" in verdict)
                and "无需返工" not in verdict):
            return ["%s 结论不是通过: %s" % (path.name, verdict)]
        return []
    return ["%s 结论不是通过: %s" % (path.name, verdict)]


def artifact_problems(project, rel, status, require_pass,
                      artifact_owners, aliases, sections=()):
    """检查一个工件。返回 (问题列表, 是否存在)。"""
    problems = []
    path = project / rel
    if not path.exists():
        return ["缺少工件: %s" % rel], False
    entry = status["artifacts"].get(rel)
    version_required = scoped_change(status)
    if path.is_dir():
        if version_required:
            problems.append("%s 需要包含本次变更版本的工件文件" % rel)
        elif not has_content(path):
            problems.append("工件目录为空: %s" % rel)
    else:
        try:
            size = path.stat().st_size
        except OSError as exc:
            return ["无法读取工件: %s（%s）" % (rel, exc)], True
        if size == 0:
            return ["工件为空: %s" % rel], True
        text = read(path)
        for keyword in CONTENT_RULES.get(rel, ()):
            if keyword not in text:
                problems.append("%s 缺少章节或内容: %s" % (rel, keyword))
        for keyword in sections:
            if keyword not in text:
                problems.append("%s 缺少配置要求的章节: %s" % (rel, keyword))
        result_fields = ()
        if version_required and rel == "docs/04-test-report.md":
            result_fields = ("回归结果", "准出结论")
        elif status["mode_id"] == "hotfix" and rel == "docs/04-security-report.md":
            result_fields = ("准出结论",)
        for field in result_fields:
            values = re.findall(r"^[ \t]*%s[:：][ \t]*(.*)$" % field, text, re.M)
            if len(values) != 1 or clean(values[0]).upper() not in ("通过", "PASS"):
                problems.append("%s 的%s需明确写通过" % (rel, field))
        if rel == "docs/06-ops.md" and status.get("database") != "无":
            problems.extend("%s %s" % (rel, problem)
                           for problem in backup_result_problems(text, project))
        for marker in PLACEHOLDERS:
            if marker in text:
                problems.append("%s 含未填写内容: %s" % (rel, marker))
        versions = VERSION_RE.findall(text)
        if version_required:
            change_id = status.get("change_id", "")
            if len(versions) != 1 or clean(versions[0]) != change_id:
                problems.append("%s 的版本不属于本次变更 %s" % (rel, change_id))
            if entry is not None and clean(entry["version"]) != change_id:
                problems.append("%s 的状态板版本未登记本次变更 %s" % (rel, change_id))
        elif versions and entry is not None and entry.get("version"):
            if versions[0] != entry["version"].strip("`"):
                problems.append("%s 版本是 %s，状态板登记 %s" % (
                    rel, versions[0], entry["version"]))
        if rel == "docs/01-requirements.md" and "TBD" in text:
            problems.append("%s 仍含 TBD" % rel)
        if rel.startswith(REVIEW_PREFIX):
            problems.extend(check_review(path, text))

    expected_owner = artifact_owners.get(rel, "")
    if expected_owner:
        if entry is None:
            if require_pass:
                problems.append("状态板缺少工件行: %s" % rel)
        else:
            actual_owner = entry.get("owner", "")
            if not actual_owner:
                problems.append("状态板缺少工件负责人: %s" % rel)
            elif not owner_ok(actual_owner,
                              owner_names(expected_owner, aliases)):
                problems.append("%s 负责人是 %s，应为 %s" % (
                    rel, actual_owner, expected_owner))
            if require_pass:
                if entry["status"] == "BLOCKED":
                    problems.append("%s 状态为 BLOCKED" % rel)
                elif entry["status"] != "APPROVED":
                    problems.append("%s 状态为 %s，不是 APPROVED" % (
                        rel, entry["status"] or "空"))
    return problems, True


REQUIREMENT_RE = re.compile(r"\b(?:REQ|NFR)-\d{3}\b")


def mapped_ids(text):
    """返回出现在映射行中的需求 ID。只有 ID 的行不算映射。"""
    mapped = set()
    for line in text.splitlines():
        ids = REQUIREMENT_RE.findall(line)
        if not ids:
            continue
        rest = REQUIREMENT_RE.sub("", line)
        rest = re.sub(r"[\s|`*_#>~\-—:：,，;；.。()（）\[\]【】/]+", "", rest)
        if rest:
            mapped.update(ids)
    return mapped


def coverage_problems(project, gate_id):
    """检查需求 ID 是否以映射行进入设计和测试。"""
    if gate_id not in ("G2", "G4"):
        return []
    requirements = project / "docs" / "01-requirements.md"
    if not requirements.exists():
        return []
    all_ids = sorted(set(REQUIREMENT_RE.findall(read(requirements))))
    if not all_ids:
        return []
    ids = all_ids
    if gate_id == "G2":
        target = project / "docs" / "02-design.md"
        label = "设计未映射需求"
        target_label = "设计"
    else:
        target = project / "docs" / "04-test-report.md"
        label = "测试报告未覆盖需求"
        target_label = "测试报告"
        ids = [item for item in ids if item.startswith("REQ-")]
    if not target.exists():
        return []
    text = read(target)
    found = set(REQUIREMENT_RE.findall(text))
    known = set(all_ids)
    problems = []
    mapped = mapped_ids(text)
    missing = [item for item in ids if item not in mapped]
    if missing:
        problems.append("%s %s: %s" % (gate_id, label, "、".join(missing)))
    unknown = sorted(found - known)
    if unknown:
        problems.append("%s %s含未登记需求 ID: %s" % (
            gate_id, target_label, "、".join(unknown)))
    return problems


def check_gate(project, gate, status, require_pass, rework_limit,
               artifact_owners, aliases, human_gates=()):
    """检查一个门。返回问题列表。"""
    problems = []
    gate_id = gate.get("id", "?")
    if (status["mode_id"] == "hotfix" and gate.get("artifacts_hotfix_security")
            and status.get("hotfix_security") not in ("有", "无")):
        problems.append("状态板的热修安全影响需明确填写有或无")
    row = status["gates"].get(gate_id)
    if row is None:
        problems.append("状态板缺少门禁行: %s" % gate_id)
    else:
        owner_id = gate.get("gate_owner", "")
        expected = teamdef.GATE_OWNER_LABELS.get(owner_id, owner_id)
        allowed = [expected] + aliases.get(owner_id, [])
        actual = row.get("owner", "")
        if not actual:
            problems.append("%s 状态板缺少门负责人" % gate_id)
        elif not owner_ok(actual, allowed):
            problems.append("%s 门负责人是 %s，应为 %s" % (
                gate_id, actual, expected))
        try:
            if int(row["rework"]) > rework_limit:
                problems.append("%s 返工次数 %s 超过 %d" % (
                    gate_id, row["rework"], rework_limit))
        except ValueError:
            problems.append("%s 返工次数不是数字: %s" % (
                gate_id, row["rework"]))
        if require_pass and row["status"] != "pass":
            problems.append("%s 状态为 %s，不是 pass" % (
                gate_id, row["status"] or "空"))
        elif row["status"] in ("n/a", "na"):
            problem = na_problem(gate, row)
            if problem:
                problems.append("%s %s" % (gate_id, problem))

    artifacts, any_of, sections = gate_artifacts(gate, status, project)
    if not artifacts and not any_of:
        problems.append("%s 未登记必需工件" % gate_id)
    if any_of:
        valid = False
        invalid = []
        for rel in any_of:
            rel_problems, exists = artifact_problems(
                project, rel, status, require_pass, artifact_owners, aliases)
            if exists and not rel_problems:
                valid = True
                break
            if exists:
                invalid.extend(rel_problems)
        if not valid:
            problems.append("%s 缺少任一有效工件: %s" % (
                gate_id, "、".join(any_of)))
            problems.extend(invalid)

    for rel in artifacts:
        rel_problems, _ = artifact_problems(
            project, rel, status, require_pass, artifact_owners, aliases,
            sections.get(rel, ()))
        problems.extend(rel_problems)
    if not scoped_change(status):
        problems.extend(coverage_problems(project, gate_id))

    if (require_pass and gate.get("gate_owner") in teamdef.HUMAN_GATE_OWNERS
            and row is not None and row["status"] == "pass"):
        entries = status.get("confirmations", {}).get(gate_id, [])
        if gate_id in human_gates:
            problems.extend(approval_problems(project, gate, entries, status))
        elif not entries or not all(has_value(value) for value in entries[-1].values()):
            problems.append("%s 缺少人工确认记录" % gate_id)
        elif any(not confirmation_matches_gate(gate_id, entry["conclusion"]) for entry in entries):
            problems.append("%s 人工确认结论须明确同意本门事项。请核对实际决定。" % gate_id)
    return problems


def sync_artifacts(project, status, data, active_gates, dry_run=False):
    """把已存在但未登记的工件补进产出物表。只增加 DRAFT 行。"""
    rows = []
    registered = set(status["artifacts"])
    for gate in data["gates"]:
        gate_id = gate.get("id", "")
        row = status["gates"].get(gate_id)
        if gate_id not in active_gates:
            continue
        if row and row["status"] in ("n/a", "na") and not na_problem(gate, row):
            continue
        artifacts, any_of, _ = gate_artifacts(gate, status, project)
        for rel in artifacts + any_of:
            if rel in registered:
                continue
            path = project / rel
            if not path.exists():
                continue
            version = "-"
            if path.is_file():
                match = VERSION_RE.search(read(path))
                if match:
                    version = match.group(1).strip()
            owner = data["artifacts"].get(rel, "")
            if not owner:
                continue
            rows.append("| %s | DRAFT | %s | %s | %s | %s |" % (
                rel, version, owner, gate_id, date.today().isoformat()))
            registered.add(rel)
    if not rows:
        print("没有缺失的产出物行")
        return 0
    path = project / "docs" / "status.md"
    snapshot = status["source_text"]
    lines = snapshot.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if line.strip() == "## 产出物":
            start = index
            break
    if start is None:
        print("状态板缺少产出物章节")
        return 2
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    last_table = None
    for index in range(start, end):
        if lines[index].lstrip().startswith("|"):
            last_table = index
    if last_table is None:
        print("状态板缺少产出物表")
        return 2
    if dry_run:
        print("将补充 %d 行产出物:" % len(rows))
        for row in rows:
            print(row)
        return 0
    require_status_snapshot(path, snapshot)
    newline = "\r\n" if lines[last_table].endswith("\r\n") else "\n"
    if not lines[last_table].endswith("\n"):
        lines[last_table] += newline
    lines[last_table + 1:last_table + 1] = [row + newline for row in rows]
    backup = path.with_name(path.name + ".bak")
    write_atomic(backup, snapshot)
    write_atomic(path, "".join(lines), expected=snapshot)
    print("已补充 %d 行产出物" % len(rows))
    print("原状态板备份: %s" % backup)
    return 0


def run():
    parser = argparse.ArgumentParser(description="检查项目门禁")
    parser.add_argument("--gate", default="passed",
                        help="门 ID、passed 或 all")
    parser.add_argument("--require-pass", action="store_true",
                        help="复核指定门的通过状态和已批准工件")
    parser.add_argument("--project", default="",
                        help="项目根目录。默认自动判断")
    parser.add_argument("--quiet", action="store_true",
                        help="只输出失败项")
    parser.add_argument("--allow-empty", action="store_true",
                        help="没有 pass 门时返回 0，供预提交钩子使用")
    parser.add_argument("--fail-on-fail", action="store_true",
                        help="--gate passed 时，任一 fail 门返回 1")
    parser.add_argument("--sync-artifacts", action="store_true",
                        help="把已存在但未登记的工件补进产出物表")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示 --sync-artifacts 将补充的行，不写文件")
    args = parser.parse_args()
    if args.dry_run and not args.sync_artifacts:
        print("--dry-run 只用于 --sync-artifacts")
        return 2

    project = teamdef.resolve_project(args.project)
    status_path = project / "docs" / "status.md"
    if not status_path.exists():
        print("门禁检查失败: 缺少 %s" % status_path)
        print("先让总控初始化状态板: docs/status.md")
        return 2
    if args.sync_artifacts and not args.dry_run:
        with teamdef.lock_file(status_path):
            return run_project(args, project, status_path)
    return run_project(args, project, status_path)


def run_project(args, project, status_path):
    try:
        status = parse_status(status_path)
    except teamdef.StatusFormatError as exc:
        print("状态板格式错误: %s" % exc)
        return 2
    try:
        data = teamdef.parse_team_yaml()
    except (OSError, UnicodeError, ValueError) as exc:
        print("团队定义读取失败: %s" % exc)
        return 2
    gates = {gate.get("id"): gate for gate in data["gates"]}
    unknown = sorted(set(status["gates"]) - set(gates))
    if unknown:
        print("状态板含未知门: %s" % "、".join(unknown))
        print("允许值: %s" % "、".join(
            gate.get("id", "") for gate in data["gates"]))
        return 2
    if not status["mode"]:
        print("状态板缺少模式: docs/status.md")
        return 2
    mode_id = teamdef.resolve_mode_id(data, status["mode"])
    if not mode_id and status["mode"] != "未判定":
        known_modes = {"未判定", *data["modes"]}
        known_modes.update(mode["label"] for mode in data["modes"].values() if mode.get("label"))
        print("状态板模式无效: %s" % status["mode"])
        print("允许值: %s" % "、".join(sorted(known_modes)))
        return 2
    profiles = data.get("profiles", {})
    profile_value = status.get("profile", "").strip()
    if profile_value and not any(
            profile_value in (key, profile.get("label", ""),
                              profile.get("label", "") + "项目")
            for key, profile in profiles.items()):
        print("状态板规模配置无效: %s" % profile_value)
        print("允许值: %s" % "、".join(
            profile.get("label", key) for key, profile in profiles.items()))
        return 2
    status["profile_config"] = active_profile(data, status)
    status["mode_id"] = mode_id
    active_gates = teamdef.mode_gate_ids(data, mode_id)
    if not active_gates:
        if (status["mode"] == "未判定" and args.gate == "passed"
                and args.allow_empty and not args.sync_artifacts
                and all(row["status"] == "pending" for row in status["gates"].values())):
            return 0
        print("先在 docs/status.md 选择项目模式。当前模式没有适用门。")
        return 2
    if scoped_change(status):
        status["change_id"] = change_id = clean(status.get("change_id", ""))
        if not has_value(change_id) or re.search(r"\s", change_id):
            print("%s需要本次变更编号。填写一个唯一编号，例如 %s-013。" % (
                data["modes"][mode_id].get("label", mode_id),
                "CHANGE" if mode_id == "quick" else "HOTFIX"))
            return 2
    if mode_id == "quick":
        ui, backend = status["ui"], status["backend"]
        ui_on, backend_on = ui.startswith("有"), backend.startswith("有")
        if (not (ui_on or backend_on) or not (ui_on or ui in UI_OFF)
                or not (backend_on or backend in BACKEND_OFF)):
            print("轻量变更需明确填写界面和后端范围。至少一项写有。")
            return 2
    active_rows = {gate_id: status["gates"][gate_id] for gate_id in active_gates
                   if gate_id in status["gates"]}
    if args.sync_artifacts:
        return sync_artifacts(
            project, status, data, active_gates, dry_run=args.dry_run)
    if args.gate == "all" or (args.gate in active_gates and args.require_pass):
        if status["blockers"]:
            print("[FAIL] 状态板有未关闭的阻塞项")
            for blocker in status["blockers"]:
                print("       - %s" % blocker)
            return 1
    release = status.get("release", "").strip()
    if release and release not in RELEASE_STATES:
        print("状态板发布状态无效: %s" % release)
        print("本团队只做验证上线。允许值: 验证上线")
        return 2
    try:
        rework_limit = int(data["rules"].get("rework_limit", "2"))
    except ValueError:
        rework_limit = 2
    artifact_owners = data["artifacts"]
    human_gates = set(teamdef.parse_list(
        data["rules"].get("human_approval_required")))
    aliases = {}
    for agent in data["agents"]:
        agent_id = agent.get("id", "")
        if not agent_id:
            continue
        names = [agent_id]
        title = agent.get("title", "")
        if title:
            names.append(title)
        aliases[agent_id] = names
    profile = status["profile_config"]
    for primary, covered in teamdef.parse_pairs(profile.get(
            "owner_aliases", profile.get("merge_roles", ""))).items():
        primary_names = [primary] + aliases.get(primary, [])
        for role in covered:
            aliases.setdefault(role, [])
            for name in primary_names:
                if name not in aliases[role]:
                    aliases[role].append(name)

    if args.fail_on_fail and args.gate == "passed":
        failed_gates = [gate_id for gate_id, row in active_rows.items()
                        if row["status"] == "fail"]
        if failed_gates:
            if not args.quiet:
                print("存在失败门: %s" % "、".join(failed_gates))
            return 1

    if args.gate == "all":
        targets = active_gates
        require_pass = True
    elif args.gate == "passed":
        invalid_na = [(gate_id, na_problem(gates[gate_id], row))
                      for gate_id, row in active_rows.items()
                      if row["status"] in ("n/a", "na")]
        if any(problem for _, problem in invalid_na):
            for gate_id, problem in invalid_na:
                if problem:
                    print("[FAIL] %s - %s" % (gate_id, problem))
            return 1
        targets = [gate_id for gate_id, row in active_rows.items()
                   if row["status"] == "pass"]
        if not targets:
            blocking = [gate_id for gate_id, row in active_rows.items()
                        if row["status"] in ("fail", "pending")]
            if not args.quiet:
                print("没有标记 pass 的门。")
                print("当前模式: %s" % (status["mode"] or "未判定"))
                if blocking:
                    print("注意: 还有 %d 个门未通过: %s。整体验收请用 --gate all。" % (
                        len(blocking), "、".join(blocking)))
            if args.allow_empty:
                return 0
            return 1 if blocking else 0
        require_pass = True
    else:
        if args.gate not in gates:
            print("未知门: %s" % args.gate)
            return 2
        if args.gate not in active_gates:
            print("当前模式不适用 %s。适用门为 %s。" % (
                args.gate, "、".join(active_gates)))
            return 2
        targets = [args.gate]
        require_pass = args.require_pass

    failed = 0
    checked = 0
    pending = 0
    na = 0
    checked_checks = 0
    auto_checks = 0
    for gate_id in targets:
        gate = gates.get(gate_id)
        if gate is None:
            continue
        row = status["gates"].get(gate_id, {})
        if args.gate == "all" and row.get("status") != "pass":
            value = (row.get("status") or "pending").lower()
            if value in ("n/a", "na"):
                problem = na_problem(gate, row)
                if problem:
                    failed += 1
                    print("[FAIL] %s %s - %s" % (gate_id, gate.get("name", ""), problem))
                    continue
                na += 1
                label = "N/A"
            elif value == "fail":
                failed += 1
                label = "FAIL"
            else:
                pending += 1
                label = value.upper()
            if not args.quiet:
                missing = row.get("missing", "")
                suffix = " - %s" % missing if missing else ""
                print("[%s] %s %s%s" % (
                    label, gate_id, gate.get("name", ""), suffix))
            continue
        checked += 1
        checks = gate_checks(gate, status)
        checked_checks += len(checks)
        auto_checks += sum(1 for check in checks
                           if check.strip().startswith("[自动]"))
        problems = check_gate(
            project, gate, status, require_pass, rework_limit,
            artifact_owners, aliases, human_gates)
        label = "%s %s" % (gate_id, gate.get("name", ""))
        if problems:
            failed += 1
            print("[FAIL] %s" % label)
            for problem in problems:
                print("       - %s" % problem)
        elif not args.quiet:
            print("[%s] %s" % ("PASS" if require_pass else "READY", label))

    if not args.quiet:
        if args.gate == "all":
            all_checks = [check for gate_id in targets
                          for check in gate_checks(gates[gate_id], status)]
            total_checks = len(all_checks)
            auto_total = sum(check.strip().startswith("[自动]") for check in all_checks)
            print("自动检查 %d 个门，失败 %d 个。未开始 %d 个。不适用 %d 个。" % (
                checked, failed, pending, na))
            if pending:
                print("整体验收未通过: 还有 %d 个门未开始。" % pending)
            print("适用门定义 %d 条检查项: 标注 [自动] %d 条，人工 %d 条。" % (
                total_checks, auto_total, total_checks - auto_total))
            if checked:
                print("本次检查 %d 个门，共 %d 条检查项。" % (
                    checked, checked_checks))
            hotfix_total = len(data.get("hotfix_checks") or [])
            if hotfix_total and mode_id == "hotfix":
                print("热修流程另有 %d 条人工检查项，见 protocol.md 第 4 节。" % (
                    hotfix_total))
        else:
            print("自动检查 %d 个门，失败 %d 个。" % (checked, failed))
            print("门禁共 %d 条检查项: 标注 [自动] %d 条，人工 %d 条。" % (
                checked_checks, auto_checks, checked_checks - auto_checks))
        if args.gate == "passed":
            waiting = [gate_id for gate_id, row in active_rows.items()
                       if row["status"] in ("fail", "pending")]
            if waiting:
                print("注意: 还有 %d 个门未通过: %s。整体验收请用 --gate all。" % (
                    len(waiting), "、".join(waiting)))
        print("脚本另检查: 工件存在、非空、版本、发布状态、占位符、"
              "评审结论、人工确认、n/a 原因、人工批准记录、"
              "适用的热修安全复核与 G6 恢复证据。")
    return 1 if (failed or pending) else 0


def main():
    try:
        return run()
    except (GateInputError, teamdef.StatusFormatError, OSError, UnicodeError) as exc:
        print("门禁检查失败: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
