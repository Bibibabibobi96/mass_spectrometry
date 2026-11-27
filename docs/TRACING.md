# 公共粒子 tracing

新公开链数值积分非相对论 Lorentz 方程，支持明确真空中静态均匀 E+B 和具名轴对齐平面。
四份作者配置在[参考配方](../recipes/reference/uniform_e.toml)及其同目录；参考单元不是完整仪器。
当前参考作者配方采用 schema3，显式 `species` 注册表分别声明 `species_id`、`species_kind`、
质量和带符号电荷态；初态以 species_id 引用，解析后物理值必须与注册表一致。
电子必须明确声明 `electron`、电荷态 −1，并使用版本化电子质量；负离子明确为 `ion`，不由电荷推断种类。
参考示例的正离子、负离子和电子验证限于非相对论真空均匀场，不代表电子碰撞或原生求解器资格。
参考 tracer 的时变场、碰撞、自洽、非参考几何由能力预检拒绝。选择 max_step 时须避免一步多次穿面；切触未保证检测。

## 安装与运行

从仓库根目录在独立临时目录构建普通 wheel 和 sdist，使用 `pyproject.toml` 中固定的
setuptools 与 wheel 版本，不需要 `build` frontend。`git archive HEAD` 只使用当前已提交快照；
未提交的修改不会进入发行，需先提交或另行明确准备要构建的源码。下面的 `$taskBuild` 是新建目录，
构建产物位于其中的 `dist`，不会覆盖已有交付文件：

```powershell
$taskBuild = Join-Path $env:TEMP ("msplatform-build-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $taskBuild | Out-Null
New-Item -ItemType Directory -Path (Join-Path $taskBuild "source"), (Join-Path $taskBuild "dist") | Out-Null
git archive --format=tar -o (Join-Path $taskBuild "source.tar") HEAD
if ($LASTEXITCODE -ne 0) { throw "source archive failed" }
tar -xf (Join-Path $taskBuild "source.tar") -C (Join-Path $taskBuild "source")
if ($LASTEXITCODE -ne 0) { throw "source extraction failed" }
py -3.11 -m venv (Join-Path $taskBuild "builder")
if ($LASTEXITCODE -ne 0) { throw "builder environment creation failed" }
$builderPython = Join-Path $taskBuild "builder\Scripts\python.exe"
& $builderPython -m pip install "setuptools==65.5.0" "wheel==0.38.4"
if ($LASTEXITCODE -ne 0) { throw "build tool installation failed" }
Push-Location (Join-Path $taskBuild "source")
try {
    & $builderPython -c 'from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])' (Join-Path $taskBuild "dist")
    if ($LASTEXITCODE -ne 0) { throw "wheel build failed" }
    & $builderPython -c 'from setuptools.build_meta import build_sdist; import sys; build_sdist(sys.argv[1])' (Join-Path $taskBuild "dist")
    if ($LASTEXITCODE -ne 0) { throw "sdist build failed" }
} finally { Pop-Location }
Get-ChildItem (Join-Path $taskBuild "dist")
```

wheel 和 sdist 分别在独立 Python 进程构建，避免构建 backend 状态影响输出位置。
构建工具版本须与当前 `pyproject.toml` 的 `[build-system].requires` 一致。使用者需要同一发行的
`requirements-lock.txt` 和 wheel；下面从仓库根目录创建独立运行环境（替换目标路径）：

```powershell
py -3.11 -m venv C:\msplatform-env
C:\msplatform-env\Scripts\python.exe -m pip install -r requirements-lock.txt
C:\msplatform-env\Scripts\python.exe -m pip install (Join-Path $taskBuild "dist\mass_spectrometry_analysis-0.4.0-py3-none-any.whl")
```

将唯一作者 TOML 复制到研究目录，切到源码树外后运行（替换部署路径）：

```powershell
C:\msplatform-env\Scripts\msplatform.exe --help
C:\msplatform-env\Scripts\msplatform.exe validate .\uniform_e.toml
C:\msplatform-env\Scripts\msplatform.exe run .\uniform_e.toml --artifact-root C:\msplatform-data\study
C:\msplatform-env\Scripts\msplatform.exe results inspect <run_id> --artifact-root C:\msplatform-data\study
```

