# 软件交付协议

<!-- RENDER:VERSION:BEGIN -->
当前版本 `1.0.0`
<!-- RENDER:VERSION:END -->

## 状态板与工件

总控在目标项目的 `docs/status.md` 登记本次模式、规模、范围和当前阶段。每个门和每件工件各登记一行。门状态使用 `pending`、`pass`、`fail` 或 `n/a`。当前流程包含 G6，且本次既无需部署也无需修改数据时，才可将该门写为 `n/a`。在缺项列写理由。

工件负责人以 `DRAFT` 开始编写，完成后提交为 `IN-REVIEW`。评审通过时记录 `APPROVED`，需要返工时记录 `CHANGES`。缺少输入或证据时记录 `BLOCKED`。

轻量变更和热修使用唯一变更编号。适用工件的版本栏、状态板中的工件版本以及热修批准编号均使用本次编号。

```text
> 工件: <名称>
> 版本: <本次变更编号>
> 状态: IN-REVIEW
> 负责人: <角色 ID>
> 门: <门 ID>
> 输入: <相关工件路径>
> 更新: YYYY-MM-DD
```

总控确认验证环境的 `数据库` 状态。值为 `无` 时，G6 核对监控、容量和告警。其他情况还需核对核心表备份与恢复的证据。

## 交接消息

每条消息描述一项任务。角色使用注册的 ID。输入和输出填写工件路径。总控写清完成条件和获准写入的文件。轻量变更和热修另填 `CHANGE`。

```text
FROM: orchestrator
TO: designer
TASK: 编写报表筛选任务流
MODE: 二次开发
GATE: G2
INPUT: docs/01-requirements.md
OUTPUT: docs/02-ux-flow.md
WRITE SCOPE: docs/02-ux-flow.md
DONE WHEN: 主要任务、筛选动作和五种状态均已说明
STATUS: READY
NOTES: 复用现有界面组件
```

状态填 `READY` 或 `BLOCKED`。需要解除阻塞时，记录缺项、可提供材料的人和已尝试的办法。

## 门禁办理

1. 工件负责人提交适用工件和证据。
2. 门负责人逐项核对完成条件。每个独立评审门由一个评审实例给出结论。
3. 总控执行当前门的就绪检查。评审和所需的人工作出决定后，登记通过状态，并用 `--require-pass` 复核。复核失败时恢复原状态并记录缺项。
4. 交付前执行 `--gate all`。处理未关闭的阻塞。

带 `[自动]` 的条目由门禁工具检查。其余结论由门负责人根据证据作出。

### 人工确认

G0 和 G7 在状态板的“人工确认”表记录确认人、时间和明确同意的结论。

G5 的批准记录位于 `docs/05-release.md`。填写批准人、批准时间、批准范围和原文。范围写“非生产”或“不涉及生产”。热修记录获批的本次变更编号。批准原文须明确同意验证发布或热修。

<!-- RENDER:PROTOCOL_GATES:BEGIN -->
### G0B 现状基线

- 技术栈和版本已记录。
- 已记录构建、启动和测试的命令及实际结果。步骤受阻时已写明原因。
- 关键模块和数据流已列出。
- 部署方式和环境已记录。
- 依赖风险与许可证已列出。
- 隐式契约已识别。
- 技术债热区已列出。
- 现有测试基线记录实际结果。对拟修复的既有失败，独立评审核对复现证据和影响范围后，可将其纳入基线。
- 现有文档已映射到团队工件。
- 不可动清单已列出。
- [自动] 现状基线含现有测试基线与不可动清单。

必需工件: docs/00-context.md、docs/review-G0B.md。

### G0 立项/变更立项

- 目标、范围、干系人已确认。
- 成功指标可判定。
- 计划与预算已确认。
- 人已确认立项或变更。
- [自动] 项目章程含目标、范围、成功指标与主要风险。

必需工件: docs/00-brief.md。

### G1 需求

- 每条需求有唯一 ID。
- 每条需求有可执行验收标准。
- 优先级有依据。
- 非功能需求有数值指标。
- 有不做清单。
- [自动] 没有 TBD。
- [自动] 需求文档含验收标准。
- [自动] 评审报告结论为通过。

必需工件: docs/01-requirements.md、docs/review-G1.md。

### G2 设计

- 每条需求映射到模块。
- 接口有输入、输出、错误码。
- 数据模型有主键、索引、迁移与回滚方案。
- 非功能指标可测量。
- 有威胁模型。
- 二次开发有影响分析。
- 有降级和回滚方案。
- 体验设计覆盖五种状态。
- [自动] 设计文档含接口契约与降级回滚。
- [自动] 设计用映射行覆盖全部 REQ 与 NFR，且不含未登记 ID。
- [自动] 威胁模型存在。
- [自动] 评审报告结论为通过。

