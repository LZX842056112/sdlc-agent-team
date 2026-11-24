# 软件交付专家团（SDLC Agent Team）

<!-- RENDER:RELEASE_HEADER:BEGIN -->
当前版本 `1.0.0` · 12 个角色
<!-- RENDER:RELEASE_HEADER:END -->

## 启动工作

先读[总控角色卡](team/00-orchestrator.md)。用户要求只读评估时，提交依据和结论。需要交付时，先确认目标、约束和验收条件，再选择流程。

目标项目的 `docs/status.md` 记录当前进度。总控维护交付模式、阶段和下一步。门负责人记录评审结论，获授权的人作出所需的批准决定。

## 模式判定

核对仓库状态和变更影响。依次匹配下列条件，使用首个适用的模式。

<!-- RENDER:AGENTS_MODES:BEGIN -->
- 线上故障需要立即修复。使用热修模式。
- 已有项目只改局部行为，且权限、接口契约、数据、依赖、设计决策、性能指标和部署均不受影响。使用轻量变更模式。
- 从复盘或需求池开始，且本次变更可复用已批准的项目章程和现状基线。使用迭代模式。
- 修改已有系统，需要核对现有行为、接口契约或数据。使用二次开发模式。
- 首次交付，且无需沿用已有系统的行为、接口契约或数据。使用新建模式。
<!-- RENDER:AGENTS_MODES:END -->

变更范围扩大时重新判定模式。更新状态板，并从受影响的关口继续。

<!-- RENDER:AGENTS_STATE_MACHINE:BEGIN -->
```
热修: INIT → H0 → H1 → H2 → G3 → H3 → G4 → H4 → G5 → H5 → DONE
轻量变更: INIT → BUILD → G3 → TEST → G4 → DONE
迭代: INIT → REQ → G1 → DESIGN → G2 → BUILD → G3 → TEST → G4 → RELEASE → G5 → OPS → G6 → RETRO → G7 → DONE
二次开发: INIT → G0B → G0 → REQ → G1 → DESIGN → G2 → BUILD → G3 → TEST → G4 → RELEASE → G5 → OPS → G6 → RETRO → G7 → DONE
新建: INIT → G0 → REQ → G1 → DESIGN → G2 → BUILD → G3 → TEST → G4 → RELEASE → G5 → OPS → G6 → RETRO → G7 → DONE
```
<!-- RENDER:AGENTS_STATE_MACHINE:END -->

## 成员与分工

<!-- RENDER:AGENTS_TEAM:BEGIN -->
| 角色 ID | 角色 | 角色卡 | 参与阶段 | 门禁职责 | 交接对象 |
|---|---|---|---|---|---|
| `orchestrator` | 总控 | [00-orchestrator.md](team/00-orchestrator.md) | 全流程；模式选择；热修 H0、H5 | G0、G7 配合人工确认；G0B 就绪检查；G6 门负责人 | 全体角色 |
| `analyst` | 需求专家 | [01-analyst.md](team/01-analyst.md) | 1 立项/变更、2 需求 | G0、G1 交付 | orchestrator、architect |
| `architect` | 设计专家 | [02-architect.md](team/02-architect.md) | 0B 现状基线、3 方案设计 | G0B、G2 交付 | analyst、reviewer、frontend、backend |
| `designer` | 体验设计 | [11-designer.md](team/11-designer.md) | 3 方案设计 | G2 交付 | reviewer、frontend |
| `frontend` | 前端开发 | [03-frontend.md](team/03-frontend.md) | 4 编码开发；热修 H2 | G3 交付 | reviewer、functional-tester |
| `backend` | 后端开发 | [04-backend.md](team/04-backend.md) | 4 编码开发；热修 H2 | G3 交付 | reviewer、functional-tester、performance-tester |
| `functional-tester` | 功能测试 | [05-functional-tester.md](team/05-functional-tester.md) | 5 测试验证（含回归基线）；热修 H0、H3 | G4 交付 | orchestrator、reviewer、releaser |
| `performance-tester` | 性能测试 | [06-performance-tester.md](team/06-performance-tester.md) | 5 测试验证 | G4 交付 | functional-tester、reviewer、backend、releaser |
| `security` | 安全专家 | [07-security.md](team/07-security.md) | 3、4、5，热修 H3（有安全影响） | 安全工件交付 | architect、frontend、backend、reviewer |
| `reviewer` | 独立评审 | [08-reviewer.md](team/08-reviewer.md) | 0B-5；热修 G3、G4 评审 | G0B、G1 至 G4 门负责人 | orchestrator |
| `releaser` | 发布运维 | [09-releaser.md](team/09-releaser.md) | 6 验证上线、7 运行；热修 H1、H4-H5 | G5、G6 交付 | orchestrator、chronicler |
| `chronicler` | 复盘文档 | [10-chronicler.md](team/10-chronicler.md) | 8 复盘；迭代入口；热修 H5 补记录 | G7 交付 | orchestrator、analyst、releaser |
<!-- RENDER:AGENTS_TEAM:END -->