`python -m msplatform` 使用相同入口。Python API 为 `msplatform.recipes.load_recipe`、
`msplatform.tracing.trace_particles`、`msplatform.workflows.tracing.run_recipe/inspect_results`。
直接 tracer 消费已解析的 SI 科学数据；作者输入与身份由 load_recipe/validate_recipe 检查。
`load_recipe(path)` 单次读取外部 TOML，返回对象的 `source_bytes` 保留该次不可变字节快照；
run 使用同一快照解析、归档 `author.toml` 并计算 provenance 的 `author_sha256`。
外部文件随后改变只影响下一次运行；来源字节哈希与排除 label 的科学缓存身份分别记录。
可用 `--source-revision <完整SHA>` 显式记录构建来源；未提供时标记来源 SHA 不可用，
不从研究目录猜测源码来源。该记录不决定物理缓存命中。

## 原生配方与当前验证边界

同一 `validate`/`run` 和 `run_recipe` 接受schema2原生配方，作者输入仍只读取一次。
安装包 `msplatform.examples` 中的 `oa_split_tof_native_small_v1.toml`、
`rf_split_oatof_native_small_v1.toml` 与 `oa_split_tof_comsol_small_v1.toml` 给出明确Study引用；
复制时保留对应JSON，不能只复制TOML。独立OA和下游TOF连续追踪，原birth与pulse/epoch保留。

`oa_split_tof_mass_scan_small_v1.toml` 给出同质量+1/+2、N=3/2的非空物种集合。
第一物种保留单物种例的全部原始请求，第二物种使用独立ID4/5和每粒子0.5权重；
样本数与丰度分开。以相同 `run` 命令执行，无需手动拼接批次；真实小N结果与复用资格仍查迁移记录。

原生运行必须同时提供 `--execution-environment <部署JSON> --profile <工程profile> --workspace <原生owner工作区>`，
另指定与原生 `workspace/artifacts` 分离的 `--artifact-root` 和正整数 `--reserve-bytes`。
部署使用既有ExecutionContext/阶段策略/共享host调度；科学值来自唯一冻结Study。
`validate` 返回 resolved与capabilities：implemented只说明编译路径，host_available只说明工具可用，
native_verified=false不代表原生求解已验证。实际逐组合证据查[迁移记录](development/architecture-migration.md)。
当前 SIMION 和 COMSOL 原生追踪预检拒绝 electron；正、负 ion 的真空预检并不赋予碰撞模型或仪器性能资格。

