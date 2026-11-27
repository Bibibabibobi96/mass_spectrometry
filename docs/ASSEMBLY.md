# 跨项目装配与物理工作流

本目录是跨项目装配的固定入口：器件与仪器项目拥有真实设计、组件、电极和端口，装配引用这些权威。
当前能力、证据与未完成验收只查[集成状态](INTEGRATION.md)；目标与职责见
[连接标准](COMPONENT_CONNECTION_ARCHITECTURE.md)、[迁移计划](ROADMAP.md#统一组装迁移计划)。

按任务进入：[装配与公共机制](INTEGRATION.md#装配与公共机制)、
[单反射整机](INTEGRATION.md#单反射整机)、[共同场／有限脉冲](INTEGRATION.md#共同场与有限脉冲)、
[门禁与剩余动作](INTEGRATION.md#依赖冻结与门禁)。组件自身资格继续归各项目PROJECT。

`verify_integration.ps1`默认执行完整Ruff与测试发现；Repository范围沿公共catalog分为四组，按实际需要完成一次preflight，
各组在独立GATE预算内执行明确模块并即时报告失败与耗时。分组PASS不单独代表完整集成门禁通过。

## Saved machine deployment

Configure one machine document once, then select a named engineering profile for each
study with `msplatform.execution.load_environment`. The loader reads explicit files;
it neither probes tools nor creates the study, ledger, aliases or policy files. Relative
references are anchored to the deployment file directory. A supplied mapping requires
absolute references. Python and PowerShell paths must name the intended installed tools.

For example, save `machine.json` beside `stages.json`:

```json
{
  "schema_version": 1,
  "role": "execution_environment",
  "tools": {"python": "C:/tools/msplatform/python.exe", "powershell": "C:/Program Files/PowerShell/7/pwsh.exe"},
  "policy": {"host_state_path": "C:/shared/msplatform/host-resources.sqlite3"},
  "profiles": {
    "standard": {"stage_policy_path": "stages.json"},
    "long_export": {"stage_policy_path": "stages.json", "overrides": {"export_cad": {"limits": {"wall_clock_seconds": 900}}}}
  }
}
```

The stage file uses the existing `execution_stage_policy` format shown in the
[standalone STEP tutorial](REPOSITORY_OPERATIONS.md#独立导出-step普通安装后的最短完整例子).
Optional machine policy fields are `policy_path` (host resource policy),
`execution_root` (shared short execution aliases), and `capacity_policy_path`
(the storage policy file, with the existing `artifact_capacity_policy` schema).
File-relative policy paths resolve beside the saved machine document. Omission
retains the installed storage policy unchanged: 700 GiB target and 295 GiB free
reserve. Select another explicit deployment file when configuring a different
machine; this does not change the artifact root, host ledger or protection leases.
A new managed owner captures that policy once, records the selected source
identity and freezes its snapshot in `inputs/capacity_policy.json`. Renewal and
readmission use this frozen policy, so changing the deployment file affects new
owners only. Existing run lifecycle budgets and historical records are not
rewritten. A legacy session can renew the same commitment and finalize using its
original evidence; increasing its commitment requires explicit current-phase
admission authority rather than inventing a historical policy. Storage policy
is machine configuration, not a per-study stage override. The existing repository
maintenance CLI retains its default policy; an explicit pressure-maintenance
callback receives the owner's captured policy in its capacity session.
Omission of the host policy and execution root retains the installed host policy
and the workspace's existing alias convention. The shared host ledger belongs
to the machine, never an individual study or profile.

```python
from pathlib import Path
from msplatform import execution

context = execution.load_environment(
    Path("deployment/machine.json").absolute(),
    workspace=Path("study").absolute(), profile="standard",
    overrides={"export_cad": {"limits": {"wall_clock_seconds": 900}}},
)
print(context.environment)  # independent profile, overrides and exact source record
```

Profile and per-call overrides merge existing engineering sections (`limits`,
`artifact_retention`, `runtime`); the original stage-policy owner validates the effective
action. Scientific dimensions, drives, sources, solver numerics and qualification criteria
stay in domain requests. Managed runs freeze the selected profile, overrides, effective
stage and exact deployment/stage authorities in their normal request and manifest chain.
Independent sources and offline analysis need no execution context. `ExecutionContext`
remains an explicit expert constructor for callers already holding resolved paths.

## 配方解析

作者显式引用冻结完整父配方；默认执行其全部实例，局部范围必须从该父装配声明派生。
参数职责与源／时钟语义见[统一装配标准](COMPONENT_CONNECTION_ARCHITECTURE.md#完整装配粒子源与局部求解范围)，
波形与同步职责见[驱动标准](COMPONENT_CONNECTION_ARCHITECTURE.md#电压波形器件驱动与同步)。

配方格式为[assembly_recipe.schema.json](../src/msplatform/contracts/schemas/assembly_recipe.schema.json)，
新科学组链的提供者接口为[component 3](../src/msplatform/contracts/schemas/component_geometry_interface_v3.schema.json)，
原[component 1](../src/msplatform/contracts/schemas/component_geometry_interface.schema.json)与
[component 2](../src/msplatform/contracts/schemas/component_geometry_interface_v2.schema.json)按明确版本读取。
实例直接声明局部到唯一装配frame的刚体位姿；连接只校验真实端面、法向与间隙，不沿连接反算位姿或补偿偏移。

从仓库根使用公共入口，先替换占位路径：

```powershell
.\.venv\Scripts\python.exe -m msplatform.workflows.connection_inputs --source-root . `
  --recipe "<recipe.json>" --components "<resolved-components.json>" `
  --plan-output "<run-inputs>/composition_plan.json"
.\.venv\Scripts\python.exe -m msplatform.workflows.connection_inputs --source-root . `
  --verify-plan "<run-inputs>/composition_plan.json"
```

component 3输入生成composition plan 5；显式旧component 1／2输入分别保留plan 3／4协议。
可选`--local-scope "<local-scope.json>"`显式派生范围。
`stage=layout_only`不代表任何求解器都能执行该装配；实际支持集、资格和拒绝边界见集成状态。

## 活动工作流

以下为公开入口。商业执行须有明确科学输入、授权及相称预算；准备成功不代表求场、Fly或物理验收。
跨项目新run归`instrument_assembly`，独立组件几何／场／CAD仍归其提供者项目。
统一 Recipe 由公共追踪入口解析；仍存的独立研究工作流以
`src/msplatform/workflows/config/assembly_registry.json` 的实际登记为准。入口和运行资源属于 `msplatform`。

公开原生追踪通过同一 Recipe/Study 选择真实场和显式原出生。历史 recorded-birth 请求版本12
仅可用 `results.historical_flight.decode_flight_request` 读取，不自动补造粒子种类或恢复旧执行入口。
当前 canonical recorded source 必须显式冻结物种、原母群与时钟；能力与 native 证据以
[追踪合同](TRACING.md)和[迁移记录](development/architecture-migration.md)为准。

### 模拟路径选择

声明的科学范围决定轨迹起点、场、时钟和母群；新整机追踪使用原出生连续传播，
组件边界观测不等于重新释放。局部研究须明确独立初态和边界。

### 分段接续模拟

历史跨组件状态重释放只按原版本读取，不作为新的整机执行入口。独立粒子批、事件、积分分区和
已支持的完整批次恢复仍按各自合同处理；它们不改变原出生或创建接续粒子。

### 联合连续模拟

当前公共入口是 `msplatform run` 和 `msplatform.workflows.tracing.run_recipe`。Study 明确完整组件、
连接、场、原出生、时钟和数值；一次连续追踪保留同一母群，中间观测不触发重新释放。
完整配方、部署文件和逐项能力状态见[追踪合同](TRACING.md)。历史 `FullJoint`、分段重释放和
旧单反射脚本不再作为新执行入口；历史资产按原版本读取。

```powershell
python -m msplatform validate <recipe.toml> --execution-environment <environment.json> --profile <profile> --workspace <workspace>
python -m msplatform run <recipe.toml> --execution-environment <environment.json> --profile <profile> --workspace <workspace> --artifact-root <store> --reserve-bytes <bytes>
python -m msplatform results inspect <run-id> --artifact-root <store>
```

OA + 单反射 TOF 支持显式原出生和选定场；RF → IP 支持原出生、显式 HS1 和空观察面，
其原始场 producer 可经严格身份与来源保护复用；商业 native 资格尚未验证。
IP → MR 及 RF → IP → MR 的公共路径要求实际匹配的
已发布采样场及显式 HS1 环境。单 MR 局部研究需要版本2 Study 的 `local_scope`、独立原出生和与模型
完全匹配的已发布 neutral sampled 场；当前尚无该组合的实际场与 native 资格证据。
自动发现脉冲的公共两阶段按原母群先进行 held-off 采样，再认证占据决策并进行 timed 追踪；
现有证据限惰性软件，尚未证明该组合的商业原生运行，不能将单次飞行或默认时间视为完成。

OA→MR 的现有独立研究入口仍为 [oa_mr.ps1](../src/msplatform/workflows/resources/oa_mr.ps1)，
其实际源、范围和场须按该次配置及证据核验；这不代表已完成公共链迁移。

共同静态场比较使用 [Store 公共 API](../src/msplatform/workflows/paired_accelerator_static_field/store_workflow.py)：
`run_paired_static_comparison(context, artifact_store=..., request_path=..., run_id=..., committed_new_bytes=...)`。
它支持新求解、受保护的已保存解原位采样、同边值问题同采样点的已完成样本复用，及有完整 writer/host
证据的 Store failed prepared 模型原位重开。`recover_paired_static_publication` 只恢复已有终态发布。
经验证的历史平面成功借用链同时保护消费者与原成功来源；缺 writer completion 的历史失败资产、
未认证借用链和中断状态不会自动获准。有限脉冲研究仍使用
[脉冲入口](../src/msplatform/workflows/resources/paired_accelerator_pulse.ps1)。这些能力的软件惰性测试
不代表商业原生求解、联合飞行或数值准确度已获资格。

## 当前文本绑定编译

唯一入口为`python -m tools.repository.refresh_repository_bindings [--check]`。
它刷新oaTOF required port的受管文本绑定，不改科学设计或历史证据；
运行依赖只由[runtime_dependencies.json](../src/msplatform/workflows/config/runtime_dependencies.json)声明，冻结机制见状态页。

## 历史追溯

[历史索引](history/integrations/README.md)维护冻结阶段证据及旧工作流入口；当前操作和能力继续由本页与集成状态维护。
