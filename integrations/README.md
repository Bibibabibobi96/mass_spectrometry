# 跨项目装配与物理工作流

本目录是跨项目装配的固定入口：器件与仪器项目拥有真实设计、组件、电极和端口，装配引用这些权威。
当前能力、证据与未完成验收只查[集成状态](docs/INTEGRATION.md)；目标与职责见
[连接标准](../docs/COMPONENT_CONNECTION_ARCHITECTURE.md)、[迁移计划](../docs/ROADMAP.md#统一组装迁移计划)。

按任务进入：[装配与公共机制](docs/INTEGRATION.md#装配与公共机制)、
[单反射整机](docs/INTEGRATION.md#单反射整机)、[共同场／有限脉冲](docs/INTEGRATION.md#共同场与有限脉冲)、
[门禁与剩余动作](docs/INTEGRATION.md#依赖冻结与门禁)。组件自身资格继续归各项目PROJECT。

`verify_integration.ps1`默认执行完整Ruff与测试发现；L2沿公共catalog分为四组，先完成一次preflight，
各组在独立GATE预算内执行明确模块并即时报告失败与耗时。分组PASS不单独代表完整集成门禁通过。

## 配方解析

作者显式引用冻结完整父配方；默认执行其全部实例，局部范围必须从该父装配声明派生。
参数职责与源／时钟语义见[统一装配标准](../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#完整装配粒子源与局部求解范围)，
波形与同步职责见[驱动标准](../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#电压波形器件驱动与同步)。

配方格式为[assembly_recipe.schema.json](../common/contracts/schemas/assembly_recipe.schema.json)，
提供者接口为[component_geometry_interface.schema.json](../common/contracts/schemas/component_geometry_interface.schema.json)。
实例直接声明局部到唯一装配frame的刚体位姿；连接只校验真实端面、法向与间隙，不沿连接反算位姿或补偿偏移。

从仓库根使用公共入口，先替换占位路径：

```powershell
.\.venv\Scripts\python.exe -m common.integration.resolve_connection `
  --recipe "<recipe.json>" --components "<resolved-components.json>" `
  --plan-output "<run-inputs>/composition_plan.json"
.\.venv\Scripts\python.exe -m common.integration.resolve_connection `
  --verify-plan "<run-inputs>/composition_plan.json"
```

输出composition plan v3；可选`--local-scope "<local-scope.json>"`显式派生范围。
`stage=layout_only`不代表任何求解器都能执行该装配；实际支持集、资格和拒绝边界见集成状态。

## 活动工作流

以下为公开入口。商业执行须有明确科学输入、授权及相称预算；准备成功不代表求场、Fly或物理验收。
跨项目新run归`instrument_assembly`，独立组件几何／场／CAD仍归其提供者项目。

| 科学工作流 | 公开入口与显式输入 | 状态及操作边界 |
|---|---|---|
| 裸导引→二区／三区OA | [local_frontend/execute.ps1](workflows/local_frontend/execute.ps1)，`-Request` | [准备与复核](docs/INTEGRATION.md#局部前端执行与复核) |
| 冷却前端→OA | [cooled_frontend/execute.ps1](workflows/cooled_frontend/execute.ps1)，`-Request` | [局部证据](docs/INTEGRATION.md#局部前端执行与复核) |
| 多极杆→OA→单反射TOF | [single_reflection_flight/run.ps1](workflows/single_reflection_flight/run.ps1)，`-Request -ExecutionBudgetPath` | [schema 9及默认完整Fly](docs/INTEGRATION.md#单反射整机)；内部execute由owner调用 |
| OA／IP→MR接口准备与IP完整链 | [accelerator_interface/execute.ps1](workflows/accelerator_interface/execute.ps1)，明确提供者与参考run；IP设计另给`-MatchingRequestPath`，完整链显式选`-FullJoint` | [输入及设计／Finalize边界](docs/INTEGRATION.md#oaip接口准备与绑定) |
| 已准备IP→MR飞行／分析 | [prepared_joint/execute.ps1](workflows/prepared_joint/execute.ps1)，准备run与观测合同 | [联合执行及Analysis](docs/INTEGRATION.md#已准备ipmr联合飞行) |
| OA→MR | [oa_mr/execute.ps1](workflows/oa_mr/execute.ps1)，`-CompositionPlanPath`及可选`-LocalScopePath` | [支持范围与证据](docs/INTEGRATION.md#已准备ipmr联合飞行) |
| 真实多极杆→IP状态准备 | [multipole_ip/execute.ps1](workflows/multipole_ip/execute.ps1)，`-Request` | [真实源／母群与负结果](docs/INTEGRATION.md#真实多极杆ip状态交接) |
| OA共同静态场 | [paired_accelerator_static_field/execute.ps1](workflows/paired_accelerator_static_field/execute.ps1)，`-Request` | [prepared／solved恢复及资格](docs/INTEGRATION.md#共同场与有限脉冲) |
| OA共同场有限脉冲 | [paired_accelerator_pulse/execute.ps1](workflows/paired_accelerator_pulse/execute.ps1)，`-Request`及显式来源 | [阶段／整批恢复与诊断](docs/INTEGRATION.md#共同场与有限脉冲) |

直属静态入口为[verify_integration.ps1](verify_integration.ps1)，不启动商业求解器。
入口递归枚举`integrations/tests`中的测试模块；L1按统一目录传入`ChangedTestModules`时合并去重，
保持该入口的Ruff检查。测试使用公共计时runner，即时报出失败详情并逐测试计时；明确的纯测试模块变更
可由L1精确运行，fixture、删除或未知目录变化扩大到owner。
L1／L2、冻结依赖与最终验收见[状态页](docs/INTEGRATION.md#依赖冻结与门禁)及[操作指南](../docs/OPERATIONS.md#分层门禁)。
不使用已退役的旧family或arm CLI执行新实验；历史运行保持原身份。

## 当前文本绑定编译

唯一入口为`python -m integrations.runtime.refresh_repository_bindings [--check]`。
它刷新oaTOF required port的受管文本绑定，不改科学设计或历史证据；
运行依赖只由[runtime_dependencies.json](config/runtime_dependencies.json)声明，冻结机制见状态页。

## 历史追溯

[历史索引](docs/history/README.md)维护冻结阶段证据及旧工作流入口；当前操作和能力继续由本页与集成状态维护。