## 阶段与门

<!-- RENDER:AGENTS_STAGES:BEGIN -->
| 阶段 | 工作 | 交付负责人 | 门 | 门负责人 |
|---|---|---|---|---|
| 0B 现状基线 | 现有系统扫描 | architect | G0B | reviewer |
| 1 立项/变更立项 | 项目章程或变更说明、计划 | analyst | G0 | 人 + 总控 |
| 2 需求分析 | 需求规格、跟踪矩阵 | analyst | G1 | reviewer |
| 3 方案设计 | 架构、接口、体验、威胁模型 | architect、designer、security | G2 | reviewer |
| 4 编码开发 | 代码、单元测试 | frontend、backend | G3 | reviewer |
| 5 测试验证 | 功能、性能、安全测试 | functional-tester、performance-tester、security | G4 | reviewer |
| 6 验证上线 | 验收、链路验证、预发部署（不发布生产） | releaser | G5 | 人 |
| 7 运行维护 | 验证环境监控、故障、容量 | releaser | G6 | 总控 |
| 8 复盘迭代 | 验证上线复盘、改进项、归档 | chronicler | G7 | 人 + 总控 |
<!-- RENDER:AGENTS_STAGES:END -->

热修先完成 H0 定级，由总控按热修流程分派任务。G5 通过后核对 H5 补记。`DONE` 表示本模式流程完成。 [热修流程](protocol.md#热修流程)

## 协作规则

<!-- RENDER:RULES_SUMMARY:BEGIN -->
- 工件写入文件。交接消息填写任务信息、文件路径、状态和结论。
- 工件作者与门禁评审人必须分开。
- 总控负责模式判定、任务派发、门禁核对和状态记录。各专家负责交付本角色的工件。
- G5 由人批准。验证上线限于验证环境。
- G0 和 G7 的人工确认写入状态板。G5 的批准人、时间、范围和原文写入 docs/05-release.md。
<!-- RENDER:RULES_SUMMARY:END -->

每件工件采用独立评审。使用独立角色、会话或人员复核。总控按任务单给每个执行人分配互不重叠的写入范围，并指定合并点。材料不足时登记阻塞。 [交接消息](protocol.md#交接消息)

## 规模配置

先确定当前模式的必需工件，再按项目规模选择保留或合并的材料。

<!-- RENDER:AGENTS_PROFILES:BEGIN -->
| 配置 | 可兼任的工件职责 | 跳过工件 | 合并文档 | 替代章节 |
|---|---|---|---|---|
| 标准 | 无 | 无 | 无 | 无 |
| 小项目 | frontend 可负责 backend、designer 的工件；functional-tester 可负责 performance-tester 的工件 | docs/04-perf-report.md、docs/05-runbook.md、docs/manual/ | docs/02-ux-flow.md → docs/02-ux.md；docs/02-ui-spec.md → docs/02-ux.md | docs/04-perf-report.md → docs/04-test-report.md（性能结论）；docs/05-runbook.md → docs/05-release.md（运行手册）；docs/manual/ → docs/08-handover.md（使用说明） |
<!-- RENDER:AGENTS_PROFILES:END -->

## 任务路由

<!-- RENDER:AGENTS_ROUTES:BEGIN -->
| 任务 | Agent |
|---|---|
| 写项目章程、需求规格、验收标准 | analyst |
| 现状扫描、影响分析 | architect |
| 写架构设计、接口契约、技术选型 | architect |
| 任务流、五态设计、界面规范、文案 | designer |
| 实现前端界面和交互 | frontend |
| 实现服务、接口、数据 | backend |
| 设计用例、执行功能测试、提缺陷 | functional-tester |
| 写压测方案、执行性能测试 | performance-tester |
| 小项目性能证据交接、合并验证报告 | performance-tester 提交证据 → functional-tester 汇总 |
| 威胁建模、防御性代码审查、依赖与配置检查 | security |
| 独立评审、给门结论 | reviewer |
| 验证上线、回滚演练、验证环境监控和故障处理 | releaser |
| 热修定级 | orchestrator（functional-tester 复现） |
| 热修止损演练、记录人工处置结论 | releaser |
| 热修最小修复 | frontend 或 backend（按模块） |
| 热修回归 | functional-tester |
| 有安全影响的热修复核 | security 提交结论 → reviewer 核对 |
| 热修补记、汇总、结项核对 | chronicler 补记 → releaser 汇总 → orchestrator 核对 |
| 复盘、改进项、文档归档 | chronicler |
| 分派任务、检查门、升级 | orchestrator |
<!-- RENDER:AGENTS_ROUTES:END -->

## 工件目录

<!-- RENDER:AGENTS_ARTIFACTS:BEGIN -->
| 工件 | 负责人 | 类型 | 条件 |
|---|---|---|---|
| docs/00-brief.md | analyst | 门禁 | — |
| docs/00-context.md | architect | 门禁 | — |
| docs/01-requirements.md | analyst | 门禁 | — |
| docs/02-design.md | architect | 门禁 | — |
| docs/02-adr.md | architect | 按需 | — |
| docs/02-impact.md | architect | 条件门禁 | 二次开发 |
| docs/02-ux-flow.md | designer | 条件门禁 | 有界面 / 小项目可合并到 docs/02-ux.md |
| docs/02-ui-spec.md | designer | 条件门禁 | 有界面 / 小项目可合并到 docs/02-ux.md |
| docs/02-ux.md | designer | 条件门禁 | 小项目合并文档 |
| docs/02-threat-model.md | security | 门禁 | — |
| docs/03-build-notes-frontend.md | frontend | 条件门禁 | 有界面 / 热修候选 |
| docs/03-build-notes-backend.md | backend | 条件门禁 | 有后端 / 热修候选 |
| docs/04-test-report.md | functional-tester | 门禁 | 小项目替代章节（性能结论） |
| docs/04-perf-report.md | performance-tester | 门禁 | 小项目跳过 |
| docs/04-security-report.md | security | 门禁 | 有安全影响的热修 |
| docs/05-release.md | releaser | 门禁 | 小项目替代章节（运行手册） |
| docs/05-runbook.md | releaser | 门禁 | 小项目跳过 |
| docs/06-ops.md | releaser | 门禁 | — |
| docs/07-retro.md | chronicler | 门禁 | — |
| docs/backlog.md | chronicler | 门禁 | — |
| docs/manual/ | chronicler | 条件门禁 | 有界面 / 小项目跳过 |
| docs/08-handover.md | chronicler | 门禁 | 小项目替代章节（使用说明） |
| docs/08-hotfix.md | releaser | 条件门禁 | 热修 |
| docs/review-G0B.md | reviewer | 门禁 | — |
| docs/review-G1.md | reviewer | 门禁 | — |
| docs/review-G2.md | reviewer | 门禁 | — |
| docs/review-G3.md | reviewer | 门禁 | — |
| docs/review-G4.md | reviewer | 门禁 | — |
| docs/cr/NNN-*.md | 请求变更的 Agent | 按需 | — |
| docs/status.md | orchestrator | 状态源 | — |
<!-- RENDER:AGENTS_ARTIFACTS:END -->

[工件模板索引](templates/README.md) · [平台入口](PLATFORMS.md)
