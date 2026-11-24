# sdlc-agent-team 插件

版本: 1.0.0

12 角色软件交付团队。安装后输入 `/sdlc-agent-team:orchestrator`，启动总控技能。
调用单个角色时，输入 `@agent-sdlc-agent-team:<角色 ID>`。

本目录是生成物，不要手改。改 `team/` 或 `protocol.md` 后重跑：

```
python bin/install.py --build-plugin plugins/sdlc-agent-team
```

入口按需读取 `sdlc-agent-team/team/` 中的角色卡。流程协议在 `sdlc-agent-team/protocol.md`。
