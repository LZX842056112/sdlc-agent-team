#!/usr/bin/env python3
"""审计项目现状。只读，不改文件。

输出内容:
1. 代码文件数量、代码行数和语言分布。
2. 测试文件、文档文件数量。
3. 风险信号。
4. 大文件和技术债热区。
5. TODO 与 FIXME 数量。

用法:
    python tools/audit.py --project <项目>
    python tools/audit.py --project . --json

跳过已安装的专家团目录和生成文件 `*.d.ts`。
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "dist", "build",
    "target", "coverage", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".pdfbuild", ".idea", ".vscode", ".next", "out",
    ".claude", ".trae", ".workbuddy", ".agents", ".cursor",
}
LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".php": "PHP",
    ".rb": "Ruby",
    ".cs": "C#",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".swift": "Swift",
    ".css": "CSS",
    ".scss": "SCSS",
    ".less": "Less",
    ".html": "HTML",
    ".sql": "SQL",
}
OTHER_TEXT = {
    ".css", ".scss", ".less", ".html", ".sql", ".sh", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".md", ".json",
}
MAX_BYTES = 2 * 1024 * 1024
LARGE_LINES = 800
TODO = re.compile(r"\b(TODO|FIXME)\b")
CI_FILES = (
    ".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml",
    "bitbucket-pipelines.yml", ".circleci/config.yml",
)


def has_ci(project):
    workflows = project / ".github" / "workflows"
    if list(workflows.glob("*.yml")) or list(workflows.glob("*.yaml")):
        return True
    return any((project / name).exists() for name in CI_FILES)


def is_test(path):
    if path.suffix.lower() not in (
            ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".java",
            ".kt", ".go", ".rs", ".php", ".rb", ".cs"):
        return False
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if "tests" in parts or "__tests__" in parts:
        return True
    if name.startswith("test_") or name.endswith(("_test.py", "_test.go")):
        return True
    return ".test." in name or ".spec." in name


def is_team_core(path):
    """识别已安装的专家团目录。"""
    return (path.name == "sdlc-agent-team"
            and (path / "team.yaml").exists()
            and (path / "AGENTS.md").exists())


def walk(project):
    """列出可读文本文件，跳过依赖、专家团和大目录。"""
    files = []
    for root, dirs, names in os.walk(project):
        root_path = Path(root)
        dirs[:] = [name for name in dirs
                   if name not in SKIP_DIRS
                   and not is_team_core(root_path / name)]
        for name in names:
            path = root_path / name
            try:
                if path.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            files.append(path)
    return files


def gitignore_lines(project):
    path = project / ".gitignore"
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(
        encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.strip().startswith("#")]


def env_is_ignored(project, lines):
    try:
        result = subprocess.run(
            ["git", "-C", str(project), "check-ignore", "-v", "-z", "--stdin"],
            input=b".env\0", stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        pass
    else:
        if result.returncode == 0:
            _, _, pattern, _ = result.stdout.split(b"\0", 3)
            return not pattern.startswith(b"!")
        if result.returncode == 1:
            return False
    return any(line in (".env", "/.env", "**/.env") for line in lines)


def risk_signals(project, has_tests):
    signals = []
    lines = gitignore_lines(project)
    if any(line in ("lib/", "lib", "**/lib/", "**/lib") for line in lines):
        signals.append(("高", ".gitignore 含 lib/ 规则",
                        "可能忽略源码目录，例如 frontend/src/lib"))
    if (project / ".env").exists() and not env_is_ignored(project, lines):
        signals.append(("高", ".env 存在且未被忽略",
                        "检查 .env 的有效忽略规则"))
    if not has_ci(project):
        signals.append(("中", "缺少 CI 工作流", "没有自动构建和测试"))
    if not has_tests:
        signals.append(("高", "没有测试文件", "先补特征测试"))
    locks = [name for name in (
        "uv.lock", "poetry.lock", "Pipfile.lock", "package-lock.json",
        "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "go.sum",
        "Cargo.lock", "composer.lock", "packages.lock.json",
        "mix.lock") if (project / name).exists()]
    if not locks:
        signals.append(("中", "缺少依赖锁文件", "构建结果不可复现"))
    if not (project / "docs").exists():
        signals.append(("中", "缺少 docs 目录", "交付物没有落盘位置"))
    return signals


def summarize(project):
    files = walk(project)
    languages = {}
    tests = []
    docs = []
    large = []
    todos = 0

    for path in files:
        suffix = path.suffix.lower()
        generated = path.name.endswith(".d.ts")
        if is_test(path):
            tests.append(str(path.relative_to(project)))
        if suffix == ".md":
            docs.append(str(path.relative_to(project)))
        if generated:
            continue
        text = None
        if suffix in LANGUAGES or suffix in OTHER_TEXT:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = None
        lines = text.count("\n") + 1 if text is not None else 0
        if suffix in LANGUAGES:
            item = languages.setdefault(
                LANGUAGES[suffix], {"files": 0, "lines": 0})
            item["files"] += 1
            item["lines"] += lines
            if lines > LARGE_LINES:
                large.append({
                    "file": str(path.relative_to(project)).replace("\\", "/"),
                    "lines": lines,
                })
        if text is not None:
            todos += len(TODO.findall(text))

    large.sort(key=lambda item: item["lines"], reverse=True)
    total_files = sum(item["files"] for item in languages.values())
    total_lines = sum(item["lines"] for item in languages.values())
    return {
        "project": str(project),
        "source_files": total_files,
        "source_lines": total_lines,
        "languages": languages,
        "test_files": len(tests),
        "tests": tests[:20],
        "doc_files": len(docs),
        "large_files": large[:10],
        "todo_count": todos,
        "signals": [
            {"level": level, "title": title, "hint": hint}
            for level, title, hint in risk_signals(project, bool(tests))
        ],
    }


def print_report(data):
    print("项目: %s" % data["project"])
    print("代码文件: %d 个" % data["source_files"])
    print("代码行: %d 行" % data["source_lines"])
    print("测试文件: %d 个" % data["test_files"])
    print("文档文件: %d 个" % data["doc_files"])
    print("待办标记: %d 个" % data["todo_count"])

    print("\n语言分布:")
    for name, item in sorted(
            data["languages"].items(), key=lambda kv: kv[1]["lines"],
            reverse=True):
        print("  %-12s %4d 个文件 %8d 行" % (
            name, item["files"], item["lines"]))

    print("\n风险信号:")
    if not data["signals"]:
        print("  无")
    for item in data["signals"]:
        print("  [%s] %s。%s" % (item["level"], item["title"], item["hint"]))

    print("\n大文件:")
    if not data["large_files"]:
        print("  无")
    for item in data["large_files"]:
        print("  %s  %d 行" % (item["file"], item["lines"]))


def main():
    parser = argparse.ArgumentParser(description="审计项目现状")
    parser.add_argument("--project", default=".",
                        help="项目根目录。默认当前目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        print("目录不存在: %s" % project)
        return 2

    data = summarize(project)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_report(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
