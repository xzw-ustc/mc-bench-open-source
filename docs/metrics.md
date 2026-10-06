# 指标

实现见 `src/mcbench/metrics.py`。

## 单链与 suite

| 字段 | 定义 |
| --- | --- |
| `task_success_rate` / `completion_rate` | 通过阶段数 / 计划阶段数；提前终止不会缩小分母 |
| `weighted_graph_progress`（WGP） | 已通过阶段对应的执行边权重 / 全链计划执行边权重 |
| `verified_milestone_progress`（VMP） | 在记录的观测中新增满足的物品/工具里程碑 / 可计分里程碑 |
| `total_steps` | 实际执行步数之和 |
| `efficiency.planned_step_budget` | 当前编译链的阶段预算之和 |
| `efficiency.budget_used_ratio` | 实际步数 / 预算 |
| `efficiency.steps_per_passed_stage` | 实际步数 / 通过阶段数；无通过阶段时为 null |
| `efficiency.deaths` | 由阶段诊断记录识别的死亡计数 |
| `efficiency.recovery_events` | 适配器明确记录的恢复事件数 |
| `efficiency.resource_waste_events` | 失败阶段中，消耗边所需资源减少的保守诊断计数 |

WGP 仅统计 `requires`、`produces`、`consumes` 对应的执行路径；不包含 `enables` 或 `abstracts_to`。suite 的 TSR、WGP、VMP 分别累加分子与分母后计算比例，不对单链比例做简单平均。

VMP 从**已报告阶段**构造里程碑集合，提前停止会改变分母，因此仅用于已到达链前缀的辅助诊断。它不是固定全链覆盖率，也不能单独作为学习增益证据。初始观测已满足的里程碑不计为新获得。

兼容字段 `evolution_score` 等于 TSR，不表示自进化得分。没有结构化恢复事件时 `recovery_events` 为 0，不能据此推出 agent 完全没有恢复行为。

`max_stage_steps` 会缩短编译阶段预算；这种结果属于预算受限运行，不能直接与默认预算的正式成绩合并。

## 通用成对指标函数

这些函数接收同一任务、环境和预算下的配对分数。

- `evolution_transfer_gain(B, R)`：绝对增益 `R-B`；归一化增益 `(R-B)/(1-B)`，无剩余空间时为 null。
- `graph_aligned_transfer_gain(B, R, U, S)`：相关经验相对匹配控制的差值 `R-(U+S)/2`。其中 B 为无先验、R 为相关、U 为无关、S 为打乱条件。该量消去了 B，不能独立证明提升。
- `self_evolution_gain_decomposition` 同时返回实际增益 `R-B`、控制差值和两者是否均为正。
- `transfer_measurement_regime` 标记四个分数是否受全零或全一限制。
- `retention_score(pre, post)`：BWT 为 `post-pre`；保留率为 `post/pre`，pre 为 0 时保留率为 null。

调用方负责固定任务、环境和预算，记录配对条件与 seed，并分析不确定性。上述函数本身不执行训练、记忆更新或统计显著性检验。
