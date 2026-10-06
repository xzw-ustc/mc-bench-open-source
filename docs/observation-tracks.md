# 观测与判定边界

Catalog 中每条 `observation_sources` 都声明 `track` 和 `agent_access`，校验器检查这两个字段。

- `native_perception` / `agent_visible`：原生观测，如背包、装备、基本生存状态；真实环境也提供 POV 图像。
- `structured_state` / `evaluator_only`：用于判定和诊断的派生 flag、counter、mission event、时间/光照、ray/grid 与已知方块位置等。

每个具体字段以 catalog 中的声明为准，逐任务来源见 [verifier-observation-sources.md](verifier-observation-sources.md)。使用 evaluator-only 信息作为策略输入时，应明确报告为 Structured-State Track，不能混入 Native Perception Track。

## 接入接口

`runner.AgentAdapter` 可接收完整 `ObservationSnapshot` 和编译阶段；`ExternalPolicyAgentAdapter` 会将 `raw_observation` 以及可选的 `snapshot`、`stage_context` 传给 policy。因此，接口**没有自动隔离或过滤特权字段**，它是受信任的集成接口，不是策略沙箱。

进行 Native Perception Track 评测时，调用方的 wrapper 必须明确筛选允许输入，禁止向模型提示、记忆或策略输入传递 verifier predicates、图边、环境隐藏坐标或 evaluator-only 字段。structured ray/grid 不能因为位于 raw observation 中就自动视为原生输入。

阶段结束的通用回调仅转发 instruction、status 和 steps；报告中的诊断证据供 evaluator 审查。新增 runtime 或 wrapper 时，应检查实际传入模型的内容，并记录使用的观测 track。