必需工件: docs/02-design.md、docs/02-threat-model.md、docs/review-G2.md。
二次开发另需: docs/02-impact.md。
有界面时另需: docs/02-ux-flow.md、docs/02-ui-spec.md。
小项目合并: docs/02-ux-flow.md 可合并为 docs/02-ux.md；docs/02-ui-spec.md 可合并为 docs/02-ux.md。

### G3 代码

- 构建通过。
- 单元测试通过。
- 关键路径有测试。
- 静态检查无高危。
- 依赖扫描无高危漏洞。
- 二次开发有特征测试。
- 修改范围与影响分析一致。
- 评审意见已关闭。
- [自动] 构建说明含修改文件与构建。
- [自动] 评审报告结论为通过。

轻量变更使用以下检查项。

- 本次改动的文件、目标行为和验收条件已记录。
- 涉及的前端或后端有构建说明与实际验证结果。
- 独立评审已关闭阻断问题。
- [自动] 构建说明和通过的评审结论属于本次变更。

必需工件: docs/review-G3.md。
有界面时另需: docs/03-build-notes-frontend.md。
有后端时另需: docs/03-build-notes-backend.md。
热修改为: docs/review-G3.md。
热修按界面和后端的改动范围提交构建说明。未确定必需说明时，从适用候选中提交至少一份。候选工件为 docs/03-build-notes-frontend.md、docs/03-build-notes-backend.md。

### G4 测试

- 用例覆盖全部验收标准。
- 回归基线通过。
- 阻断缺陷为 0。
- 性能有结论（小项目写入测试报告）。
- 安全无未处置高危。
- 遗留缺陷有结论。
- [自动] 测试报告含用例与准出建议。
- [自动] 测试报告用映射行覆盖全部 REQ，且不含未登记 ID。
- [自动] 性能报告含用例、性能与准出建议。
- [自动] 安全报告含用例、安全与准出建议。
- [自动] 评审报告结论为通过。

轻量变更使用以下检查项。

- 本次验收条件已验证。
- 受影响的旧功能回归通过。
- 独立评审已确认验证范围与证据。
- [自动] 本次变更的回归结果、准出结论和评审结论均通过。

热修使用以下检查项。

- 修复后的故障场景验证通过。
- 受影响模块的回归通过。报告记录范围、用例和实际结果。
- 阻断缺陷为 0。
- 有安全影响时，独立评审已核对本次热修的安全复核范围、证据和结论。
- [自动] 热修安全影响已明确为有或无。
- [自动] 有安全影响时，安全报告属于本次变更且准出结论为通过。
- [自动] 测试报告含用例与准出建议。
- [自动] 本次回归结果与准出结论均通过。
- [自动] 评审报告结论为通过。

必需工件: docs/04-test-report.md、docs/04-perf-report.md、docs/04-security-report.md、docs/review-G4.md。
热修改为: docs/04-test-report.md、docs/review-G4.md。
热修安全影响为有时，另需 docs/04-security-report.md。
轻量变更只需 docs/04-test-report.md、docs/review-G4.md。
小项目跳过: docs/04-perf-report.md。
小项目替代章节: docs/04-test-report.md（性能结论）替代 docs/04-perf-report.md。

### G5 验证上线

- 有人批准验证上线（不涉及生产）。
- 验证链路已跑通，无报错、无阻塞。
- 回滚方案已验证。
- 有运行手册（小项目写入发布计划）。
- 监控与告警已验证。
- 数据迁移在预发可回退。
- 值班与公告已确认（验证环境）。
- 未执行任何生产发布操作。
- [自动] 发布计划含回滚、批准、迁移、告警与公告。
- [自动] 人工批准记录完整。

必需工件: docs/05-release.md、docs/05-runbook.md。
热修改为: docs/05-release.md、docs/05-runbook.md、docs/08-hotfix.md。
小项目跳过: docs/05-runbook.md。
小项目替代章节: docs/05-release.md（运行手册）替代 docs/05-runbook.md。

### G6 运行

- 验证环境监控正常。
- 验证环境告警有处理记录。
- 验证环境容量有余量。
- 数据库未明确为无时，验证至少一个核心表可恢复。核心表见设计文档。
- [自动] 运维记录含监控、容量和告警。
- [自动] 数据库未明确为无时，校验备份、恢复证据、行数和校验和。

必需工件: docs/06-ops.md。

### G7 复盘

- 验证上线结论有数据支撑。
- 每个问题有根因。
- 改进项有负责人和期限。
- 需求池已更新。
- 交接文档已生成；有界面时用户手册已生成（小项目写入交接文档使用说明）。
- [自动] 复盘含问题与根因、改进项。
- [自动] 交接文档存在。

必需工件: docs/07-retro.md、docs/08-handover.md、docs/backlog.md。
有界面时另需: docs/manual/。
小项目跳过: docs/manual/。
小项目替代章节: docs/08-handover.md（使用说明）替代 docs/manual/。
<!-- RENDER:PROTOCOL_GATES:END -->

### 验证环境发布

