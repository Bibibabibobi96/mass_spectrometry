# 机器合同与设计请求

本目录保存跨项目的机器合同 Schema、语义校验器和可追溯规划工具。JSON Schema只判断字段、类型、
单位是否完整；Python语义层判断项目选择、能力成熟度、模式、指标、设计变量和约束是否成立。
二者不能互相取代。

`artifact_project.py`统一artifact项目根索引，`particle_state.py`统一SIMION/COMSOL适配后的粒子事件字段、
身份、三维位置/速度、全局时间和RF相位校验；`run_artifact_support.ps1`统一PowerShell运行器创建目录、
冻结输入、失败收尾和三件套manifest。它们不得内置器件参数，项目包装器只允许保留兼容入口。
`file_identity.py`是manifest、正式资产和机器合同文件SHA-256身份的唯一流式实现，固定返回大写十六进制；
调用者只负责路径范围、字节数和证据资格等各自合同。

`particle_count_policy.json`是根README“通用验证口径”对应的机器合同。入口使用
`python -m common.contracts.particle_count_policy --count <N>`在求解前失败关闭；本目录不重复定义档位，
项目也不得复制后修改该规范。

## 项目发现

项目身份和能力的权威源是各项目`config/project.json`。根`config/project_registry.json`是生成索引，
禁止手改：

```powershell
.\.venv\Scripts\python.exe common\contracts\build_project_registry.py
.\.venv\Scripts\python.exe common\contracts\build_project_registry.py --check
```

## 从自然语言到计划

当前边界是“Agent理解自然语言，确定性工具验证合同”：Agent先把需求翻译成`design_request` JSON，
保留为`proposed`，由使用者批准后才能请求formal证据。校验结果固定为`READY`、
`NEEDS_CLARIFICATION`、`NEEDS_PROJECT_COMPLETION`、`NEEDS_NEW_PROJECT`或`UNSUPPORTED`，不会因为
项目目录存在就假定能力已经完成。

```powershell
.\.venv\Scripts\python.exe -m common.contracts.validate_design_request <request.json>
.\.venv\Scripts\python.exe -m common.contracts.plan_design_request <request.json> `
  --run-id 20260720_120000__analysis__repo__design-request `
  --output-dir <new-run-directory>
```

规划器只写`design_plan.json`和`run_config.json`，不启动商业求解器、不宣称满足指标，也不把
`formal_gate_passed`设为真。后续执行器必须继续使用项目门禁、summary和manifest闭合实际证据。

## 执行dry-run

各项目在`config/execution_profiles.json`中声明现有入口实际支持的工况、目标指标、变量、约束、产物和命令链。
执行编译器只生成命令预览，没有执行开关：

```powershell
.\.venv\Scripts\python.exe -m common.contracts.compile_execution_plan <design_plan.json>
```

结果为`EXECUTION_READY`、`AWAITING_APPROVAL`、`NEEDS_RUNTIME_INPUTS`或`NEEDS_IMPLEMENTATION`。
`EXECUTION_READY`只表示需求已批准且现有入口能够消费声明字段并评价所请求的目标指标；它不表示
求解已经运行或指标已经满足。只完成结构构建的runner不得把分辨率等未评价目标列为支持。
需要显式粒子表、RF幅值等运行绑定的profile使用`--bind key=value`提供预览值。编译器会验证入口文件、
生成受命名合同约束的子run ID，并保留项目profile的限制说明，但不会创建artifact运行目录。

## 正式结果与来源运行

每次运行的`run_config.json`、`summary.json`和`run_manifest.json`只描述来源run；通过正式门禁后，选出的
模型、CAD和结果进入稳定`formal/`，但不改变来源三件套。`formal/asset_manifest.json`是当前正式发布
的唯一资产清单，记录来源run三件套、Git内正式验证合同及各正式资产的相对路径、字节数和SHA-256：

```powershell
python common/contracts/write_formal_asset_manifest.py `
  --project-root <artifacts-project-root> --repository-root <repository-root> `
  --project <project_id> --source-run-id <run_id> `
  --validation-contract <formal-validation-json> `
  --asset formal_results_manifest=results/SHA256SUMS.csv
```

结构门禁默认不读取大二进制；正式发布或资产变更后再运行
`verify_artifact_layout.py <artifacts-projects-root> --verify-hashes`做完整哈希复核。正式结果本体不复制回
来源run；为便于独立交付，可在结果包保留三份小型来源JSON快照，但它们不能替代原始run或正式清单。
只复核当前正式发布而不审计旧run命名时使用`--formal-only --repository-root <repository-root>`。

优化变量的“项目能力声明”和“现有执行入口可消费”是两层事实。一个变量可以属于未来设计空间，但在
候选参数编译器尚未把它单向派生到baseline/resolved和全部求解器/CAD前，dry-run必须报告
`NEEDS_IMPLEMENTATION`，不得调用固定模型冒充优化。

## 候选参数编译

项目可以用`config/design_variables.json`声明变量类型、静态安全范围、JSON指针和重建影响，并用独立
`config/optimization_envelope.json`限制一轮优化的总体包络。正式baseline是当前验收设计，不是永远
不可扩大的宇宙上限；envelope可经明确审查扩大，扩大本身也不会自动改写或转正baseline。

项目候选编译器必须把获批提案写入隔离run，验证请求/提案身份、单位、变量范围、项目硬约束和当前
envelope，并输出可审阅的候选合同与差异。它不得修改正式baseline、运行求解器或创建正式资产。
具体包络策略、候选文件名和编译入口属于消费项目，不在公共合同README维护第二份说明。
