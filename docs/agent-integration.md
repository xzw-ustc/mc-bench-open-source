# Agent 接入

Benchmark 通过 `EnvironmentAdapter` 和 `AgentAdapter` 接口运行，定义在 `src/mcbench/runner.py`。

| 接口 | 方法 |
| --- | --- |
| Environment | `reset(profile)`、`observe()`、`step(action)`、`close()` |
| Agent | `reset(compiled_chain)`、`act(snapshot, instruction, stage_context)` |

`EnvironmentStep` 返回 observation、done 和 info。Benchmark 的 verifier 负责阶段判定。

## Python policy

配置 `agent.kind: external`，用 `policy_entrypoint` 指定已安装 Python 包的工厂函数：

```json
{
  "kind": "external",
  "policy_entrypoint": "my_agent.policy:create_policy",
  "device": "cpu",
  "random_seed": 0,
  "policy_kwargs": {}
}
```

工厂返回具有 `act` 方法的对象。工厂支持的参数包括 `device`、`chain_context`、`agent_label`、`prompt_template` 和 `policy_kwargs` 中的字段，适配器按函数签名传参。

策略调用签名为 `act(observation, instruction, *, stage_context, snapshot)`，也支持两个位置参数或仅接收 instruction 的接口。返回值必须为动作 mapping。`action_adapter_entrypoint` 可指定动作转换函数。

每条链创建一次策略对象；对象提供无参数 `reset()` 时，在链开始时调用。`on_stage_end(instruction=..., status=..., steps=...)` 接收阶段反馈；`runtime_metadata()` 的返回值写入报告。策略的观测输入遵循 [观测协议](observation-tracks.md)。

## 配置

| 字段 | 单链 | Suite | 含义 |
| --- | --- | --- | --- |
| `catalog_dir` | 必填 | 必填 | Catalog 目录 |
| `profile_dir` | 可选 | 可选 | 默认使用 catalog 目录 |
| `chain_id` | 必填 | — | 官方能力链 ID |
| `environment_profile` | 必填 | — | 初始 profile |
| `environment` | 可选 | 可选 | `kind: scripted` 或 `kind: minerl` |
| `agent` | 必填 | 必填 | `kind: scripted` 或 `kind: external` |
| `output_path` | 必填 | — | 单链 JSON 报告 |
| `output_dir` | — | 必填 | 报告目录 |
| `chain_ids` / `split_ids` | — | 可选 | 二选一；均不设置时运行全部链 |
| `max_stage_steps` | 可选 | 可选 | 每个阶段的步数上限 |
| `per_stage_profiles` | 环境字段 | 可选 | 是否按任务切换 profile |

相对路径以运行命令的工作目录为基准。`environment.seed` 覆盖 profile seed；`agent.random_seed` 设置 Python 和已安装 NumPy/PyTorch 的随机数种子。

```bash
mcbench run-config run.json
mcbench run-suite-config suite.json
```

运行配置写入报告，服务凭据通过策略自己的环境变量读取。
