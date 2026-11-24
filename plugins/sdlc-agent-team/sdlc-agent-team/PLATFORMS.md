# 平台安装指南

<!-- RENDER:RELEASE_HEADER:BEGIN -->
当前版本 `1.0.0` · 12 个角色
<!-- RENDER:RELEASE_HEADER:END -->

## 项目入口

在专家团源码目录运行安装器。先用 `--dry-run` 查看将生成的文件，再执行安装。

```sh
python bin/install.py --platform codex --target "../delivery-project" --dry-run
python bin/install.py --platform codex --target "../delivery-project"
```

| 平台 | 平台 ID | 安装到目标项目的入口 |
|---|---|---|
| Claude Code | claude | `CLAUDE.md` 和 `.claude/agents/` |
| Codex | codex | `AGENTS.md` |
| Trae | trae | `.trae/skills/sdlc-agent-team/`、`.trae/agents/` 和 `.trae/rules/` |
| Cursor | cursor | `.cursor/rules/` |
| WorkBuddy | workbuddy | `.workbuddy/skills/sdlc-agent-team/` |
| DSH | dsh | `AGENTS.md`、`.agents/skills/` 和 `sdlc-agent-team/DSH_PRESETS.md` |
| 通用 | generic | `AGENTS.md` |

`python bin/install.py --list` 显示平台 ID。用 `--platform all` 生成全部入口。

## 发起任务

在目标项目打开会话。读取 `sdlc-agent-team/AGENTS.md` 和 `sdlc-agent-team/team/00-orchestrator.md`。给出交付目标、改动范围和验收条件。

Claude Code 和 Trae 的项目子角色使用 `sdlc-<角色 ID>`。Trae 可在内置 Agent 选择 `/sdlc-agent-team`。DSH 参考安装后的 `DSH_PRESETS.md` 设置角色入口。工作目录和命令示例见[安装与运行](README.md#安装与运行)。

## Claude Code 插件

在 Claude Code 的会话中添加插件市场并安装专家团。

```text
/plugin marketplace add <本项目目录>
/plugin install sdlc-agent-team@sdlc-agent-team-marketplace
```

用 `/sdlc-agent-team:orchestrator` 发起交付。插件附带角色卡、工件模板和运行工具。

## 用户级技能

在源码目录执行对应平台的命令。

```sh
python bin/install.py --install-skill
python bin/install.py --install-workbuddy
```

Trae 读取 `~/.trae-cn/skills/sdlc-agent-team/`。WorkBuddy 读取 `~/.workbuddy/skills/sdlc-agent-team/`，团队资源位于技能的 `references/`。安装后重新打开 WorkBuddy 加载技能。
