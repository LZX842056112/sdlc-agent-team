# 软件交付专家团

<!-- RENDER:RELEASE_HEADER:BEGIN -->
当前版本 `1.0.0` · 12 个角色
<!-- RENDER:RELEASE_HEADER:END -->

## 项目简介

软件交付专家团（SDLC Agent Team）为软件项目提供角色卡、交付门和项目工具。总控根据任务范围派发工作。各角色将结果写入项目，由指定的门负责人核对后推进。

## 功能说明

- 按任务影响选择流程。选择适用的角色、工件和检查条件。
- 分派需求、体验和架构设计、实现、验证、独立评审、发布运维及复盘工作。
- 用项目状态板记录进度、工件、确认事项和阻塞。用命令行工具核对当前门所需的材料。
- 在授权的验证环境开展发布和运行验证。生产操作交给有权限的人办理。
- 用本地看板查看阶段进度和角色交接。

### 交付模式

总控按表中顺序选择第一个符合条件的模式。

<!-- RENDER:README_OVERVIEW:BEGIN -->
| 模式 | 适用条件 | 适用门 |
|---|---|---|
| 热修 | 线上故障需要立即修复 | G3 → G4 → G5 |
| 轻量变更 | 已有项目只改局部行为，且权限、接口契约、数据、依赖、设计决策、性能指标和部署均不受影响 | G3 → G4 |
| 迭代 | 从复盘或需求池开始，且本次变更可复用已批准的项目章程和现状基线 | G1 → G2 → G3 → G4 → G5 → G6 → G7 |
| 二次开发 | 修改已有系统，需要核对现有行为、接口契约或数据 | G0B → G0 → G1 → G2 → G3 → G4 → G5 → G6 → G7 |
| 新建 | 首次交付，且无需沿用已有系统的行为、接口契约或数据 | G0 → G1 → G2 → G3 → G4 → G5 → G6 → G7 |
<!-- RENDER:README_OVERVIEW:END -->

[角色与工件](AGENTS.md) · [交付协议](protocol.md)

## 安装与运行

准备 Python 3.8 或更高版本。安装和项目工具使用 Python 标准库。

在本仓库根目录运行命令。将 `../delivery-project` 换成目标项目路径，将 `codex` 换成使用的平台 ID。选择 `all` 可生成全部项目入口。

```sh
python bin/install.py --platform codex --target "../delivery-project"
```

安装器把团队资源写入目标项目的 `sdlc-agent-team/`，并初始化 `docs/status.md`。Claude Code、Trae、WorkBuddy 等平台的安装方式见[平台指南](PLATFORMS.md)。

在目标项目中发起交付任务。

```text
读取 sdlc-agent-team/AGENTS.md 和 sdlc-agent-team/team/00-orchestrator.md。
为报表列表增加按业务日期筛选的能力。先确认影响和验收范围，再由总控推进。
```

在目标项目根目录运行需要的工具。

```sh
python sdlc-agent-team/tools/audit.py --project .
python sdlc-agent-team/tools/gates.py --gate all
python sdlc-agent-team/tools/dashboard.py --project .
```

`audit.py` 汇总仓库现状。`gates.py` 检查适用门。`dashboard.py` 启动本地看板，默认地址为 `http://127.0.0.1:8765`。 [运行命令](protocol.md#命令行操作)

## 配置说明

- `team.yaml` 是配置源。`version` 记录发布版本。`agents`、`routes` 和 `artifacts` 登记人员角色、任务分派与工件归属。
- `modes`、`stages`、`hotfix_stages`、`gates` 和 `rules` 定义交付阶段、所需材料、门负责人和返工规则。
- `profiles` 定义 `标准` 和 `小` 两种规模。总控在目标项目的状态板选择规模。小项目按配置合并工件。
- `monitoring.flow_state` 设置活动记录路径。`monitoring.refresh_seconds` 设置看板刷新间隔。
- 轻量变更和热修使用本次唯一的变更编号。总控在热修 H0 登记安全影响，在 G6 前确认验证环境的数据库状态。

## 目录结构

```text
sdlc-agent-team/
├── README.md           项目说明和上手入口
├── PLATFORMS.md        平台安装指南
├── AGENTS.md           团队配置的阅读入口
├── protocol.md         门禁、交接与命令
├── CLAUDE.md           Claude Code 项目指引
├── SKILL.md            Trae 技能入口
├── team.yaml           团队配置源
├── team/               角色卡
├── templates/          状态板与交付工件模板
├── tools/              现状审计、门禁和监控工具
├── bin/                安装、渲染和一致性校验
├── .claude/            Claude Code 项目角色入口
├── .claude-plugin/     插件市场清单
└── plugins/            生成的 Claude Code 插件包
```

工作记录和工件写入目标项目自己的 `docs/`。按[工件模板索引](templates/README.md)选择文件。

## 开发使用说明

1. 在 `team.yaml` 更新团队配置。各角色的执行方法在 `team/` 中维护。
2. 在 `templates/` 更新工件格式。同步维护模板索引中的文件和输出路径。
3. 在源码目录生成文档区块和插件，然后校验包内容。

```sh
python bin/render.py
python bin/install.py --build-plugin plugins/sdlc-agent-team
python bin/validate.py --source-only
```

[MIT 许可证](LICENSE)