G4 通过且当前模式包含 G5 时，总控安排发布。发布运维按照人的批准范围操作授权的验证环境。迁移、验证和回滚演练均使用该环境。需要生产处置时交给获授权的值班人员。

热修在 G5 通过后办理 H5。其余模式按状态机推进验证环境运行和复盘。

## 热修流程

<!-- RENDER:PROTOCOL_HOTFIX:BEGIN -->
| 阶段 | 工作 | 负责人 |
|---|---|---|
| H0 定级 | 复现、定级、评估影响并登记热修安全影响 | functional-tester、orchestrator |
| H1 止损 | 在授权的验证环境演练回滚或降级，记录适用的人工处置结论 | releaser |
| H2 最小修复 | 最小改动、补测试 | frontend、backend |
| H3 回归 | 功能回归。有安全影响时由 security 复核 | functional-tester、security |
| H4 验证发布 | 验证环境发布、观察 | releaser |
| H5 补记录 | 补 CR、测试用例和复盘记录，汇总热修记录并核对结项 | chronicler、releaser、orchestrator |
<!-- RENDER:PROTOCOL_HOTFIX:END -->

H0 由总控判断安全影响。涉及身份认证、访问权限、租户隔离或敏感数据处理时，将状态板的 `热修安全影响` 写为 `有`。确认各项均无影响时填 `无`。范围变化时重新判定。

H1 由 `releaser` 在授权验证环境演练止损措施。需要生产止损时，获授权的值班人员决定并执行。发布运维将人的处置结论写入 `docs/08-hotfix.md`，总控跟进缺失的结论。

有安全影响的热修在 H3 由 `security` 复核。安全报告使用本次变更编号，记录证据和准出结论。`reviewer` 在 G4 核对该报告。G4 通过后进入 H4，按 G5 的人工批准执行验证发布。

H5 由 `releaser` 将发布记录和时间线交给 `chronicler`。复盘文档角色提交变更请求、验证证据和复盘补记。发布运维汇总热修记录。总控核对后登记 `DONE`。

<!-- RENDER:PROTOCOL_HOTFIX_CHECKS:BEGIN -->
- 故障级别已判定（P0-P3）。
- H0 已判定热修安全影响。有安全影响时 G4 已核对安全复核结论。
- 只改导致故障的最小范围。
- G3、G4、G5 已按本次变更编号复核通过。
- H1 已记录回滚路径和止损结论。
- H4 前用户已明确同意验证发布。
- H5 已补齐 CR、测试用例和复盘记录。总控已核对热修记录。
<!-- RENDER:PROTOCOL_HOTFIX_CHECKS:END -->

## 返工与升级

在门禁记录中登记问题、责任人和返工次数。G0B 退回基线，G1 退回需求，G2 退回设计。达到 `rules.rework_limit` 且问题仍未解决时，总控提交选项及影响，请人裁决。

高风险上线、P0 或 P1 热修及任务目标改变时，由总控主动报告。涉及结论冲突时，先核对证据，仍无法解决则升级。状态板上的阻塞完成处理后写 `CLOSED` 或“已关闭”。

## 变更请求

范围、接口契约、数据或依赖改变时，由请求者填写 `docs/cr/NNN-*.md`。总控登记批准、拒绝或延期及理由。批准后更新受影响的工件，重新办理对应的门。

## 并行工作

总控先确认输入和文件归属。接口契约确认后可以并行实现前端和后端。验证环境互相独立时，可以并行开展功能与性能验证。

需要合并性能结论时，`performance-tester` 向 `functional-tester` 提交证据和结论。功能验证报告由 `functional-tester` 统一写入。

## 命令行操作

在目标项目根目录运行。按当前阶段替换示例中的门 ID。

```sh
python sdlc-agent-team/tools/gates.py --gate G2
python sdlc-agent-team/tools/gates.py --gate G2 --require-pass
python sdlc-agent-team/tools/gates.py --gate all
python sdlc-agent-team/tools/gates.py --sync-artifacts --dry-run
python sdlc-agent-team/tools/dashboard.py --project .
python sdlc-agent-team/tools/flow.py --project . show
```

执行 `--sync-artifacts` 可把已发现的工件登记到状态板。门负责人仍须填写各自的结论。

使用以下命令记录活动。看板读取状态板和活动文件。

```sh
python sdlc-agent-team/tools/flow.py --project . start --agent analyst --stage G1 --task "整理需求"
python sdlc-agent-team/tools/flow.py --project . handoff --from analyst --to reviewer --artifact docs/01-requirements.md
python sdlc-agent-team/tools/flow.py --project . done --agent reviewer --artifact docs/01-requirements.md
python sdlc-agent-team/tools/flow.py --project . block --agent backend --reason "等待契约确认"
```

`monitoring.flow_state` 的默认值为 `docs/flow.json`。`monitoring.refresh_seconds` 控制看板刷新。 [模板索引](templates/README.md)