软件路径包括SIMION→SIMION、COMSOL→COMSOL，以及显式COMSOL OFF/ON资产采样到SIMION。
桥接必须声明原SIMION source-free FieldBundle作为碰撞载体及world/windows采样，
当前要求原生资产位于同一个显式workspace owner root、OA与assembly坐标为identity pose，不推断或伪造缺失场。
COMSOL有限外箱电位与SIMION Neumann不是同一边值问题，不能以同几何直接宣称结果精度等价。
桥接的显式导体支持采用 `equipotential_dirichlet_solid_interiors_v2`：只填严格实体内部，
重叠时保存完整电极组集合，并要求每个工作点全部电位精确相等。边界和未知节点保持无效，
不据此指定唯一物理owner。活动prepared支持标签须为v2并重新核对几何组与当前电位；
历史标签保持只读。此填值不增加FEM观测或精度资格，细节见[后端合同](COMSOL_BACKEND.md#saved-assembly-scalar-export)。

原生ID目前受SIMION Lua日志32-bit ABI限制，超过2^31−1在执行前拒绝。

Store只拥有小原生引用缓存与完整科学结果；PA/MPH继续由原执行owner管理，原始源使用防写/防删句柄保护。
`native_stages.json` 记录每阶段实际引用与复用，provenance的stage_productions是生产回调记录，
`native_worker_evidence.json` 是真实worker退出观察，均不冒充Compute/Fly次数。
无回执或回执缺件时观察数明确不可用，不能从缓存标志推断原生调用数。

SIMION原生配方可在 `[field_source.reference]` 显式选择已发布的 `fields`：
`path` 为相对于作者TOML的manifest路径，`sha256` 为该manifest摘要，`product_id = "fields"`。
预检从同一冻结Study重建模型，核对drive/clock、几何、数值配置、场设计与全部工作点成员；
执行全程持有原owner保护并跳过几何构建、模型准备和求场。缺件或不匹配时明确拒绝，不回退求场。
来源producer与当前tracer实现分别记入provenance；路径本身不决定科学身份。
这项科学场准入不代表任意历史PA文件均可直接交供应商重开，运行载体仍须符合公共原生输入隔离合同。

split原生SIMION运行由同一workflow将旧静态ground PA族转换为独立运行载体：
`grounded_runtime.prepare_grounded_runtime_fields` 在新owner内按冻结几何重新生成私有PA#，
对已证明的零电极Dirichlet与齐次外边界Neumann条件构造全新零势PA，保留电极及FSS并独立冷开核验；
不重开原已发布PA族，不执行Refine，不改原source/drive。派生与原producer均保护到Fly结束。
部署stage policy须显式声明 `prepare_grounded_runtime_fields` 的预算与保留类别，科学配方不保存这些工程设置。
该派生的小引用缓存由ArtifactStore管理，原始及派生PA分别由其既有原生owner管理删除。

## 补偿作者来源

补偿 Study 的 `model_input_sources.compensation_provenance` 可显式绑定相对 Study 路径与 SHA-256。
该小文件冻结原 resolved Recipe、原模型、轴向响应样本、原场、完整拟合和新 drive 摘要；加载时保存原字节。
消费前在同一 ArtifactStore 与执行 workspace 下保护实际样本和原场，重编原模型、重算拟合并核验新模型仅作声明的电极变化。
同 Store 的必要来源资产绑定运行，外部来源仍由其原 owner 管理。新场阶段可在受管 owner 中使用已认证响应基
组合新电压，再审计并发布与新模型绑定的完整 FieldBundle；该路径的软件测试不等于真实 SIMION 场或补偿准确度已验证。

可在安装环境中以同一 Store 检查来源：

```powershell
python -m msplatform validate <recipe.toml> --artifact-root <store> --execution-environment <environment.json> --profile <profile> --workspace <workspace>
```

## 局部原出生研究

原生 Study 版本2可在完整 parent 组件和连接之外显式给出 `local_scope`；装配仍保留被选区域与外部的边界关系。
单 MR 的独立原出生路径要求显式 vacuum、观测面列表、真实 neutral sampled FieldBundle、
`frozen_sampled_field` 数值标记及与该 Study 完全一致的模型和时钟。历史上游出口状态不自动成为新出生。
公开准入会重新核对场的生产来源和几何；真实单 MR 场及商业求解器结果需单独验证。
观测时间恰为出生时，记录使用原生 initialize 的实际六维状态；寿命内其他选定时间使用已接受步的插值，缺失或不完整记录不发布为完整结果。

## 区域轴向场诊断

SIMION split OA–TOF 的配方可以在 `[recording]` 明确声明单个
`field_intervention = {id = "base", selector = "real"}`，或声明非空的
`field_interventions = [{id = "base", selector = "real"}, {id = "drift", selector = "ideal:drift.ez"}]`。
两者不可同时出现，case ID 必须唯一。selector 支持 `real` 和 `ideal:` 后以 `+` 组合的
`accel.ez`、`drift.ez`、`stage1.ez`、`stage2.ez`、`reflectron.ez` 或 `all.ez`；
不支持的分量会在运行前拒绝。COMSOL scalar-world 先应用完整采样场，再按所选区域替换轴向分量。轴向值取实际已编译 Study 的电压与几何，其他方向的场保留原求解值。

case 集合使用同一个冻结原出生母群和场，分别保存完整 SI 结果与阶段回执；`inspect_results` 逐 case
重读和核对统计及初态，返回 collection，而不会把相同粒子 ID 合并为一个母群。case 执行和统计的
软件合同不等于商业求解器验证或数值精度认证。

## 结果与复用

每个运行独立保留 resolved.json、provenance.json、execution.json、summary.json、run_manifest.json，
以及 initial_states.parquet、terminal_states.parquet、events.parquet 和 trajectories.h5。
frame 为显式实验坐标（参考 laboratory，x/y/z右手轴、原点由作者初态声明），时钟为实验相对秒。
粒子 ID 为正 int64，物种、质量、电荷态、派生电荷与权重各自保存。未保存的任意时刻完整回放不作承诺。
当前参考初态快照使用结果 schema3 和 `unavailable_initial_snapshot`；原生已验证出生使用结果 schema2、
`initial_state_basis=native_birth_verified` 与 `primary_birth`，两者的 parent_particle_id 均为空。
两种新写结果均在各表及轨迹元数据中冻结相同的 Species 注册表，冷读时核对物种身份、质量和电荷。
历史结果 schema1、没有注册表的旧 schema2 仅按原合同冷读，并明确报告 `species_status=kind_unrecorded`；
不按质量、电荷或名称补造历史粒子种类。
原生出生、原生观测初态和普通快照各自保留来源，不相互冒充；本轮没有次级生成能力。事件序号按粒子递增，并保存平面轴法向穿越方向，重复穿面分别记录。
终态独立表达 physical_outcome 与 stop_reason；无法归属的 component/electrode/surface 是 null，
attribution_status/method 显式不可用；原生码、实体ID和诊断不丢弃。取消未启动粒子没有捏造的物理终点。
0 命中和时间截断可执行成功，统计分母保持完整母群；缺记录标记 incomplete，不补 lost。

检测观测覆盖另由 `data_integrity.detector_observation` 的版本1合同记录：
`complete`、`unavailable`、`not_requested` 或 `incomplete`，绑定完整原始粒子ID集合。
只有执行成功、数据完整且检测观测完整时才计算检测效率；观测不可用时效率为 null、到达及谱峰分析为 unavailable，
不能将空事件表解释为零命中。多物种分别检查各批覆盖；完整监测的真实零命中仍返回零。
旧结果重读先按原合同核验已存摘要，再返回 `legacy_unqualified` 的当前检测解释及原 `stored_summary`，不改写历史文件。

相同科学输入复用场和完整独立粒子批；label 无关，场或粒子/数值输入改变只失效对应依赖。
缓存缺件重算完整受影响批；run 自含科学数据，所以合格缓存回收后仍可重读历史统计。
`provenance.field.reused` 和 `provenance.batches[].reused` 报告实际命中，不能只看路径存在。
缓存和存储限制见[ArtifactStore](ARTIFACT_STORE.md)，实际测试证据见[迁移记录](development/architecture-migration.md)。

## 双锥 SDS 回调采样

单双锥 Study 可显式选择 SIMION 原生场和 SDS 气体。气体请求冻结环境作者、已发布
COMSOL `gas_field` 及 SDS 输入身份；运行准入时在来源保护下重读实际 CFD 数据并核对几何与环境。
Study 必须明确源到器件的刚体变换、原出生母群、驱动、网格和物理数值；当前 SDS 支持显式正离子、
零出生时间、原始编号和单位权重。

`recording.mode = "actual_callback_samples"` 使用显式 `sample_interval_us` 与 `end_time_us`。
保存的是求解器回调实际时刻；该间隔是后续调度参数，不保证均匀网格、严格最小间隔或命中指定时刻。
没有请求探测面时，不从终态推断探测事件。当前公共链已通过真实 Store 与受管四阶段的惰性软件测试，
其原生进程使用替身；这不是 SIMION/COMSOL 原生数值或仪器准确度验证。

## 原生追踪的工程执行控制

Python `run_recipe(..., tracking_execution={...})` 可显式提供 `unit_size`、
`recovery_reference` 和 `dispatch_profiles`；这些是执行与恢复声明，不写入科学 Study。
`recovery_reference` 是明确的历史轨迹 manifest 文件记录，运行时会在来源保护下验证；
失败或中断 predecessor 的单位索引与所需记录须由封存停止证据保护；短进程 guard 和 RF→IP 公共 Store 惰性部分重放已验证；
跨资产且缺独立来源保护的输入明确拒绝，商业原生重放未验证；
单位划分保留原始粒子 ID 和完整母群，不把分批结果当作新出生。调度 profile 不改变科学缓存键；
单位划分与恢复来源身份纳入追踪复用判断。当前仅支持单母群、非 discovery 的 SIMION 原生场链；
参考、SDS、标量桥和多 case 等未接该控制的路径会提前拒绝。多单位碰撞的商业求解结果尚未验证。

## 独立 OA 焦点研究

原始焦点 campaign 可由 Study 的 `model_input_sources.oa_focus_campaign` 显式指定相对路径和 SHA-256；
`oa_focus_campaign_birth_request` 只声明时钟、源组件、species ID、出生原点和权重，粒子 release_spec
从同一冻结 campaign 解析。Study 仍须明确追踪截止与观察时间，旧 campaign 未给出这些值时不自动猜测。
运行使用原 mirror-X、`surface=none` 的独立 OA 模型，分别记录 exit/focus 两面及实际终态；
由明确的 SIMION 安装选取并冻结其 TestPlane 文件。最终 run 冻结原作者、组件合同、实际模型、
本次原出生 packet、模型坐标出生行和认证面合同，供 `oa_focus_store_analysis.publish_focus_analysis`
受保护冷读分析。

公共 Store 与真实分析链已有3粒子惰性求解器测试；TestPlane和原生进程均为测试替身，
且合成运动不满足原campaign能量验收。这不是商业 SIMION native 运行或物理准确度资格。
