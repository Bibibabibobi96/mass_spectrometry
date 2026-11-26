# 公共粒子 tracing

新公开链数值积分非相对论 Lorentz 方程，支持明确真空中静态均匀 E+B 和具名轴对齐平面。
四份作者配置在[参考配方](../recipes/reference/uniform_e.toml)及其同目录；参考单元不是完整仪器。
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
`msplatform.tracing.trace_particles`、`msplatform.workflows.reference_tracing.run_recipe/inspect_results`。
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

原生运行必须同时提供 `--execution-environment <部署JSON> --profile <工程profile> --workspace <原生owner工作区>`，
另指定与原生 `workspace/artifacts` 分离的 `--artifact-root` 和正整数 `--reserve-bytes`。
部署使用既有ExecutionContext/阶段策略/共享host调度；科学值来自唯一冻结Study。
`validate` 返回 resolved与capabilities：implemented只说明编译路径，host_available只说明工具可用，
native_verified=false不代表原生求解已验证。实际逐组合证据查[迁移记录](development/architecture-migration.md)。

软件路径包括SIMION→SIMION、COMSOL→COMSOL，以及显式COMSOL OFF/ON资产采样到SIMION。
桥接必须声明原SIMION source-free FieldBundle作为碰撞载体及world/windows采样，
当前要求原生资产位于同一个显式workspace owner root、OA与assembly坐标为identity pose，不推断或伪造缺失场。
COMSOL有限外箱电位与SIMION Neumann不是同一边值问题，不能以同几何直接宣称结果精度等价。
原生ID目前受SIMION Lua日志32-bit ABI限制，超过2^31−1在执行前拒绝。

Store只拥有小原生引用缓存与完整科学结果；PA/MPH继续由原执行owner管理，原始源使用防写/防删句柄保护。
`native_stages.json` 记录每阶段实际引用与复用，provenance的stage_productions是生产回调记录，
`native_worker_evidence.json` 是真实worker退出观察，均不冒充Compute/Fly次数。
无回执或回执缺件时观察数明确不可用，不能从缓存标志推断原生调用数。

## 结果与复用

每个运行独立保留 resolved.json、provenance.json、execution.json、summary.json、run_manifest.json，
以及 initial_states.parquet、terminal_states.parquet、events.parquet 和 trajectories.h5。
frame 为显式实验坐标（参考 laboratory，x/y/z右手轴、原点由作者初态声明），时钟为实验相对秒。
粒子 ID 为正 int64，物种、质量、电荷态、派生电荷与权重各自保存。未保存的任意时刻完整回放不作承诺。
初态 parent_particle_id 为空且谱系标记为 unavailable_initial_snapshot，不把快照冒充真实出生记录；
本轮没有次级生成能力。事件序号按粒子递增，并保存平面轴法向穿越方向，重复穿面分别记录。
终态独立表达 physical_outcome 与 stop_reason；无法归属的 component/electrode/surface 是 null，
attribution_status/method 显式不可用；原生码、实体ID和诊断不丢弃。取消未启动粒子没有捏造的物理终点。
0 命中和时间截断可执行成功，统计分母保持完整母群；缺记录标记 incomplete，不补 lost。

相同科学输入复用场和完整独立粒子批；label 无关，场或粒子/数值输入改变只失效对应依赖。
缓存缺件重算完整受影响批；run 自含科学数据，所以合格缓存回收后仍可重读历史统计。
`provenance.field.reused` 和 `provenance.batches[].reused` 报告实际命中，不能只看路径存在。
缓存和存储限制见[ArtifactStore](ARTIFACT_STORE.md)，实际测试证据见[迁移记录](development/architecture-migration.md)。
