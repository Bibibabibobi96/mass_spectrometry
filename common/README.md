# 公共机制与维护入口

本目录维护跨项目复用的运行、数据和软件机制。器件几何、物理参数、科学工作流及资格由所属项目或
集成维护；执行命令与工具链先查[操作指南](../docs/OPERATIONS.md)，知识归属见
[仓库架构](../docs/REPOSITORY_ARCHITECTURE.md)。本页导航公共实现，并说明根级门禁和资源调度的维护边界。

## 按任务定位

| 要做的事 | 实现与说明 |
|---|---|
| 排查软件验证选了哪些阶段、失败退出或日志 | [门禁编排](#门禁编排)、[唯一目录](gate_catalog.json)、[并行调用器](parallel_gate_support.ps1) |
| 排查资源等待、进程归属、阶段切换和释放 | [主机资源实现](#主机资源实现)、[PowerShell入口](host_execution_lease.ps1)、[调度器](host_resource_scheduler.py) |
| 创建run、冻结输入、发布manifest、保护来源或恢复收尾 | [机器合同与生命周期API](contracts/README.md#python工作流的公共生命周期owner)；小Result保存在run外，原CLI的ResumeFinalization只恢复收尾 |
| 发现项目、校验设计请求与预览执行计划 | [项目发现与规划](contracts/README.md#项目发现) |
| 连接组件、解析完整配方与局部范围 | [公共连接合同](integration/README.md) |
| 构造母群、释放与粒子身份 | [离子释放](ion_release/README.md) |
| 计算峰宽、比较场或配对粒子数据 | [公共分析](analysis/README.md) |
| 维护COMSOL启动器与共享小模型 | [COMSOL实现](comsol/README.md) |
| 维护SIMION执行、PA缓存、批次与恢复 | [SIMION实现](simion/README.md)；批次协调使用 `Invoke-SimionBatchPhase`，科学物化和接受条件由调用方提供 |
| 维护STEP导入、SolidWorks生成和引用检查 | [SolidWorks桥接](solidworks/README.md) |
| 定位源码、产物、执行表示与主机库 | [路径机制](paths/README.md#公共运行根与原生执行表示)；身份使用持久位置，原生参数使用本次执行表示 |

只进入本次涉及的实现边界。文档结构与链接由`verify_documentation.ps1`和`documentation_links.py`检查；
跨语言实现规则由`verify_development_standards.py`检查；受管文本字节由`verify_repository_text_bytes.py`检查。
这些门禁的统一调度仍由下述目录负责，不在本页维护第二份阶段名单。
The existing scientific-boundary check also examines qualified SIMION accesses from applications:
an ordinary preparation-submodule import must not authorize access to sibling field or tracking
operations through Python's implicitly bound parent package. Named preparation modules and members
remain allowed; this is a dependency check, not a runtime reflection sandbox.

## 科学核心发行与旧入口

`mass-spectrometry-analysis` 0.4开发版的实现位于 `src/msplatform/`，使用 Python 3.11 与标准
setuptools src 布局。正式 API 是 `msplatform.ion_release.release` 的请求校验、生成、物化和读回，
`msplatform.assembly.resolve_assembly` 的完整布局与局部范围派生，
`msplatform.analysis.peak_metrics` 的 `AnalysisSettings`、`compute_time_peak_metrics`、`half_height_width`，
以及 `msplatform.contracts` 的刚体变换、粒子物理和本地 schema 校验。
0.3新增规范母群计数、中立转移状态、版本化电极绑定及强制方法元数据的名义质量峰入口；
电极组公开字段使用`electrode_group_id`，component3/plan5/binding2显式升版，旧资源含义保持。
普通文件摘要位于 `msplatform.io.file_identity`；P3开始实迁所选链的器件、SIMION编译和唯一执行机制，
当前已验证范围及尚未闭合的原生／恢复出口只查[集成状态](../integrations/docs/INTEGRATION.md#当前边界)。
参数、单位和资格边界查上述离子释放、连接和分析说明；安装不授予原生或科学资格。

根 `pyproject.toml` 是发行边界的唯一声明：发行实际 `msplatform` 实现及显式schema／例子／GEM／PS资源，
不把整个`common`或项目树、测试和商业载荷打进wheel。旧入口仅单向转发到新实现；冻结快照使用
自身的源码和资源，不以当前安装补齐旧快照。迁移阶段与退役期限见[路线图](../docs/ROADMAP.md#科学核心与平台边界迁移)。

Shared field-comparison mathematics and conditional TOF planning budgets are owned by
[`msplatform.analysis.field_comparison`](../src/msplatform/analysis/field_comparison.py)
and [`msplatform.analysis.tof_error_budget`](../src/msplatform/analysis/tof_error_budget.py).
Their former `common/analysis` implementations have been removed without aliases;
repository consumers use the installed owners. The TOF budget reports optional planning
limits and does not grant scientific qualification or impose a Case C accuracy gate.

The canonical SIMION GEM resolver normally reads installed package resources.
Downstream planning supplies its explicit frozen source root instead: registered
templates must exist inside that tree, with canonical containment checked and the
execution alias preserved for native paths. Missing frozen resources never fall
back to the installed package. This selects source provenance without changing
geometry, native mappings or scientific inputs.

本批保留发行名`mass-spectrometry-analysis`与import名`msplatform`，描述覆盖源、装配、合同和分析核心，
不宣称仓库运行器或商业后端均可安装。正式对外发行或发行边界重整前，最迟P4发行收口时，
发行维护者须依据外部索引所有权、锁和metadata消费者、旧wheel、冻结恢复以及同一import包的安装冲突
决定保留或迁名；本次不指定未经核实可用的新发行名，也不上传包索引。

### 独立导出 STEP：普通安装后的最短完整例子

本例使用已验证的`rf_oatof_functional_v1`完整RF＋三区OA／单反射装配，输出mm单位的
`physical_solids` STEP；理想零厚栅／数值面按导出报告明确排除，不凭一个代表实体替代整套装配。
这是一条headless CAD出口，不采样、不求场、不Fly，也不启动SolidWorks、COMSOL或SIMION。
它仍使用Python／CadQuery／OCCT和公共PowerShell运行owner；不是没有进程或没有文件副作用。

先准备Windows、Python 3.11、PowerShell 7，以及**同一指定发行版本**的wheel和配套锁文件。
CAD可选依赖实际锁在[`requirements-cad-step-lock.txt`](../requirements-cad-step-lock.txt)，当前为
CadQuery 2.8.0／cadquery-ocp 7.9.3.1.1；基础依赖锁见[`requirements-lock.txt`](../requirements-lock.txt)。
由发行提供者一起交付wheel和这两份锁，在新目录创建虚拟环境后安装：

```powershell
py -3.11 -m venv .venv
# 将 wheel 路径替换为你收到的指定发行文件；两份锁须来自同一发行。
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt -r requirements-cad-step-lock.txt
.\.venv\Scripts\python.exe -m pip install 'C:\releases\mass_spectrometry_analysis-0.4.0-py3-none-any.whl'
```

`pip -c`只约束版本，不会安装锁中列出的工具／依赖，不能代替上述`-r`安装。无需editable、
PYTHONPATH或作者checkout。下面代码保存为新工作目录的`export_step.py`，用该虚拟环境的
`python.exe -I export_step.py`运行。只需设置两个本机配置：实际PowerShell路径，以及部署时已确定的
**同机共享**host账本绝对路径；后者与该机器其他平台任务相同，不按study另建以绕过准入。
Save these paths once in the machine deployment described below; daily studies select its engineering profile:

```powershell
# Configure deployment/machine.json once with this machine's actual tool and shared ledger paths.
.\.venv\Scripts\python.exe -I export_step.py
```

```python
import json
from pathlib import Path
from msplatform import assembly as assembly_api, components, examples, execution, exporters

workspace = (Path.cwd() / "my_study").resolve()
workspace.mkdir(parents=True, exist_ok=True)
study = examples.load_example("rf_oatof_functional_v1")
parts = {name: components.resolve_component(request)
         for name, request in study.component_requests.items()}
assembly = assembly_api.assemble(study.recipe, parts)
# 可打印 study.to_dict() 查看／另存完整版本化请求、配方、位姿与数值。
options = study.cad_export
print(json.dumps(options, indent=2))
# 当前展开值：representation="physical_solids", write_pcurves=True, precision_mode=0。
# 这是CAD表示／STEP写出选项，不是场网格或求解精度。

# Optional English output stem and STEP assembly display name:
# options = {**options, "name": "RF-OA-TOF assembly"}
# Omitting name preserves results/assembly.step.

# Reuse the saved machine deployment described in integrations/README.md.
# Its selected stage_policy_path points to the engineering policy below.
context = execution.load_environment(
    Path("deployment/machine.json").absolute(), workspace=workspace, profile="standard",
)
cad = exporters.export_cad(assembly, format="step", options=options, context=context)
with (workspace / "cad-reference.json").open("x", encoding="utf-8") as stream:
    json.dump(cad.reference, stream, indent=2)
print(cad.data_path("step"))
print(cad.data_path("report"))
```

Save the following once as `deployment/stages.json`, beside the machine document
from the [deployment guide](../integrations/README.md#saved-machine-deployment). The
shared host ledger and tools are declared there; daily studies reuse that deployment.

```json
{
  "schema_version": 1, "role": "execution_stage_policy",
  "stages": {"export_cad": {
    "limits": {
      "wall_clock_seconds": 600,
      "transient_run_directory_bytes": 104857600,
      "process_tree_working_set_bytes": 4294967296,
      "minimum_system_available_memory_bytes": 1073741824,
      "compact_final_retained_bytes": 104857600,
      "automatic_retry_count": 0
    },
    "artifact_retention": {
      "policy_version": 1, "class": "solver_review",
      "reason": "Retain independent STEP and its complete source/report"
    }
  }}
}
```

上述预算沿本批实际导出使用的600秒／100MiB载荷与保留／4GiB进程树内存／1GiB可用内存，
重试0；是显式工程申报，不是适用于所有装配的测得峰值。更改规模前按实际成本调整这份输入，
不把科学尺寸放进context。owner在`my_study/artifacts/projects/instrument_assembly/runs/<新run_id>/`
保存冻结装配、选项、STEP、报告、日志与manifest；不要移动单个STEP后仍使用原ref冒充完整闭包。
教程本身不改库内文件，也无需Agent或商业软件操作。重复实践使用新study目录，原输入和产物保留。

The optional `options["name"]` is a printable ASCII filename stem; the exporter appends
`.step` and uses the same stem for the top assembly display name. Paths, separators,
Windows reserved names, control characters, and trailing spaces/dots are rejected.
English spaces, apostrophes, hyphens, and underscores are supported; workspace paths
may still contain Chinese characters. This changes display/output naming, not scientific IDs.

The root name must also differ from the exported physical members' `step_name` values.
For example, `oatof.detector` is a legal filename stem but conflicts with the detector
member in this example. The exporter rejects that conflict before loading the CAD
engine and asks for another export name. Ideal surfaces are excluded from this check.

The export report records `step_name` for each physical member. Labels combine the
actual instance and provider member semantics: RF rod/segment/group context and full
TOF member roles. Repeated instances remain distinct; a member containing multiple
solids retains all solids. Report member IDs, source references, transforms, and ideal
item exclusions remain the identity authority; imported body order is not an identity key.

导出进程退出后，新进程可独立做已发布数据的完整性检查：

```python
import json
from pathlib import Path
from msplatform.results import open_artifact
ref = json.loads(Path("my_study/cad-reference.json").read_text(encoding="utf-8"))
cad = open_artifact(ref, expected_kind="cad_geometry")
print(cad.data_path("step"))  # 原manifest发布绑定及文件bytes/SHA复核
print(cad.metadata)
```

`open_artifact`不运行CAD引擎／GUI，只验证发布记录与文件身份。装有上述可选CAD依赖后，
可在同一独立进程调用实际STEP冷读检查，无需重新导出、执行owner、点击或启动SolidWorks：

```python
inspection = exporters.inspect_cad(cad, checks={
    "schema_version": 1, "kind": "physical_solids_step_v1", "probes": [],
})
print(inspection["status"], inspection["failed_checks"])
```

检查将实际冷读的B-rep有效性、实体数和总体积与冻结装配的唯一CSG来源比较，复用导出时的
OCCT序列化精度profile；体积界不是物理／制造公差。可显式给出
`{"probe_id": "具名点", "point_mm": [x, y, z]}`世界坐标点，比较来源CSG与实际STEP的内外关系；
不自动发明点、不承诺逐孔／逐构件拓扑配对或完整尺寸认证。`consistent`只表示所列检查一致，
`mismatch`报告实测差异；两者均不授予科学或制造资格。搬迁后使用显式resolver打开的`cad`，
检查消费其已验证实际位置，不尝试重新打开报告中的历史绝对路径。

几何构造、STEP导出、只读检查与可选应用查看是独立动作；本批既有SolidWorks冷打开证据不代替
这些语义检查，也不代表任意器件／姿态已支持。准确能力和GUI验收范围查
[集成状态](../integrations/docs/INTEGRATION.md#当前边界)。

SolidWorks兼容查看是后续显式可选动作`applications.open_model(cad, application="solidworks", context=...)`，
另需应用、配对模板与`open_model`预算，见本节下文；不是生成STEP的前置，也不自动保存／转存。
同一`assembly`可并列传给`msplatform.backends.simion.compile_geometry(assembly, numerics=study.geometry_numerics)`，
纯编译不采样、不写工作目录、不Refine／Fly或开GUI；不经STEP导入来反建后端几何。
其原生build／prepare／solve另行显式调用，不能从CAD完成推出模型或场资格。
端口便利连接用显式rotation与gap的`msplatform.assembly.mate_ports`；分域与副作用边界见
[仓库架构](../docs/REPOSITORY_ARCHITECTURE.md#可安装科学核心与迁移边界)。

同一示例的`cad_export`、`drive`和`physics`均可展开查看；驱动电极组缺省从同一解析提供者展开，
可显式覆盖完整科学组映射，不要求作者填写SIMION编号。示例pulse保留既有功能输入的明确时序，
时钟使用发行包内版本化authority及原32字节零epoch。模型输入来源说明保存在示例的
`model_input_sources`；这不是新的精度或优化基线。
`msplatform.backends.simion.prepare_model(geometry, drive=study.drive, physics=study.physics, context=context)`将驱动绑定到
既有几何，单独申请`prepare_model`工程预算和保留政策。自定义clock authority可显式提供
`drive["clock_authority"]={"contract": <文件record>, "data_root": <绝对数据根>}`；`drive["clock"]`
仅给`phase_reference_instrument_time_us`，epoch ID与SHA由唯一authority验证器读取，不由作者重复抄写。
完整原生模型／GUI及后续求场验收状态仍以集成正文为准，接口存在不代表该链已经完成。

`msplatform.backends.simion.solve_fields(model, numerics=..., context=context, reuse_fields=None)`使用已发布未求解模型及其唯一驱动。
求场数值显式提供`frontend_domains`（含各成员`refine_convergence_v`）、RF模型的
`rf_reference_voltage_v`及三角色`downstream_convergence_v`；它们不放进执行context。
`solve_fields`工程policy另要求`reserved_run_payload_bytes`，为原总commitment以内的非负整数，
从cache实际入账量扣减commitment时仍保留该run载荷额度；缺值或越界在启动前拒绝。
可选`reuse_fields`只指定一个已发布场的引用，后端按真实空间输入判断适用性，新产品仍绑定本次模型／钟；
不能传latest、改变源来暗中求场，或把未求解PA当已有场。普通安装和 worker 运输已有分阶段证据；
完整场包发布、后续Fly及搬迁后继续执行的范围仍查集成正文，不能从接口存在推定完成。

`msplatform.results.open_artifact(reference, expected_kind=...)`读取显式manifest record和`product_id`，校验已完成发布的
所选数据闭包；不恢复执行环境、不运行求解器。发布者在原manifest的`products`字段绑定版本1产品：
`schema_version/kind/status/metadata/data`，其中`status="complete"`，`data`每个具名成员是同一manifest
inputs／outputs中的原文件record。reference为`{"manifest": <文件record>, "product_id": <具名产品>}`。
返回的`OpenedArtifact`提供metadata／原producer状态／data_records的独立视图，`data_path(name)`在
后续消费前核对该成员身份。读取不授予场映射适用性或科学资格，实际track／analysis仍执行其领域合同。
The reader imports only read-only I/O and data contracts. Exact file records, publication-incomplete
checks and Windows closed-file identity belong to `msplatform.io`; importing results does not load
execution owners, publication writers, locks, schedulers or historical code. Active consumers use this
entry directly; the former execution reader/record/identity modules are removed rather than forwarded.
新产物的数据成员可用manifest相对路径；旧绝对引用搬迁需显式`resolver(record, base_directory)`返回
精确绝对路径，保留原record/hash，不按latest搜索。`data_locations`与`manifest_location`返回打开时已验证的
实际位置快照，不替代后续`data_path`复核或原owner的写入保护。搬迁后的数据可读不自动改变原容量owner；
真实三进程链的完成状态仍查集成正文。

`msplatform.ion_release.sample_release`消费版本1的`canonical_birth_source_request`：显式`release_spec`（原生成器合同）、
`clock`（epoch与authority SHA）、`instrument_origin_us`、`species_id`、`source_component_id`与
`relative_weights`，可另给首次作者`particle_ids`。`relative_weights=None`明确使用单位权重；映射则
精确覆盖实际作者ID，JSON十进制ID键与整数ID键不能重复。返回`ReleaseRealization`的`rows`是原CSV1
出生状态，`mother`覆盖本次实际释放的全部粒子，`to_dict()`展开原spec、生成器原始行及初始ID映射。
所有公开嵌套视图返回副本；生成族`mother_particle_count`用于原采样前缀关系，不虚构本run未释放母粒子。
此入口不重编号已有handoff，不把snapshot重标为birth，也不声明未观测相位；原低层
`msplatform.ion_release.release.generate_release_states`合同和采样次序保持。实际原生执行仍须验证相同
clock authority的真实发布record，并由backend检查原生ID表示范围。

`msplatform.backends.simion.track(fields, particles, propagation=..., observations=..., numerics=..., context=...,
source_reference=None, unit_size=None, recovery_reference=None, dispatch_profiles=())`
将已发布SIMION FieldBundle接到同一运行owner；未求解model直接拒绝。
`particles`为`ReleaseRealization`、其完整`to_dict()`或纯handoff的`HandoffResult`。handoff必须显式提供
已发布`trajectory_result`的`source_reference`，backend从其原始观测复核实际来源，不仅信任调用者6D状态。
propagation版本1显式给出`scope`、`end_policy`、`consumed_plane_events`与`stop`；截止规则选择原出生以来
的`maximum_particle_age_us`或共同仪器钟的`absolute_instrument_end_us`，不重置出生或RF相位。
observations给出`plane_observations`及可选`observation_times_us`；numerics给出`maximum_step_us`、
`trajectory_quality`及存在RF时的`rf_steps_per_period`。工程limits/retention来自独立`track` stage policy。
`unit_size=None`保留一个完整cohort单元；正整数按源行ordinal划分重放单元，不重编号原ID、不切割完整母群。
`recovery_reference`为明确前驱`run_manifest.json`的完整文件record，不是Result或粒子checkpoint。
原planner逐项验证直接前驱绑定、实际完成与输入字节，只复用完整单元；不完整单元整批重放，原失败保持。
`dispatch_profiles`为显式已有资源profile列表；科学numerics不混入worker／调度设置，重计算仍受原公共准入控制。
公共接线与原owner的四单元软件恢复已有分层回归；零handoff保完整母群且无原生调用。
普通安装后的真实Fly、真实SIMION角色的多单元派发与跨进程分析仍待验收，不能据接口存在宣布完成。

`msplatform.backends.simion.analyze(result, selection=..., method=...)`只读已发布SIMION轨迹数据，不启动owner或工具。
selection版本1明确`particle_ids`、`observation`与`unexecuted_fate_label_field`；完整母群继续作为分母，
未执行粒子的原fate字段由调用者明确指定，缺分类返回`insufficient_classification`，不猜作loss。
observation可为census的null、`{"kind":"canonical_event","event":...}`，或具名plane的
`observation_id/direction/occurrence`。method版本1选择`census`，或`time_peak`加显式`time_reference`
（epoch、authority SHA、`instrument_time_us`）及`settings`（原AnalysisSettings字段或显式null）。
峰使用共同仪器参考，保留原算法metadata；缺测／非等权分别报告不足／不支持，不补飞或授予精度资格。

`applications.open_model(cad, application="solidworks", context=context)`是独立、同步的STEP查看动作。
`open_model` stage runtime明确`com_class="SldWorks.Application.30"`、现有clean `part_template`及`assembly_template`绝对路径与
`lifecycle="document_close"`；显式工具路径使用`tools["solidworks"]`。它拒绝接管已有应用，复制已发布
STEP与模板后打开自己的文档；导入完成后、进入查看等待前恢复并读回临时导入偏好，
在原回执保留导入前值。关闭文档后按原owner收尾；若整个自有应用先正常退出，
只有同一原Popen句柄的PID／终态与已完成偏好恢复均确认后，才跳过对已断开COM的重复清理。
最后一次文档计数查询不可用时，仅在此前已确认自有文档关闭、无其他文档且无原始错误的特定懒属性访问边界，
保留结构化诊断并等待同一原句柄的真实终态；属性缺失本身不证明应用退出。等待告警期限不释放保护或强停进程。
非零退出、未知身份或未恢复仍报告失败；原进程家族排空与输入保护保持，不要求编辑内部ACK文件。
不调用SaveAs、Refine或Fly；已取得普通安装后的实际打开／关闭／配置恢复证据，但启动仍需处理已识别提示，
内部尺寸／孔槽验收与自动启动修复继续保留，准确范围见集成正文。
可选`checks={"schema_version":1,"kind":"selected_solid_geometry_v1","selected_step_members":[...]}`
选择该CadArtifact导出报告中的1至7个明确`step_name`。原worker直接检查本次LoadFile4返回的文档，
冻结并保护来源报告；未保存装配的路径可以为空，不按标题或ActiveDoc寻找替代对象。
返回`selected_geometry`中的原生实体／质心／表面观测，getter不可用或超出界限记`incomplete`；
这些观测不是孔形、尺寸或科学资格通过。SIMION查看不接受此SolidWorks检查选项。

`applications.open_model(model, application="simion", context=context)`接受已发布的未求解PreparedModel；
已打开的PreparedModel省略application时也选择SIMION，裸引用应明确application。
它沿唯一模型writer复制完整raw／surface／clock／drive并执行容器build、冷读回verify，再显式打开新IOB；
四个操作为`materialize_geometry/build_model/verify_model/view_model`。这是同设计的新查看容器，不是原IOB字节搬迁，
不调用Refine／Fly、不给模型补粒子，不重新生成PA。GUI保持原进程保护直到正常退出；没有内部ACK文件。
显式GUI调用沿原process owner传递`window_style="Normal"`并记入查看请求；其他进程仍默认`Hidden`，
仅接受这两个精确值，不按stage名称推断可见性，也不改变进程身份、输入保护或资源释放规则。
`open_model`策略的SIMION runtime仅接受可选布尔`simion_allow_asynchronous_io`，工具路径显式给出`simion.exe`。
普通SDK11已取得真实SIMION可见窗口、四个PA实例以及正常关闭的证据；具体范围见集成正文，
不能用headless读回或进程退出码推定GUI检查、场精度或Formal资格。

公共process owner的早期观测沿原`usage_path`写入`process_start`：同一启动句柄的实际PID和出生ticks、
原run／role／stage、请求的程序／窗口模式，以及可取得或明确unknown的实际image。
这是启动时事实，不代表持续存活、窗口可见、模型加载或计算完成；最终退出与保护释放仍以原owner收据为准。
该新增记录已完成定向软件测试、独立复核及普通SDK12真实SIMION调用核验，不回填旧运行；
启动事实与最终退出收据的各自适用范围见集成正文。
宿主事务stdin断管时保留原异常，并附加已启动子进程的退出码与stdout/stderr收集结果；
这不推断旧CI断管根因。RF恢复测试的外部诊断采用UTF-8替换解码，正式JSON/CSV仍严格校验编码。

`execution.resume_run(result_path, mode="finalization", context=context, completion_api=...)`接原owner的停止后收尾；
调用方显式传入原操作的完成策略，execution不反向导入后端来猜测策略，
只读核对原request／completion／容量权威后继续原发布，不回调科学动作。Result是可变运输文件，
传入明确绝对路径；它不能通过删除自身hold字段或标complete解除原容量保护。
完整终态重复调用还校验原manifest／seal及lease实际释放，随后只读返回。
不完整单元重跑用`track(..., recovery_reference=...)`的新运行身份，不能将其冒充收尾或native checkpoint。

`msplatform.capabilities.capabilities({"schema_version":1,"operation":...,"arguments":...}, environment=None)`复用实际纯
provider／compiler／planner检验明确输入，不执行原生动作。规划参数及`software_scope`明确区别于执行API；
缺真实输入返回`insufficient_request`，原validator异常保类型／原因返回`rejected`，未提供纯查询适配的动作
返回`unsupported`，不据函数存在推定可启动。可选environment只接受调用者明确的版本1工具观测，
不搜索PATH或探测许可；合同接受、环境声明、执行未评估及原生资格未授予分别返回。
Tracking queries validate the actual whole-unit planner, including explicit ordinal partitions and
declared reuse keys. They do not authenticate reuse evidence or grant native/checkpoint qualification;
incomplete units are replayed whole rather than resuming a process state.

### P3 有限桥与局部适配件的退出责任

本轮核对单向模块／CLI／资源桥及18个局部职责适配件。下表是尚未退役路径的有限清单，
不是运行配置、支持白名单或已完成退役声明；同一旧文件可委托多个具名规范所有者。所有者均须最迟P4
迁移真实活动调用、旧CLI和冻结声明，保留普通安装、树外冷快照、缺资源拒绝与原失败语义回归后，才移除旧入口。
局部适配件还承担作者文件、profile、来源／receipt或治理职责，不能因科学函数已迁走就整文件删除。

表内“引用”是本轮源码的精确module/path字面引用；JSON库存条目只证明声明，代码引用也不证明该次运行实际调用。
仅basename命中的Lua／PS引用在表内单列为待核候选，不算已确认消费者；退出前仍由列出的所有者核对动态／跨语言入口。
F5与continuous03的已发布inputs选择规范正文／资源，不证明其余旧调用已退出，也不替代逐调用验证。
历史run、冻结快照和只读reader不列为必须重写的活动桥；没有字面命中不证明没有动态或外部用户。

路径均相对仓库根；“目录／：文件名”逐一组成有限完整路径，不表示通配目录。规范模块从`src/`发行；
资源项按包内实际路径列出。责任列适用于该行全部引用及尚待核实的旧入口，期限统一最迟P4。


<details>
<summary>待退役单向桥：精确路径、规范所有者与生产字面引用</summary>

|旧路径|规范所有者／资源|本轮精确生产引用|退出责任|
|---|---|---|---|
|`common/host_execution_lease.ps1`|`msplatform/execution/resources/host_execution_lease.ps1`<br>`msplatform/execution/host_resource_scheduler.py`|未确认精确字面生产引用；须核动态／CLI／冻结入口，不据此判死代码<br>跨语言／路径静态候选（未证实调用）：`common/`：`gate_catalog.json`、`host_resource_python.ps1`、`resource_budget_support.ps1`、`verify.ps1`、`verify_documentation.ps1`、`verify_repository_hygiene.ps1`、`verify_toolchain.ps1`<br>`common/comsol/`：`run_comsol_r2025b.ps1`<br>`common/contracts/`：`invoke_solver_review_retirement.ps1`、`run_artifact_support.ps1`<br>`projects/apertured_tube_electron_impact_ion_source/`：`verify_project.ps1`<br>`projects/dual_cone_tandem_quadrupole_ion_interface/`：`verify_project.ps1`<br>`projects/dual_pressure_rectilinear_ion_processor/`：`verify_project.ps1`<br>`projects/orthogonal_accelerator/`：`verify_project.ps1`<br>`projects/orthogonal_accelerator/simion/`：`run_component_focus_flight.ps1`、`run_component_focus_pa.ps1`、`run_component_focus_workflow.ps1`<br>`projects/parallel_mirror_dual_stripe_mr_tof/`：`verify_project.ps1`<br>`projects/parallel_mirror_dual_stripe_mr_tof/analysis/`：`run_downstream_workpoint_iteration.ps1`、`run_dual_stripe_operating_seed.ps1`、`run_mirror_exact_k_operating_point.ps1`、`run_mirror_fixed_grid_voltage_correction.ps1`、`run_mirror_l0_l1_candidate.ps1`、`run_resolved_cad_export.ps1`、`run_two_prism_segmented_continuation.ps1`、`run_two_prism_segmented_coverage.ps1`<br>`projects/parallel_mirror_dual_stripe_mr_tof/simion/`：`run_native_static_field_provider.ps1`<br>`projects/rf_multipole_ion_optics/`：`verify_project.ps1`<br>`projects/rf_multipole_ion_optics/runtime/`：`run_finite_3d_transport.ps1`、`run_simion_finite_3d_transport.ps1`<br>`projects/rf_multipole_ion_optics/workflows/interface_readiness/`：`run_comsol.ps1`<br>`projects/rf_multipole_ion_optics/workflows/mass_filter_reference/`：`run_finite_length.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/`：`verify_project.ps1`<br>`projects/single_reflection_oa_tof_mass_analyzer/analysis/`：`candidate_source_closure.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/`：`build_formal_delivery.ps1`、`run_candidate_flight.ps1`、`run_parameterized_geometry_smoke.ps1`<br>`projects/single_reflection_oa_tof_mass_analyzer/workflows/formal_reference/`：`run_formal_validation.ps1`<br>`projects/single_reflection_oa_tof_mass_analyzer/workflows/ideal_source_comparison/`：`run_comparison.py`<br>`projects/transverse_helical_filament_wehnelt_electron_gun/`：`run_build_only_smoke.ps1`、`verify_project.ps1`<br>`integrations/`：`verify_integration.ps1`<br>`integrations/config/`：`runtime_dependencies.json`<br>`integrations/workflows/oa_mr/`：`execute.ps1`<br>`integrations/workflows/paired_accelerator_pulse/`：`execute.ps1`<br>`integrations/workflows/paired_accelerator_static_field/`：`execute.ps1`<br>`integrations/workflows/prepared_joint/`：`execute.ps1`|公共执行／缓存／钟所有者；最迟P4|
|`common/resource_budget_support.ps1`|`msplatform/execution/resources/resource_process_support.ps1`<br>`msplatform/execution/resources/simion_dispatch_support.ps1`|未确认精确字面生产引用；须核动态／CLI／冻结入口，不据此判死代码<br>跨语言／路径静态候选（未证实调用）：`common/`：`gate_catalog.json`、`host_resource_python.ps1`<br>`common/comsol/`：`run_comsol_r2025b.ps1`<br>`common/contracts/`：`run_artifact_workflow.ps1`<br>`projects/dual_pressure_rectilinear_ion_processor/simion/`：`prepare_gui_replay.ps1`、`run_functional.ps1`<br>`projects/parallel_mirror_dual_stripe_mr_tof/analysis/`：`run_ip_prism_distance_study.ps1`<br>`projects/parallel_mirror_dual_stripe_mr_tof/comsol/`：`run_corridor_field_provider.ps1`<br>`projects/parallel_mirror_dual_stripe_mr_tof/simion/`：`run_native_static_field_provider.ps1`<br>`projects/rf_multipole_ion_optics/runtime/`：`run_finite_3d_transport.ps1`、`run_simion_finite_3d_transport.ps1`、`simion_execution.ps1`<br>`projects/single_reflection_oa_tof_mass_analyzer/analysis/`：`candidate_source_closure.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/`：`build_formal_delivery.ps1`、`run_candidate_flight.ps1`<br>`projects/transverse_helical_filament_wehnelt_electron_gun/`：`run_build_only_smoke.ps1`<br>`integrations/config/`：`runtime_dependencies.json`<br>`integrations/workflows/local_frontend/`：`execute.ps1`<br>`integrations/workflows/oa_mr/`：`execute.ps1`<br>`integrations/workflows/paired_accelerator_pulse/`：`execute.ps1`<br>`integrations/workflows/paired_accelerator_static_field/`：`execute.ps1`<br>`integrations/workflows/prepared_joint/`：`execute.ps1`<br>`integrations/workflows/single_reflection_flight/`：`execute.ps1`|公共执行／缓存／钟所有者；最迟P4|
|`integrations/runtime/pure_boundary_validator.py`|`msplatform.backends.simion.tracking_program`|未确认精确字面生产引用；须核动态／CLI／冻结入口，不据此判死代码|integration所有者；最迟P4|
|`projects/orthogonal_accelerator/analysis/electrode_topology.py`|`msplatform.components.orthogonal_accelerator.electrode_topology`|`projects/orthogonal_accelerator/analysis/`：`assembly_interface.py`|OA所有者；最迟P4|
|`projects/orthogonal_accelerator/analysis/sectioned_geometry.py`|`msplatform.components.orthogonal_accelerator.sectioned_geometry`|`projects/orthogonal_accelerator/analysis/`：`assembly_interface.py`<br>`integrations/runtime/`：`single_flight_frontend.py`|OA所有者；最迟P4|
|`projects/rf_multipole_ion_optics/core/axial_acceleration.py`|`msplatform.components.rf_multipole.axial_acceleration`|未确认精确字面生产引用；须核动态／CLI／冻结入口，不据此判死代码|RF所有者；最迟P4|
|`projects/rf_multipole_ion_optics/core/connector_geometry.py`|`msplatform.components.rf_multipole.connector_geometry`|未确认精确字面生产引用；须核动态／CLI／冻结入口，不据此判死代码|RF所有者；最迟P4|
|`projects/rf_multipole_ion_optics/core/electrode_topology.py`|`msplatform.components.rf_multipole.electrode_topology`|未确认精确字面生产引用；须核动态／CLI／冻结入口，不据此判死代码|RF所有者；最迟P4|
|`projects/rf_multipole_ion_optics/core/face_sections.py`|`msplatform.components.rf_multipole.face_sections`|未确认精确字面生产引用；须核动态／CLI／冻结入口，不据此判死代码|RF所有者；最迟P4|
|`projects/rf_multipole_ion_optics/core/interface_geometry.py`|`msplatform.components.rf_multipole.interface_geometry`|`projects/rf_multipole_ion_optics/analysis/`：`analyze_comsol_transport_metrics.py`、`analyze_source_model_comparison.py`、`generate_official_particle_table.py`、`numerical_observables.py`、`stationary_field_sampling.py`、`transport_diagnostics.py`<br>`projects/rf_multipole_ion_optics/core/`：`component_port.py`<br>`projects/rf_multipole_ion_optics/runtime/`：`finite_extraction_context.py`、`simion_batch_continuation.py`、`simion_particle_source.py`<br>`projects/rf_multipole_ion_optics/workflows/interface_readiness/`：`run_comsol.ps1`、`run_simion.ps1`<br>`projects/rf_multipole_ion_optics/workflows/mass_filter_reference/`：`run_simion.ps1`|RF所有者；最迟P4|
|`projects/rf_multipole_ion_optics/core/round_rod_geometry.py`|`msplatform.components.rf_multipole.round_rod_geometry`|`common/`：`gate_catalog.json`<br>`projects/dual_cone_tandem_quadrupole_ion_interface/analysis/`：`resolve_geometry.py`<br>`projects/dual_pressure_rectilinear_ion_processor/analysis/`：`guide_interface.py`|RF所有者；最迟P4|
|`projects/rf_multipole_ion_optics/simion/simion_geometry.py`|`msplatform.backends.simion`|`common/`：`gate_catalog.json`<br>`projects/dual_cone_tandem_quadrupole_ion_interface/simion/`：`geometry.py`<br>`projects/rf_multipole_ion_optics/analysis/`：`sync_simion_geometry.py`<br>`projects/rf_multipole_ion_optics/runtime/`：`run_simion_finite_3d_transport.ps1`<br>`integrations/runtime/`：`single_flight_frontend.py`|RF所有者；最迟P4|
|`projects/single_reflection_oa_tof_mass_analyzer/analysis/accelerator_electrical.py`|`msplatform.components.single_reflection_oa_tof.accelerator_electrical`|`projects/single_reflection_oa_tof_mass_analyzer/analysis/`：`candidate_source_closure.py`<br>`integrations/workflows/paired_accelerator_static_field/`：`prepare.py`|单反射TOF所有者；最迟P4|
|`projects/single_reflection_oa_tof_mass_analyzer/analysis/accelerator_geometry.py`|`msplatform.components.single_reflection_oa_tof.accelerator_geometry`<br>`msplatform.backends.simion.accelerator_projection`|`projects/single_reflection_oa_tof_mass_analyzer/analysis/`：`candidate_source_closure.py`<br>`integrations/workflows/paired_accelerator_static_field/`：`prepare.py`|单反射TOF所有者；最迟P4|
|`projects/single_reflection_oa_tof_mass_analyzer/analysis/assembly_interface.py`|`msplatform.components.single_reflection_oa_tof.assembly_interface`<br>`msplatform.backends.simion.tof_assembly_interface`|`integrations/workflows/paired_accelerator_static_field/`：`prepare.py`|单反射TOF所有者；最迟P4|
|`projects/single_reflection_oa_tof_mass_analyzer/analysis/electrode_topology.py`|`msplatform.components.single_reflection_oa_tof.electrode_topology`|未确认精确字面生产引用；须核动态／CLI／冻结入口，不据此判死代码|单反射TOF所有者；最迟P4|
|`projects/single_reflection_oa_tof_mass_analyzer/analysis/finite_interval_design_compiler.py`|`msplatform.components.single_reflection_oa_tof.finite_interval_design_compiler`|未确认精确字面生产引用；须核动态／CLI／冻结入口，不据此判死代码|单反射TOF所有者；最迟P4|
|三份单反射variant Lua旧转发器（已退役）|`msplatform/backends/simion/resources/build_{reflectron,detector,flight_tube}_variant.lua`|实际CLI、冻结依赖、集成与物理测试均已直接消费安装实现；旧项目路径无转发|已退出|

|`projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/candidates/oatof_analyzer_component.lua`|`msplatform/backends/simion/resources/oatof_analyzer_component.lua`|未确认精确字面生产引用；须核动态／CLI／冻结入口，不据此判死代码<br>跨语言／路径静态候选（未证实调用）：`integrations/config/`：`runtime_dependencies.json`<br>`integrations/workflows/single_reflection_flight/`：`runtime.py`|单反射TOF所有者；最迟P4|
|`common/host_resource_scheduler.py`|`msplatform.execution.host_resource_scheduler`<br>`msplatform.execution.resources`|未确认精确字面生产引用；须核动态／CLI／冻结入口，不据此判死代码|公共执行／缓存／钟所有者；最迟P4|

</details>

<details>
<summary>17个局部适配件（仍保留外层职责）：精确路径、规范所有者与生产字面引用</summary>

|旧路径|规范所有者／资源|本轮精确生产引用|退出责任|
|---|---|---|---|
|`common/host_resource_python.py`|`msplatform.execution.process_transport`|`common/`：`gate_catalog.json`、`host_resource_python.ps1`<br>`common/contracts/`：`run_artifact_workflow.ps1`<br>`projects/parallel_mirror_dual_stripe_mr_tof/analysis/`：`mirror_exact_k_operating_point.py`、`mirror_fixed_grid_voltage_correction.py`、`mirror_l0_hardware_candidate.py`、`mirror_l0_l1_hardware_candidate.py`、`run_mirror_exact_k_operating_point.ps1`、`run_mirror_l0_l1_candidate.ps1`、`run_two_prism_segmented_continuation.ps1`、`run_two_prism_segmented_coverage.ps1`、`two_prism_segmented_coverage.py`、`two_prism_segmented_voltage_continuation.py`<br>`projects/rf_multipole_ion_optics/runtime/`：`run_ideal_transport.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/analysis/`：`candidate_source_closure.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/`：`build_formal_delivery.ps1`、`run_candidate_flight.ps1`<br>`projects/single_reflection_oa_tof_mass_analyzer/workflows/ideal_source_comparison/`：`run_comparison.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/workflows/radial_compaction/`：`run_campaign.py`<br>`integrations/config/`：`runtime_dependencies.json`|公共执行／缓存／钟所有者；最迟P4|
|`integrations/runtime/frontend_field_plan.py`|`msplatform.backends.simion.physical_samples`|`integrations/runtime/`：`local_frontend_field_support.ps1`|integration所有者；最迟P4|
|`projects/orthogonal_accelerator/analysis/accelerator_time_focus.py`|`msplatform.components.orthogonal_accelerator.accelerator_time_focus`|`projects/orthogonal_accelerator/analysis/`：`component_focus_workflow.py`、`three_zone_ideal_theory.py`、`two_zone_theory.py`<br>`projects/parallel_mirror_dual_stripe_mr_tof/analysis/`：`run_mirror_l0_l1_candidate.ps1`、`simion_candidate_reference.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/`：`verify_project.ps1`<br>`projects/single_reflection_oa_tof_mass_analyzer/analysis/`：`candidate_source_closure.py`、`oatof_oaaccelerator_coupling.py`、`three_zone_ideal_theory.py`、`three_zone_t5_simion_candidate.py`、`three_zone_theory_experiment.py`、`validate_longitudinal_prediction.py`、`verify_axial_ideal_closure.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/config/candidates/`：`accelerator_grid_aligned_strict_focus.json`<br>`projects/single_reflection_oa_tof_mass_analyzer/config/experiments/`：`three_zone_solver_free_funnel_v1.json`、`three_zone_solver_free_funnel_v2.json`<br>`projects/single_reflection_oa_tof_mass_analyzer/workflows/formal_reference/`：`verify_geometry_derivation.py`<br>`integrations/workflows/local_frontend/`：`prepare.py`|OA所有者；最迟P4|
|`projects/orthogonal_accelerator/analysis/two_zone_geometry.py`|`msplatform.components.orthogonal_accelerator.two_zone_geometry`|`projects/orthogonal_accelerator/analysis/`：`assembly_interface.py`、`component_focus_workflow.py`、`execution_binding.py`<br>`projects/orthogonal_accelerator/simion/`：`run_component_focus_flight.ps1`<br>`projects/parallel_mirror_dual_stripe_mr_tof/analysis/`：`run_mirror_l0_l1_candidate.ps1`、`simion_candidate_reference.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/analysis/`：`candidate_source_closure.py`、`three_zone_t5_simion_candidate.py`、`three_zone_theory_experiment.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/config/experiments/`：`three_zone_solver_free_funnel_v1.json`、`three_zone_solver_free_funnel_v2.json`|OA所有者；最迟P4|
|`projects/rf_multipole_ion_optics/core/compile_design_request.py`|`msplatform.components.rf_multipole.compile_design_request`|`projects/rf_multipole_ion_optics/analysis/`：`resolve_contract.py`、`rfquad_contract.py`、`verify_resolved_design.py`<br>`projects/rf_multipole_ion_optics/runtime/`：`design_profile.py`、`resource_budget.py`、`runtime_profile.py`、`run_finite_3d_transport.ps1`、`run_round_rod_field_screen.ps1`、`run_simion_finite_3d_transport.ps1`|RF所有者；最迟P4|
|`projects/rf_multipole_ion_optics/core/grounded_shield.py`|`msplatform.components.rf_multipole.grounded_shield`|`projects/single_reflection_oa_tof_mass_analyzer/analysis/`：`candidate_source_closure.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/workflows/mass_spectrum_candidate/`：`run_mass_spectrum_candidate.ps1`|RF所有者；最迟P4|
|`projects/single_reflection_oa_tof_mass_analyzer/analysis/geometry_contract.py`|`msplatform.io.file_identity`<br>`msplatform.components.single_reflection_oa_tof.geometry_contract`<br>`msplatform.backends.simion.tof_geometry`|`projects/single_reflection_oa_tof_mass_analyzer/analysis/`：`candidate_source_closure.py`、`compile_candidate_design.py`、`resolve_geometry.py`、`simion_component_pa_plan.py`、`sync_geometry_contract.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/workflows/mass_spectrum_candidate/`：`run_mass_spectrum_candidate.ps1`<br>`projects/single_reflection_oa_tof_mass_analyzer/workflows/radial_compaction/`：`run_campaign.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/workflows/reflectron_voltage_compensation/`：`run_compensation.py`|单反射TOF所有者；最迟P4|
|`projects/single_reflection_oa_tof_mass_analyzer/analysis/oatof_oaaccelerator_coupling.py`|`msplatform.components.single_reflection_oa_tof.oatof_oaaccelerator_coupling`|`projects/single_reflection_oa_tof_mass_analyzer/`：`verify_project.ps1`<br>`projects/single_reflection_oa_tof_mass_analyzer/analysis/`：`candidate_source_closure.py`、`validate_longitudinal_prediction.py`、`verify_axial_ideal_closure.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/config/experiments/`：`three_zone_solver_free_funnel_v1.json`、`three_zone_solver_free_funnel_v2.json`<br>`projects/single_reflection_oa_tof_mass_analyzer/workflows/formal_reference/`：`verify_geometry_derivation.py`|单反射TOF所有者；最迟P4|
|`projects/single_reflection_oa_tof_mass_analyzer/analysis/reflectron_dual_stage_solver.py`|`msplatform.components.single_reflection_oa_tof.reflectron_dual_stage_solver`|`projects/single_reflection_oa_tof_mass_analyzer/`：`verify_project.ps1`<br>`projects/single_reflection_oa_tof_mass_analyzer/analysis/`：`candidate_source_closure.py`、`oatof_oaaccelerator_coupling.py`、`validate_longitudinal_prediction.py`<br>`projects/single_reflection_oa_tof_mass_analyzer/config/experiments/`：`three_zone_solver_free_funnel_v1.json`、`three_zone_solver_free_funnel_v2.json`|单反射TOF所有者；最迟P4|

</details>

退出时沿唯一原实现与包资源入口更新调用、实际source hash和冻结闭包，不能以旧桥正文hash代表已迁算法，
也不能用当前安装填补旧快照缺件。Python alias保留共享globals／monkeypatch语义；PS保留仓库部署上下文、
Lua保留已冻结根的加载职责，均不是installed侧反向依赖作者树的许可。
公共执行／缓存／钟所有者负责显式Context、账本／事务与CLI回归；RF/OA/TOF所有者负责原几何、版本与数值保证；
integration所有者负责组合入口、source/clock、程序与冻结资源声明同步。历史协议reader只读边界继续保留。
性能与正式模型／科学资格、COMSOL后续迁移及P5新使用者验证不由桥清单关闭；阶段责任仍查[路线图](../docs/ROADMAP.md#科学核心与平台边界迁移)。

Ion-release and assembly compatibility aliases have retired. Active imports, CLI calls and new frozen source declarations use `msplatform.ion_release` and `msplatform.assembly.resolve_assembly` directly. Repository test modules remain under `common/ion_release`; the following P1/P2 inventory is historical, not an active import contract.

### P1／P2 迁移时的旧入口索引

下述为原迁移审查记录的有限调用索引，不作为P3当前消费者全集或运行证明；P3本轮路径与责任见上表。
原清单按Python AST直接导入（包括函数内导入）归类；路径均相对仓库根，
每行目录前缀与列出的文件名组合为完整路径，不表示整个目录或通配范围。排除测试、历史与测试辅助文件；
同一文件可能消费多座桥，数量不相加解释为独立消费者。各类责任由对应项目／集成／公共模块所有者承担。

`common.ion_release`（14个生产Python文件）：源策略、生成、物化与读回。

- `integrations/workflows/local_frontend/`：`prepare.py`。
- `integrations/workflows/single_reflection_flight/`：`prepare.py`。
- `projects/dual_cone_tandem_quadrupole_ion_interface/simion/`：`prepare.py`。
- `projects/dual_pressure_rectilinear_ion_processor/analysis/`：`functional.py`、`guide_interface.py`、`upstream_admission.py`。
- `projects/orthogonal_accelerator/analysis/`：`component_focus_workflow.py`。
- `projects/parallel_mirror_dual_stripe_mr_tof/analysis/`：`bunch_source_and_schedule.py`、`execution_binding.py`。
- `projects/rf_multipole_ion_optics/analysis/`：`generate_official_particle_table.py`、`generate_rf_multipole_family_mother_sample.py`、`paired_particle_source_bundle.py`。
- `projects/rf_multipole_ion_optics/workflows/mass_filter_reference/`：`run_finite_length.py`。

退出条件：上述调用者迁为直接规范API，并保留对应科学、失败与冻结回归后移除桥，最迟P4。

`common.integration.resolve_assembly`（8个生产Python文件）：完整布局编译、局部范围派生。

- `integrations/workflows/accelerator_interface/`：`prepare.py`。
- `integrations/workflows/local_frontend/`：`prepare.py`。
- `integrations/workflows/multipole_ip/`：`prepare.py`。
- `integrations/workflows/paired_accelerator_static_field/`：`prepare.py`。
- `integrations/workflows/single_reflection_flight/`：`prepare.py`。
- `projects/parallel_mirror_dual_stripe_mr_tof/analysis/`：`native_system_geometry.py`、`prepared_joint_trial.py`。

退出条件：上述调用者迁为直接规范API，并保留对应科学、失败与冻结回归后移除桥，最迟P4。

峰形与刚体变换旧桥均已退役；活动消费者直接调用`msplatform.analysis.peak_metrics`及
`msplatform.contracts.rigid_transform`，包括实际冻结源码与来源探针。算法、协议标识、坐标和变换算序不变。

`common.contracts.particle_physics`旧桥已退役；全部活动消费者、动态冻结清单和门禁路由直接使用
`msplatform.contracts.particle_physics`。物理常量、动能／速度公式、单位与失败语义不变。

`common.contracts.machine_contracts`旧桥已退役；ContractError、JSON/schema校验和普通摘要直接由
`msplatform.contracts.machine_contracts`提供。确实需要仓库上下文的消费者从
`common.paths.repository_root`导入`REPO_ROOT`，可安装科学核心不持有仓库根。

跨语言模块字符串还在以下具名入口出现，分别用于实际导入或冻结后的来源探针；不能仅凭AST清单删除桥：

- `projects/rf_multipole_ion_optics/workflows/interface_readiness/run_comsol.ps1`、`run_simion.ps1`：粒子物理与源模块。
- `projects/rf_multipole_ion_optics/workflows/same_solver_convergence/run_comparison.ps1`：粒子物理来源探针。
- `projects/rf_multipole_ion_optics/workflows/mass_filter_reference/compare_responses.ps1`、`run_comsol.ps1`、`run_simion.ps1`：峰形模块来源探针。
- `projects/rf_multipole_ion_optics/runtime/run_simion_finite_3d_transport.ps1`：内嵌Python的schema校验。
- `projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/generate_comsol_consistent_ions.ps1`：以文件路径调用 `common/ion_release/dotnet_gaussian_box_ion11.py`。

上述入口随各自科学调用和来源探针一起迁移，最迟P4；公共兼容测试保留行为保证后再退出旧桥导入。
IP与MR的有限桥冻结声明、单反射候选及重分析清单同时交付canonical源码和schema；
别名桥的动态 `__file__` 指向规范实现，不能代替显式旧入口声明。

从旧 0.1 安装迁移到 0.2 时，将 `common.ion_release.release`、
`common.integration.resolve_assembly`、`common.analysis.peak_metrics` 的导入分别改为上述规范 API；
函数参数和版本化科学格式保持，原 `method_id` 与 schema `$id` 不改写。0.2 wheel 不提供旧命名空间，
仓库中的兼容桥只服务尚未迁移的具名调用者；外部安装调用者需显式更新导入，不能依赖仓库桥。

### 粒子旧入口与退出范围

`common.analysis.particle_census`旧桥已退役；MR交接／实测源／分析、local及RF冻结消费者直接使用
`msplatform.analysis.particle_census`。原ID、权重、母群与未知终态分类不变。

`common.contracts.component_particle_state`旧桥已退役；IP、MR及integration的准备、交接、分析、
测试与旧CLI直接使用`msplatform.contracts.particle_state`，冻结输入和状态合同不变。

`common.contracts.particle_state`仍是RF事件表／ION11旧协议入口，规范所有者为RF
`analysis/rf_event_table_validation.py`及`simion/ion11_source_adapter.py`，不可错接中立状态。
当前未发现活动生产Python直调；RF/IP交接fixture及公共旧CLI行为测试仍消费它。
该RF旧协议入口只服务具名fixture、旧CLI及冻结库存，不拥有第二套算法。
RF的`runtime/run_simion_finite_3d_transport.ps1`及`runtime/run_finite_3d_transport.ps1`已显式冻结census安装实现；
integration的`runtime_dependencies.json`公共provider整包声明间接携带该旧协议入口，不等于直接算法调用。
最迟P4由各活动消费者所有者迁移上述调用和测试／CLI边界，同步清理旧源码声明及库存；
保留真实冻结来源／缺依赖拒绝及原CSV、ID、单位、共同钟、权重／母群、失败语义回归后移除旧桥。
历史冻结快照不追改；本清单不声称未知外部消费者不存在。

仓库当前未包含 LICENSE 文件或声明项目开源许可证；本次本机发行不新增许可证授权，也不上传 PyPI。
第三方依赖由声明与锁文件获取，未把商业求解器或其许可证、模型、原生载荷装入发行包。

V4 P1 的科学核心迁移已在声明的有限边界内验收；范围、失败与跳过限制及最终身份见
[P1 迁移验收记录](../docs/history/20261103__phase01-scientific-core-migration.md)。该结论不授予原生求解器或科学资格，
不关闭后续平台迁移；具名兼容桥仍按[路线图](../docs/ROADMAP.md#科学核心与平台边界迁移)退出。
安装隔离验收由 `common/contracts/test_installed_scientific_core.py` 执行真实 wheel、sdist 重建和仓库外消费。
P2的0.3.0工作树候选已完成该真实方法（106.321秒，无skip）：独立builder使用声明的
setuptools65.5.0/wheel0.38.4与已核对离线依赖；原wheel和sdist重建wheel分别普通安装到树外consumer。
两轮实际模块来源均为consumer的site-packages，44个schema及378处引用本地闭合；
真实RF/OA组件3、plan5、binding2、母群、中立状态及严格峰入口均有实际计算断言。
这是该候选的软件安装证据；后继已提交，当前跨项目验收状态统一查[路线图](../docs/ROADMAP.md#科学核心与平台边界迁移)，
不以安装方法通过代替整机原生与工程出口。
运行、安装及冻结依赖规则由[操作指南](../docs/OPERATIONS.md#工具链与执行入口)维护。

## 门禁编排

公开门禁先解析本次 Python，内部阶段先校验冻结请求，再用该解释器加载主机资源上下文；
调用结束恢复原 `SIMULATION_PYTHON_EXE`。旧环境值不能覆盖显式解释器或使只读规划提前失败。

公共 workflow 的纯软件 PowerShell 夹具统一使用已有 ACK／Job 归属入口：启动脚本取得归属后才执行，
90 秒测试硬超时后清理本夹具子树并有限排空输出，保留原超时、原始输出与次要诊断错误。
这关闭了仅结束 PowerShell、遗留子 Python 持有管道而无限等待的默认分支；不改变商业求解器的告警与退出策略。

容量压力回归保留真实解释器与路径解析，仅在测试容量命令边界注入故障；使用私有主机账本和受控观测，不重复真实主机故障矩阵。收尾恢复分别核对入场预算收据与最终零承诺及释放，不能将已更新的 lease 当作入场快照。对应两项旧夹具失败保留于 CI 41142387491（373.131 秒）和 41142659947（302.116 秒）；定向修复通过不代替新提交的整轮 CI。

公共 COMSOL mesh／Size helper 家族的 Changed 路由按真实调用链选择：RF 两个 solver 共用同一机制，
其准备／冻结接线只运行 mesh-report 与 frozen-MATLAB-closure 两模块；SFI 仍消费 Size helper，
integration 继续由既有冻结库存选择。typed reader 的当前 SFI legacy 调用不进入显式 hmin 读回分支。
既有公共 MATLAB `ComsolMeshSizeTest` 的16项行为证据继续负责默认／显式 Size 读写；相关 helper 变化
仍须相称工具验收，不新设每次运行 smoke。数值合同变化的原完整映射、Owner／Repository及未知新 helper 的保守范围不变。
在6ae3507b软件树重放同两个 helper 改动，规划15→10阶段、1756→1225个 unittest case（只加载计数，未执行全套）；
无同轮重复 case，节省来自去掉非消费者宽路由。重放688的全部36路径仅16→15阶段、2033→1986 case，
其他实际RF生产变化仍触发宽回归；该规划差异不证明历史1333.416秒 CI 或宽范围反馈预算已达标。

四极 COMSOL 数值编译器的 Changed 依赖按实际消费者选择 interface 与 mass-filter 合同测试；其他 runtime 和未知重命名仍保守扩大。普通文档不单独触发声明了测试选择的 owner。2026-10-31 对应提交修复前 CI 实际运行 1109 项、公开门禁墙钟 803.073 秒并失败；精确四路径规划收窄为两个消费者模块，尚不代表新 CI 已通过或性能预算已达标。

`common/gate_catalog.json`是改动路径路由、依赖等级、阶段前置关系和Repository成员身份的唯一机器目录；项目或
integration新增公开门禁时必须注册，目录与文件系统不一致即失败。集成route通过
`runtime_dependencies_path`引用已有运行依赖库存；公共catalog读取器将其`source_repo_path`展开为精确匹配，
新增依赖不再手抄第二份路由表。缺失库存、未知版本／身份或缺失来源文件在规划时失败。
专用`oatof_*`和`multipole_*` schema由catalog中的精确owner匹配声明；读取器据此从公共合同目录的
保守fallback中排除这些已知文件，保留实际runtime消费者与统一schema元校验。
例如`oatof_three_zone_stage_report`的真实owner是单反射项目；它的改动不再触发无关RF、电子枪或EI门禁。
未登记的新schema、公共validator、生命周期和注册语义仍沿保守路由扩大，不按文件名前缀猜测新归属。
OA提供者的普通tests变更留在OA owner；跨项目生产目录依赖不包含该测试子树。
集成夹具实际导入的`test_bare_three_zone_component.py`及其测试包初始化仍精确触发集成回归；
OA生产代码与runtime库存声明的真实消费者依赖保持原路由。
IP普通Python测试留在IP owner；集成实际导入的`test_component_exit.py`与`test_functional.py`仍精确触发集成回归。
IP生产／未知路径、测试support与包初始化保持保守集成依赖；独立测试变更不再令集成两模块扩大为完整owner。
需要补充或精确选择测试的owner在同一目录声明`test_selection`。明确的新增／修改测试模块进入实际
执行集合；生产与测试混合改动保留原owner门禁。删除、重命名旧路径、共享fixture、包初始化及未知
测试目录变化扩大到所属owner发现，并报告选择原因。是否仅为测试变更按该owner实际路由影响计算；
其他owner测试和文档不迫使全量发现，SIMION公共测试也使用同一选择机制。
单反射项目的独立 Python 测试改动也由该目录选择；源码、共享夹具、删除或未知测试范围仍保留原项目完整检查。
Git差异保留重命名两端，不能只看到新路径。
模块集合由实际owner选择；原expected-values、gate、CLOC、dependency及schema元校验触发关系
归入公共合同owner的`test_selection.dependencies`，不再维护covered专属路由和去重分支。
短分析模块逻辑上独立选择，按stdlib／locked分别合为unittest执行批次，逐测试计时及失败保持。
Core的成功不能替代未运行测试的证据。
当前Repository规划48阶段：4个全局职责、33条逻辑route去掉9条分析独立进程、1个
integration纯Ruff preflight和1个公共合同父进程，再加2个分析批次、16个MR／单反射／integration／RF四极测试分片
及4个公共合同分片。RF原长阶段拆成前置与四个模块片，使此前43阶段增加4；任务数变化不是提速证据。
逻辑route由37减为33是四条covered归回公共合同选择，不能再算一次任务减少。
九个短分析模块按依赖分为stdlib四模块、locked五模块，保留标准库范围无需安装科学环境的能力，
因此是九进程收敛为二，而非混装成一个。该数量是当前选择结果，不是未来配额或实际native进程计数。

公共合同沿现有分片机制按模块分为四组，覆盖集合保持完整且各模块恰执行一次。
真实分片回归按catalog配置验证数量及完整集合；并发故障小夹具自行声明片数，
不让生产排程调整改变其失败传播与健康任务排空场景。
Owner别名回归核对实际unittest模块与catalog所属发现集合（包括重复数量），
不以是否存在未分片的阶段名称判断完整覆盖。父级选择的模块直接传给分片，子进程消费已编译请求；
仅改指定测试时不展开完整owner，部分root的扩展不冒充完整scope。
当前权重统一取自21b的同轮Owner2实测55模块；原owner37方法按源／执行路径15项、完成／恢复22项
分别归入test_run_artifact_workflow_sources与test_run_artifact_workflow，完整集合变为56模块。
共享夹具支持仅在test_support/run_artifact_workflow维护，实际CLI消费者不导入带测试方法的TestCase。
两组实测测试工作量177.702262／227.086357秒只用于排队，不缓存PASS或跳过检查。
四分片278.167秒是同轮成本重排预测；另有25.195秒实测前置及准入／收尾，不能据此宣称复杂Owner≤5分钟。
同机16逻辑核、Python3.11.0／PowerShell7.6.9、固定4worker的979测试配对，完整Owner墙钟511.484→402.224秒。
原37方法累计耗时反增5.59%，收益来自局部并行与长尾改善；这是单次配对，不能外推CI或Repository达标。
MR、集成、单反射及RF四极的模块权重取自Repository CI 41260704508的实际逐测试计时，分别覆盖91、60、74、40模块，
按owner及实际文件身份对齐，保留原完整集合和默认新模块权重。这些值只用于排队，不缓存PASS或跳过检查。
RF四极复用已有分片参数：前置执行原Static的合同与科学软件检查一次，子片仅消费明确选定模块；
原ChangedTestModules仍追加，和SelectedTestModules替换式参数混用会拒绝。分片消费父计划已解析的owner集合，
不会按RF总tests目录重复domain／六极／八极的已注册职责；未知测试根仍沿原owner保守发现。
RF的official／interface现指向同一组四个authority路径，Freshness只检查该发布一次；
interface正式workflow、mass-filter及各结构变体的独立检查保留，真实发布字节漂移仍拒绝。
RF `verify_project.ps1` 变化还选择真实跨求解器门禁消费者测试，保留 Core 并追加该模块；
回归检查实际职责与输入参数、所选测试的非零传播，不锁已退役的重复调用次数。
按同次实测模块成本重放旧／新最长片：MR523.404→432.484秒、集成530.083→467.003秒、
单反射430.631→430.258秒、RF四极716.775→179.213秒；这些是排程预测，未计前置和启动成本，不是整轮实测收益。
四片不增加并发：两个worker下RF原模块工作量的理想下界仍约358.387秒，不能将179秒称为完整RF owner耗时。
单反射仍受candidate完整模块约430秒限制。并发上限与资源准入不变，a03原完整软件4256.913秒未达900秒目标的事实保留。
Changed已选的Python模块或声明替换式参数的PowerShell模块全部具有实测权重、累计达到300秒且有效并发至少为2时，
若现有分片的预计调度时间更短，可直接对该模块集合分片；不扩大为完整owner或重置为Repository命令。
300秒取自复杂软件反馈参考，只决定排程，不是超时或验收放宽。短／未知成本、单worker及继承资源仍合批；
子片保留实际依赖环境、导入根、前置阶段和原失败策略，实际墙钟另行测量。
纯Python部分集合分片后不再执行包含同一集合的父测试命令；原owner的PowerShell前置声明不适用于该已转换命令，仍需的PowerShell前置照常保留。
共享`msplatform.workflows.single_reflection_flight.field_plan`按实际保留的单反射及依赖消费者选择集成模块，
未知、删除或重命名来源仍保守扩大，Owner／Repository保持完整覆盖。
集成入口使用现有`SelectedTestModules`替换式参数消费选定集合；有同轮中央Ruff时依赖其PASS后分片，
没有时保留单批与入口自身的一次Ruff，不把subset追加成完整发现。模块权重按上述Repository实测更新，
选中集合减少与预计排程收益不代表已经实测达到反馈预算。
PowerShell subset的串行fallback夹具保留五个决策场景，使用同一worker PID和事件顺序核对串行执行；
只在并行／失败排空场景保留握手所需等待，不在串行场景逐测试固定等待。

显式Python测试命令保留目录声明的发现根作为临时导入路径，并在返回时恢复调用者环境，
使既有目录级导入与未知子目录的模块枚举同时成立。
软件验证父入口只解析一次catalog、实际模块与分片；子阶段通过同轮`InternalRequestPath`消费已解析命令，
不重新规划所有route或枚举全部测试。前置仍由父级依赖准入保护，子阶段仍调用原计时、GATE资源和失败传播入口。
该请求只运输执行计划，不保存PASS，也不提供跨提交缓存；Ruff和改动范围标准检查的长参数列表由同一调用器临时文件传递并清理。
`common/verify.ps1 -Scope Changed|Owner|Repository`是唯一软件验证入口；Owner范围必须提供`-Owner`。
普通命令自动规划、执行并汇总，`-PlanOnly`用于可选预览。Changed的`-FullScope`保留原Core／Static
选择，不等于Repository。原两个驱动已移除，活动消费者统一使用此入口。
`.github/workflows/lightweight-gate.yml`在push运行Changed，手动`workflow_dispatch`默认运行Repository。
Changed和Repository按实际选择范围分别排队，同范围仍串行且不取消运行中的任务。
两个job使用[独立GitHub托管VM](https://docs.github.com/en/actions/how-tos/manage-runners/github-hosted-runners/use-github-hosted-runners)，
其主机库、产物和临时目录互不共享；分组沿[官方concurrency机制](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)，
不改变每个host的并发预算或平台限额，也不保证立即取得runner。
手动指定`comparison_base`可在所选代码版本上运行从该提交到当前提交的Changed范围，例如
`gh workflow run lightweight-gate.yml --ref <任务分支> -f comparison_base=<40位提交SHA>`。
显式比较基线必须可取得、非零且差异非空；不满足时在规划前拒绝，不静默改为另一范围。
比较性能时仍须核对实际覆盖与环境，不能将不同catalog选择的墙钟直接当作同范围提速。
Repository保留[GitHub平台job上限](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idtimeout-minutes)，
不再另设60分钟强制取消；反馈性能目标不变，超目标必须继续报告和处理。原 CI 41222211656
在60分钟边界附近取消，尾部仍在执行测试；该轮有真实失败，不能视为完整Repository验收。
Changed可能包含完整integration行为回归；CI预算包括环境安装与整轮验证，不能按单个Core检查估算。
两个CI job在门禁前将后续步骤的`TEMP/TMP`设为[官方`RUNNER_TEMP`](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)的规范绝对路径，
通过[`GITHUB_ENV`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#setting-an-environment-variable)传递，避免Windows用户目录短别名与长路径在测试夹具中混用。

`-PlanOnly`使用同一目录先给出`stdlib`或`locked`依赖等级；GitHub对只需标准库的文档和门禁
合同范围跳过完整科学Python环境安装，任何未明确分类、项目注册表、Python lint、项目/集成、依赖声明或
FullScope均失败关闭为`locked`。本机与CI的普通软件门禁并发默认均为4，可用
`-MaxConcurrency 1..32`显式覆盖，或用`-MaxConcurrency auto`（兼容0）选择`min(8, logical_processors)`。
这是门禁组内的并发上限；实际内存、I/O、独占资源和前置依赖仍独立限制准入。普通非重型GATE的CPU
压力和声明核数只作观测，不以95%阈值或累计核数阻挡；SIMION、COMSOL和重型GATE保持原CPU限制。并行阶段即时报告进程启动与完成，启动行的`LOG_PATH`
指向执行中逐行刷新、可直接读取的阶段日志；完成后仍按稳定顺序回放完整日志，不在内存缓存整个阶段。
unittest 测试完成时报告耗时，首个异常发生时增量回显 traceback；其他已启动阶段自然收尾。
For a selected test subset, the existing owner partitioner keeps known `measured_seconds`
and uses its declared `default_seconds` for modules without a measurement. The fallback
is a scheduling estimate, not measured runtime; one unknown cost does not disable all
partitions. The existing cost/benefit threshold, exact module coverage, prerequisites,
resource limits and inherited-worker cap remain in force. This does not establish the
full-suite performance target.

`common.gate_unittest`按实际结果回调输出逐实体outcome与独立invocation起止收据；
源码相对路径及类/方法组成`test_key`，stage、随机invocation和源码SHA分别作为执行与版本元数据，
不以短模块ID去重。fixture/loader、subtest、skip原因和未完成分别保留；record_count含子实体，
不能当作unittest的tests_run。旧duration信号继续可读，但没有outcome的历史记录保持unknown。
并行组在日志清理前解析，单阶段inline沿同一解析器汇总；不完整收据或无效信号作为证据错误暴露，
不覆盖已有执行失败。显式`--outcomes-path`可另发布该次调用的独立JSON，子进程不继承该路径。
`python -m common.gate_outcome_report report --summary <摘要> --output <新报告>`生成只读对账输入，
`compare --left <报告> --right <报告> --output <新对账>`保留重复尝试，分别报告outcome、
版本/skip理由、单端执行和stage未执行差异；不调度测试，也不把旧unknown补成PASS。
CI两种范围上传独立的`*_gate_test_outcomes.json`，与原摘要、精确source/workflow身份及环境绑定。
摘要在阶段完成时保存已观测的逐测试耗时和结果；非unittest阶段不凭空产生测试结果。
成功组清理临时目录；失败组保留阶段日志、请求JSON和`group_failure.log`，输出
`GATE_DIAGNOSTICS=RETAINED`及精确清理命令。串行fallback也写入同一阶段日志，不能只有控制台错误。
复核完成后沿[操作指南](../docs/OPERATIONS.md#软件验证与科学证据)清理，不按年龄自动删除失败证据。
Group cleanup follows natural child exit and outcome publication. A cleanup
failure is secondary to an existing group/finalization error; otherwise it
fails the gate after log-retention metadata is reconciled, including partial
log deletion. The secondary diagnostic preserves the primary failure even when
caller warnings are errors. Summary outcomes and the original gate exit remain
distinct from raw-log archival: terminal-only
collection cannot recover normally deleted logs, and an archival failure must
not overwrite the original execution result.
改动选择器回归中的八个mini场景在同一PowerShell host内调用真实PlanOnly与InternalStage委托，
逐例检查RED/GREEN；MR和RF两个真实owner仍各自通过独立CLI核对非零退出传播。
保留原Core的owner遇到源码与测试混合改动时，仍合并明确修改的测试模块并去重；
实际源码依赖沿catalog既有映射补入，不让未映射源码消去明确测试。
此规则仅适用于原命令的模块追加参数，不将替换式`SelectedTestModules`的未知范围缩成子集。
相同十场景的PowerShell启动数由20降至5，不减少selector或测试执行，不新增生产缓存。
收尾完整故障矩阵由公共owner覆盖；集成保留prepared retention／unknown、OA publication及
paired static retention／pulse publication五个原CLI代表场景，核对真实Result参数、不重算、未知拒绝与幂等终态。
一次准备host、五次恢复及四次幂等重入共十个PowerShell进程；场景变更不作为同范围提速证据。
唯一入口输出`GATE_SUMMARY_PATH`：默认是系统临时目录中的独立小JSON，可用`-SummaryPath`指定
不存在的目标文件。摘要保留选中原因、实际命令、依赖、环境、阶段状态、耗时、退出码和日志保留情况，
成功清理详细日志后仍保留摘要。计划先落盘，阶段完成即更新；可捕获的失败或中断按实际状态收尾，
硬杀或断电后的`PENDING/RUNNING`只表示未完成，不能解释为通过。日志路径标为未保留时不可用。

On Windows, summary publication keeps one complete candidate and retries the same
atomic replacement only for native errors 5, 32 and 33. The project retry policy uses
50/100/200/400 ms delays, at most five attempts, and a 750 ms deadline for starting
another attempt. It does not preempt an OS call. Persistent denial still fails;
diagnostics preserve the first error and exact paths, attempts and HResult, with
temporary-cleanup errors attached separately. ACLs and atomicity are unchanged.
This is a bounded project workaround, not proof of the actor behind an old failure.

During live acceptance, use stdout and the process handle for progress. A Windows
reader can prevent replacement while it holds the summary open. If a JSON snapshot
is needed, read and close the file before parsing: assign
`$text = [IO.File]::ReadAllText($summaryPath)`, then parse `$text | ConvertFrom-Json`.
Do not keep a live `Get-Content` pipeline open through downstream parsing.

CI使用[官方artifact action](https://github.com/actions/upload-artifact)在`always()`步骤上传摘要和本次保留的门禁诊断。
两个CI公开调用步骤用现有Python环境的单调时钟包围实际`pwsh`根命令，继承stdout／stderr以保持首错即时可见；
另上传`*_gate_command_timing.json`记录命令、环境、退出码、scope和完整命令墙钟，保留原summary文件及其计时口径。
安装、队列及此前独立scope规划不计入该公开命令墙钟。
摘要是观测记录，不是跳过后续验证或跨改动复用PASS的凭证。
文档检查保持独占；随后短检查先进入同一执行器，其余阶段按catalog顺序稳定排队。
只有`requires_stages`全部PASS的阶段才可启动，失败前置的后继即时标为`BLOCKED`；
前置缺失、未选择或无法取得ready阶段也明确阻塞，不挂起等待不存在的工作。
Changed／Owner首个失败后停止派发待队阶段，已启动阶段自然收尾；Repository在环境及目录初始化成功后继续独立检查，
包括文档检查失败之后的独立诊断，最后汇总失败。无日志与sidecar的既有串行fallback先取得实际结果，
才允许依赖它的阶段启动。资源许可、嵌套预算与进程数上限保持原公共入口。
`-ResourceWaitTimeoutSeconds 1800`默认给每次普通GATE准入30分钟有限等待，可显式设置1..86400秒。
计时包含准入采样、事务竞争和资源队列，不含Action执行；阶段切换重新开始准入计时。超时失败关闭，
记录原因及实际等待，仅取消自身申请；释放仍保护活子进程，不杀健康owner、不强行准入。遥测CIM调用按
剩余等待设置超时，清理另有30秒窗口；清理失败保留错误和账本，不假报已释放。继承父token不释放父申请，
嵌套组仍串行。旧冻结policy缺此字段时保留原无隐式deadline边界；新公开门禁始终传有限正数。
计划与摘要的`resource_context`记录请求/解析worker、逻辑核数和等待上限，消费计划不得覆写该上下文。
`queue_seconds`从本执行组开始到派发，含组预热、依赖及并发槽等待；`resource_wait_seconds`单独测量
host许可等待，`execution_seconds`只测Action，`cleanup_seconds`测许可释放与环境恢复。
`launch_seconds`只测`Start-Process`调用，不能解释为全部子PowerShell初始化；`process_elapsed_seconds`
从该调用开始到父进程确认退出，包含轮询观察延迟。原`elapsed_seconds`仍是stage wrapper总计时，
整轮摘要从建立摘要到收尾计时，均不是整个根PowerShell进程墙钟；这些范围不能相加推算另一范围。
公开命令的端到端墙钟由调用者使用单调时钟，从启动公开命令前测至根进程实际退出，并另记命令、退出码、
环境和实际范围；例如现有Python调用环境的`time.perf_counter()`包围`subprocess.run(...)`。
原summary／stage计时保持原义，用于区分规划、准入、测试和收尾，不改名为端到端时间。
未实际观测的阶段字段为null，测试数量与skip不从退出码猜测。
Repository的MR静态测试与instrument assembly集成测试分别按原owner完整模块集合分为四组，随后每组独立申请
既有GATE资源预算；任一组失败仍使Repository失败。目录中的权重取自2026-10-29同机L2逐测试耗时，
未测模块使用保守调度估计，权重仅决定分组次序，不决定覆盖或通过。MR保留一次PS／Lua前置，
纯Ruff的integration前置任务已撤销；中央唯一Ruff承担实际选中范围，项目委派仅表示父级汇总职责，
不冒充项目lint已PASS。中央注册表PASS供MR前置复用，RF Freshness承担一次整树PS解析，变体各验科学合同。
分片结果不等于完整owner门禁；项目直接入口默认完成其全部必要检查。
集成分片权重来自同机完整L2 r3逐测试耗时按模块聚合；所有已发现模块恰好执行一次，权重仅用于调度。
Changed选择的命令与同一catalog中的完整owner命令语义相同时，复用上述分片及实际必要前置；
只改测试模块仍只运行所需模块，普通MR `Core`不会扩大为`Static`。覆盖去重按实际选中分片的模块并集判定，
任一必要preflight或分片失败仍使所选范围失败。原权重样本中的单反射执行模块约688秒；
当前按场、飞行、容量、发现和准备拆成五个真实测试模块，共用仅含helper的测试fixture，沿现有分片器调度。
模块权重来自拆分前后可比方法的历史测量，仅作调度提示；当前Goal测试的联合回归仍另行报告。
隔离候选的四worker实测公开墙钟268.209秒、五阶段通过；一次性测量harness遗漏顶层摘要收尾，
其原摘要仍为RUNNING，独立退出码、单调计时和资源释放日志保留，不将该摘要当作完整门禁通过证据。
这不证明完整owner或Repository已达预算；显式仅改测试文件的选择仍按现有单owner命令串行。
2026-10-30同机宽L1为24/24阶段通过、摘要区间1337.500秒；热点为common contracts 1301.851秒及集成分片01 1113.187秒。
完整软件L2主体摘要区间1578.351秒，44/45阶段通过；唯一RF阶段修正后以正式quadrupole Static完整复验298.011秒通过，
原失败整轮摘要仍为FAIL。此前同机完整L2 r3为2064.248秒；本轮增加恢复用例，不能当作同冻结工作量的加速倍数。
宽L1的10分钟、软件L2首轮15分钟目标均未达到；普通单owner L1未独立计时，不宣称已达1–3分钟。
历史耗时测量见[门禁审计](../docs/history/20260802__gate-system-audit.md)；
Repository用于显式全仓软件验证，纯文档提交不默认运行Repository。
三个scope共用命令调用器直接绑定函数脚本块；仅冻结每项路由参数，不对调用器本身建立动态闭包，
避免其捕获旧的`LASTEXITCODE`而把失败报告为成功。公共回归实际执行成功及非零退出探针。
公共预算阶段执行期间将控制台输出编码设为UTF-8，退出时恢复原编码，嵌套阶段同样遵守；
避免隐藏Windows宿主的CP936经Python传给子PowerShell，导致中文错误日志解码失败并掩盖原始错误。

改动范围Ruff检查沿锁定版本的[官方参数文件](https://docs.astral.sh/ruff/configuration/#argfile-support)
传递原文件集合，保持逐文件范围及非零退出语义；阶段结束时清理临时参数文件。
这样避免大量绝对路径超过[Windows CreateProcessW的32,767字符上限](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)，
不另建分批启动器，也不以缩短路径或修改UTF-8日志语义规避进程限制。

最新路径主题 `1eb7fedd` 的 [CI](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41066360221) 保留为 FAIL：
cooled 路径夹具在较短 CI TEMP 下未达到原生长度边界，却要求 alias；六个恢复负例在目标故障前触发生产磁盘余量。
修正仅加深测试路径，并让恢复夹具实际消费自己的 64 MiB／零 minimum-free 策略及代码副本；生产策略不变。
相对该提交的隔离副本中，两测试方法（含原六个恢复场景）通过，测试区间 79.280 秒；这不是整轮 CI 通过。

## 主机资源实现

运行前磁盘准入沿`Enter-ArtifactWorkflowCapacitySession`与现有容量台账执行；旧`Test-RepositoryDiskCapacity`及其专属测试已退役，
当前最低余量、承诺、来源保护和失败关闭测试保持。

粒子拆批与默认并发遵循[开发标准](../docs/DEVELOPMENT_STANDARDS.md#独立粒子与耦合求解的调度)，
随机重复运行的验收遵循[验证方法](../docs/science/VALIDATION_METHODS.md#随机碰撞与重复运行)。
PA等昂贵阶段复用及中断恢复遵循[统一复用与恢复规则](../docs/DEVELOPMENT_STANDARDS.md#昂贵阶段复用与中断恢复)。

本机门禁与SIMION/COMSOL运行通过[`host_execution_lease.ps1`](host_execution_lease.ps1)
进入同一[`主机调度器`](host_resource_scheduler.py)。当前默认账本位于工作区同级产物根的
`artifacts/common/host_resources.sqlite3`；同一父目录中的工作树共用该默认值，跨父目录不能假定自动共用。
准入和status按显式绝对路径、`MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH`、默认路径的顺序选择；
不同工作树必须显式部署到同一绝对账本，不能各建一份而重复分配资源。环境路径只用于受控部署或隔离测试，
生产调用不得用它绕过正在运行的申请。切换部署路径前必须等待原账本的owner、后代和等待者全部结束，
不能复制活跃SQLite或让两个账本并行准入。资源配置、已分类阶段及测量依据只维护在
[`host_resource_policy.json`](../src/msplatform/execution/resources/host_resource_policy.json)，不在项目脚本复制容量阈值。

CIM不可用时，原生观测每轮只用一次
[Toolhelp进程快照](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot)
建立父PID表，循环查表，不跨事务缓存。
[PROCESSENTRY32W](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/ns-tlhelp32-processentry32w)
只有PID／父PID，不提供创建身份；创建时间继续由.NET或
[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)
读取。抓表后才创建的同PID身份不能绑定旧父关系，进入既有unknown处理；缺少父项仍按原parent=0语义。
这是基于Windows官方API的仓库实现，资料核验日期2026-10-25；不把进程名当身份或console豁免依据。

`release`遇到其它reservation的创建身份未知时，只允许核对并减少自己的已知reservation：
调用者须是当前仍可观测的原owner；自己的未知work进程仍须已有同步等待的精确创建身份完成证据。
其它reservation的身份、后代、预算和承诺原样保留，不执行foreign refresh，也不准入任何新grant；
自己的活work子进程仍保留原阶段资源。request、poll、status、transition、register、inherit仍按完整观测失败关闭。
这修复无关release的耦合，不代表已证明或修复所有退出采样竞态；缺失创建时间仍不等于进程已停止。

阶段通过`Enter-HostResourceStage`申请CPU核数、内存字节、批量I/O槽位及具名独占资源，取得许可后
才能启动工作；相同独占资源名不能同时授予两个活动阶段。预算是准入声明，不是操作系统强制限额，
也不修改科学参数或求解器精度。中央策略只区分重任务与轻任务：只有阶段名单列出的PA refine、离子飞行、求解及理论计算
占用唯一重任务许可，重任务之间串行。所有未列入名单的阶段默认轻任务，包括`SIMION/COMSOL`角色，采用中央声明
额度，不要求先完成峰值测量；声明额度不代表测得的占用上界，已有测量的检查可使用较小额度。
PA输入准备、GEM转PA、缓存物化与纯IOB组装默认按轻任务准入，不因属于PA工作流而整段判重；
原生refine以及已知内部调用refine的Lua操作须在重阶段执行，结束后可回到轻准备阶段。
重任务身份与I/O标记相互独立：SIMION飞行仍持有唯一重任务许可；会批量读写的阶段以非零`io_slots`
标记启用目标卷实时压力检查。当前没有可复现基准支持固定并发流数，因此主机`io_slots=0`明确表示
telemetry-only，不执行静态槽位求和，也不会因猜测的槽数误报`io_budget_full`；若将来用吞吐基准启用正数
容量，它才表示所有活动阶段的并发I/O权重上限。内存、重任务互斥和实时I/O压力始终独立生效；
CPU准入限制适用于商业角色与重型GATE，普通软件GATE仍记录真实CPU观测。
轻任务可与重任务或其他轻任务并行；商业轻任务仍核对实际CPU加预计核占用及累计核数，
所有角色均核对可用内存及I/O压力。观测不完整时停止新增准入，不能把缺少观测解释为资源空闲。
重任务分类只在中央策略维护，不在项目复制规则。
排队公平性按重、轻同类约束；等待重任务不会仅因轻任务多次通过而阻挡后续轻任务。
普通GATE仅豁免由CPU压力、CPU余量或累计核数不足形成的同类队列屏障；内存、I/O、独占资源等
原因形成的屏障仍生效，商业角色的原公平性不变。

软件验证按实际阶段申请预算，已持有父token的嵌套组在父预算内串行，不能重复申请或增加嵌套并发。

门禁目录的 `resource_role` / `resource_stage` 将同一公开检查的资源职责传到保存计划、inline 与 worker；
缺字段仍为 `GATE` / 原阶段名，显式空值或未知角色拒绝。当前具名原生职责只有
`simion_dirichlet_native`：原 Dirichlet 模块的六项微型原生测试单独申请 `SIMION/pa_refine`，
在 Owner `common/simion`、Repository 与相关 Changed 范围恰好执行一次；普通 SIMION 软件组排除该模块。
此分离不为相邻 opt-in 原生测试设置授权环境变量，不改变普通 GATE 并发及嵌套规则。
微型测试的原 120 秒 deadline、科学输入与 Refine 默认保持；失败保留临时 builder 的逐字节还原证明、
阶段 checkpoint、受限原始输出及小输入。诊断修复与正确重型准入不等于已裁决历史偶发挂起的根因。
目录回归同时核对真实 host bridge 改动触发该原生职责；隔离目录夹具携带角色校验所需的公共依赖，
仍实际验证错误发现范围及父级 preflight 的拒绝，不用缺依赖异常代替这些断言。

COMSOL公共入口已支持准备、求解和后处理边界，具体调用见
[COMSOL主机资源阶段](comsol/README.md#主机资源阶段)。本次服务器完全退出后的`COMSOL/postprocess`
显式使用普通轻任务策略；`COMSOL/solver`列为重任务，准备和未分类阶段默认轻任务。入口调用
`Enter-HostExecutionLease -Role <角色> -Stage <阶段>`按中央名单解析；省略`Stage`时为`unclassified`轻任务。
`unknown_peak`只表示峰值未知，不授予重任务许可。自定义预算不能覆盖中央阶段分类。
此入口不再获取旧mutex；内层阶段继承
父申请不会自动缩减其全程预算。当前接入不表示所有项目或内部求解阶段都已经完成资源细分。

Python重阶段通过[`host_resource_python.py`](host_resource_python.py)现有request/result通道执行；
`run_heavy_function`的成功值仍使用原Path/tuple编码，失败仍向父调用者抛`RuntimeError`，同时保留worker的
异常类型、消息、notes及其明确提供的`observed_process_exit_confirmed`/`observed_process_returncode`。
缺失、损坏的结果或成功结果后的bridge非零退出均标为退出未确认，不能据此封存科学输出。
父进程通信异常不会主动杀死健康的PowerShell owner；它关闭请求输入、排空输出并等待同一进程句柄自然退出，
再抛原异常。二次中断或等待故障保留未确认状态及必要IPC目录；清理次错只附加说明，不覆盖主错。
`bridge_process_exit_confirmed`只证明直接bridge根进程；worker携带的观测状态也只覆盖它原来声明的进程，
均不替代既有主机owner对后代退出的判据，不构成求解成功或物理资格。尚未确认停止的写入者不得进入retention或终态封存。
`Exit-HostResourceStage -PassThru`原样返回本次释放事务；默认控制台输出与环境恢复不变，继承调用不返回
释放结果。bridge在同一个call结果中附加`host_release`，保留`inherited`、token、原事务`result`及释放
`error`；只有非继承、无释放错误且同token的`released`响应才确认owner释放，仍保留的预约不能报告成功。
`run_heavy_function(..., completion_receipt=空字典)`将本次bridge根退出和host释放事实写入调用者提供的
独立容器，正常返回值类型不变；失败异常也带`host_release`与`host_release_confirmed`，释放次错不替换worker主错。
继承的直接调用只报告继承身份，没有owner释放证明；每次调用须使用新的空容器，避免复用旧证明。
host释放不能覆盖worker明确报告的原生退出未知，也不替代局部PA guard所需的实际写入进程退出证据。
CLI reentry在原前台输出流报告释放结果，释放未确认时非零退出，不另建结果文件。

受控Python helper使用`common.host_resource_python.await_managed_process_start()`作为首个操作，随后才能
导入项目或启动native工作。公共`Invoke-RepositoryManagedPythonProcess`以同一stdio完成nonce、实际worker
PID与创建身份的READY／ACK握手；Python调用方使用`run_managed_python_process`沿既有内部bridge访问它。
两入口均不申请、继承核验或释放资源许可，不设置heavy reentry；科学入口仍负责既有准入。
父端确认worker属于本次launcher后持有其实际进程句柄，等待worker退出并将两条输出流按原始字节排空到日志。
因此`.venv`启动器退出、或worker先写completion后继续写stderr，都不能使日志提前封存。
返回的`repository_managed_python_completion`分别报告ownership、worker／launcher退出与两流drain；Python异常的
`managed_python_completion`或PowerShell异常Data中的同名值保留失败时已确认的事实。
`ack_attempted`在发送ACK之前置true；发送错误可能发生在worker已收到ACK之后，不能解释为工作从未启动。
此收据只证明实际worker与launcher退出及日志排空，不声明任意后代退出。初始归属未确认或错误ACK不得
启动受控工作。项目另核对实际native根的原生终态；native未知不得发布或执行retention，保留run及容量保护，
不能声称PowerShell退出后其FileShare句柄仍保持。
当前受控SIMION脚本使用同进程的`simion.command()`／PA API，没有主动外部fork；
依据[官方CLI说明](https://simion.com/info/command_line_interface.html)，由直接Popen根writer的完成事实判定本地PA写入结束。
该合同不覆盖任意程序派生独立写入者，适用的host释放判据仍由原调度器负责。
创建时间沿用现host接口的.NET UTC ticks（D19），通过Windows
[`GetCurrentProcess`](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getcurrentprocess)和
[`GetProcessTimes`](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)
读取，并按[`FromFileTimeUtc`](https://learn.microsoft.com/en-us/dotnet/api/system.datetime.fromfiletimeutc)相同epoch转换，
不经浮点Unix时间舍入。官方API核验于2026-10-28；这是基于官方API的受控worker归属协议，不是任意进程树捕获保证。

SIMION公共执行器在原生refine/fly启动或进入内部飞行批次调度前通过`Assert-HostResourceHeavyStage`核验同一父许可；
已知内部调用refine的Lua由调用入口设置重阶段，不能仅按Lua命令名判断其开销。
内部worker仍由既有SIMION规划器按实时CPU和内存准入，不逐worker申请主机许可，也不传递第二套动态额度文件。
重任务许可不代表包下所有空闲资源；轻任务及其他系统进程的实际占用仍进入内部启动判断。

阶段切换用`Update-HostResourceStage`重新准入，同时显式声明仍需保留的内存；账本保留观测到的
存活进程内存，不能因进入等待或传入零值就视为已释放。仍有本次工作子进程存活时禁止切换阶段；先完成
子进程清理并确认退出，才可降级资源，避免释放仍在使用的服务器或具名独占资源。入口登记本次子进程并在正常、失败或中断
路径调用`Exit-HostResourceStage`。若工作子进程仍存活，释放请求不会撤销其占用；父进程崩溃后也按
PID与创建时间继续识别后代，确认相关进程退出才回收。状态可通过`Get-HostResourceStatus`查询。
同一PID曾对应多个已登记创建身份时，调度器保留各自身份并按相容父身份判断后代，
既保留旧父退出后仍活的孤儿，也拒绝未登记的新PID实例的无关后代；工作后代使用同一判据。
调度器不杀进程；排查无用占用须结合命令、归属、日志和实际进展，不能仅凭低CPU利用率终止
可能正在I/O、等待许可证或保存结果的工作。观测失败不清空既有预约。
并发事务使准入或阶段切换的采样过期时，入口退避后重新采样并报告等待；正常竞争不算工作失败，陈旧观测不能用于准入。
释放不申请新资源：若当前账本与传入快照都确认该租约没有非owner、非系统console的存活后代，
且owner创建身份有效、相关身份观测完整，公共事务只释放该租约，不推进全局观测水位、不重新准入
或回收其他租约。这样无关排队轮询不能让较慢的正常释放无限饥饿；任一观测仍有后代或身份未知时继续保留。
唯一的子进程例外是可执行路径精确匹配 Windows 系统映像的`conhost.exe`：它不阻止阶段切换或显式
释放，实际内存仍进入系统观测，活动预约期间仍记录其身份与内存。普通工作后代不享有此例外。

旧Windows mutex与新账本没有双轨兼容。切换前须确认旧入口持有者及其子进程已结束，再从当前
公共入口启动新任务；已启动的旧PowerShell不会因工作树文件更新而自动迁移。不得删除账本或
另设账本来释放仍在运行的任务。

真实求解器入口在发布终态 manifest 后，向共享租约报告 `success`、`failed` 或 `interrupted`；仅持有
`SIMION`或`COMSOL`租约的顶层运行因此播放一次本机系统提示音（成功为三音上行完成提示，其余为 Hand）。提示不属于科学
输入、run identity 或证据，声卡不可用不能改变终态；设置进程环境变量 `SIMULATION_COMPLETION_SOUND=off`
可静默。阶段切换、批次、45 秒资源观测、重试、门禁和继承租约不得单独提示。

合法运行参数探索与源码／合同语义改动的验证边界见[操作指南](../docs/OPERATIONS.md#软件验证与科学证据)：
同一实现内的合法参数探索不默认执行软件测试；项目入口继续承担必要输入、支持域、资源与输出检查。

### 进程观测与预算

并行执行器每轮有活动worker时，由`Get-RepositoryProcessSnapshot`统一枚举一次`Get-Process`和
`Win32_Process`；CIM失败时同轮只抓一次原生父PID表。`Get-ManagedSolverProcessSample -ProcessSnapshot`
复用该轮枚举，各family仍分别复核创建身份、投影可能归属的父链并读取工作集、private、两者最大值及CPU。
快照不跨轮保存，标量读取也不构成全机同一时刻的原子测量。独立调用省略快照时仍按进程枚举、创建身份
复核、父关系枚举的原顺序执行；无关进程的未知身份不会扩大为其他family的失败。
当CIM缺少可执行路径时，`.Path`补偿只查询已归属的活进程，不为无关进程读取MainModule；
系统console仍须精确匹配Windows映像路径，未知祖先、PID创建身份及全部计量字段保持原语义。
2026-11-01在同一i9-9900K／16逻辑处理器、PowerShell 7.6.9、2核／2GiB准入下，
对1／4个family各做三对交替采样，每臂重新枚举329–334个进程并创建新snapshot／Process对象。
sampler中位数分别为0.261018→0.124298秒、0.792439→0.373825秒；
含snapshot的中位数分别为0.336703→0.184046秒、0.861682→0.437266秒。
这是局部采样成本，不含稳定的冷启动或完整门禁收益；原公共故障场景、真实console及READY身份回归保留。
共享采样脚本变更由现有catalog选中SIMION的managed-completion模块及host资源批次；
公共`test_observed_preparation_drain`十二项回归随host批次执行一次，不再遗漏于Repository范围。
受管Python的READY/ACK使用`Test-ManagedProcessLaunchAncestry`证明选定worker到原launcher的父链：
每步创建身份必须已知，父进程不能晚于子进程，首尾身份精确匹配且链不能成环。
Windows父PID可能已复用，其他旧分支的未知身份不否定这条已证明的链；
完整family的`ancestry_complete`和未知列表仍原样保留，不因此推断其他writer已停止或授权清理。
父PID复用与创建时刻判别的官方说明见[Microsoft说明](https://devblogs.microsoft.com/oldnewthing/20150403-00/?p=44313)。
2026-10-29在i9-9900K／16逻辑处理器、PowerShell 7.6.9上，最终冻结双臂重测保全完整源码与18个
交替样本。BASE为80,292 B混合工作树快照，不是Git 3005980；NEW为82,265 B的当前实现。
1、4、8个worker各三对采样的中位数分别为397.6261→456.7082 ms（+14.86%）、
2787.6528→1023.5216 ms（−63.28%）及4766.7381→2379.6709 ms（−50.08%）。全机进程与CIM枚举
均从每轮N次降至一次，六类完整返回字典相同；单worker没有改善，健康进程和危险处理策略不变。
本次采样合计37.6740721 s，外层127.286349 s包含准入等未细分开销，且同时有L2背景负载，不能据此
宣称求解或整个调度器提速。旧轮57.0983365 s调度观测中的长退出间隔未完整分段，也不计入采样收益。

单进程观察器`Invoke-ResourceBudgetedProcess`接收调用者在冻结边界解析的`-Limits`对象，
观察收据记录完整limits；没有项目工程预算的入口可显式传`-Limits $null`，仍跟踪进程身份、退出及公共物理危险，
不生成usage或虚构预算。`Complete-ResourceUsage`只读取已有usage收据收尾，不重新解析预算。
启动后的身份或采样异常先沿同一实际Process句柄等待根进程自然退出，再抛回原ErrorRecord；
异常Data中的`observed_process_exit_confirmed`／`observed_process_returncode`仅证明该直接根进程；
`observed_process_id`／`observed_process_started_at_utc_ticks`保留同一handle实际取得的身份，未取得启动时刻则为null。
等待自身失败时明确为未确认，并把次错保留在`observed_process_wait_error`；调用者不能据此释放
仍可能被使用的输入保护或执行载荷清理。这不替代host owner释放，也不证明任意后代进程已经停止。
Python向PowerShell传递派生预算可使用任务临时JSON，解析后由调用者finally清理；冻结的工程预算仍是输入权威。

墙钟、目录体积、进程树工作集或可用内存预算越限，每类只写一次`RESOURCE_BUDGET_WARNING`，
不据此停止健康进程。低CPU、暂时无输出或采样空洞也不是停止依据。原生进程明确失败时停止启动同批新工作，
已经运行的健康同级自然结束。只有持续低于中央策略的物理内存危险保留量才进入受管停止，并记录危险原因。

`New-RepositoryProcessObservation`和`Update-RepositoryProcessObservation`供包装器和COMSOL入口复用观测；
它们不启动进程、调度、重试或发布科学终态。物理危险阈值只来自[主机策略](../src/msplatform/execution/resources/host_resource_policy.json)，
无Limits时不写usage；目录或usage写入失败只告警，不能遮蔽已经确认的物理危险。

调用者请求观测收据时，同一文件的`last_process_observation`保存既有采样的活跃／跟踪／未知成员、
出生身份映射、相关成员的直接父边、祖先完整性、console分类，以及原root身份、退出确认、实际判断分支和等待阶段／原因。
`sampled_at_utc`是最后样本时间，`recorded_at_utc`是当前记录时间；进入原句柄阻塞等待前保存的样本
可能较旧，不把它解释为当前全家族已停止。采样异常保留上次样本并标明未知等待阶段，不造空集合。
这些字段只投影已计算事实，不新增进程扫描或推断GUI就绪。预算usage沿原写入合并；无预算但显式
请求启动身份收据时沿该原收据记录，不造limits或峰值。无预算／排空等待的相同状态最多每30秒刷新，
状态变化和进入阻塞等待时立即写入；未请求收据的旧调用不新增文件。写盘失败仍只告警，不能覆盖首错、
触发重启或提前释放输入保护。正常root退出、家族排空、guard／租约释放和发布终态仍须分别由原owner证明。

RF 资源预算的两个调度用例改由真实 admission-pause 事件释放短测试 worker，纯报告矩阵合批执行。
同范围三项实测39.189→15.879秒、父PowerShell启动9→3；后者使用隔离的已提交生产源码并保留worker退出检查。
其他失败、未知writer与自然排空测试保留；这不是完整模块、Owner或Repository耗时。缺失释放信号、错误接受全部报告、外层非零及坏JSON的变异检查均能使测试失败。

生产leaf可在现catalog的test_selection.dependencies用exact匹配声明受影响模块；已删除leaf和未知来源仍回退完整owner。SFI的SelectedTestModules复用原CLI与实际前置，完整分片按实际模块union判定，不能将替换式subset误当追加式完整范围。Owner／Repository保持全范围；纯测试Changed快路径保持，窄leaf结果不代表完整owner或Repository通过。
`frozen_inputs.py`的机制测试归公共合同owner，真实`workbench_seed`消费者测试归SIMION owner；
两者通过同一catalog精确选择，混合SIMION改动时seed模块仍只在其owner执行一次。

### Pure static gas inputs

`msplatform.contracts.gas` owns explicit immutable gas/source/model-selection data;
`msplatform.gas.field` prepares and samples declared static uniform, box-region and
legacy-policy axisymmetric data, using existing rigid transforms and constants.
No vendor, context or run owner is needed for these pure actions. See the
[domain directions](../docs/REPOSITORY_ARCHITECTURE.md#可安装科学核心与迁移边界).
The two existing-catalog contract modules test real sampler/state behavior;
point-query checks do not establish step-crossing, Lua/Program, HS1/SDS or native
qualification. Production adapter migration and its original callback/RNG/resource
closures remain separate P4 work.
The composed pure sampler/boundary checks passed 36 actual methods; the corrected
Changed-route method separately passed all eight path cases. An initial outer class-selector
error remains recorded. Ordinary direct-wheel and sdist-rebuilt-wheel acceptance passed
in 233.590 seconds, exercising the installed gas probe and original consumers with source
access denied. All 440 package payloads match the current source, sdist and both wheels.
These results cover this pure input slice; final Repository and native gas acceptance remain open.


### Installed single-reflection frontend field production

`msplatform.workflows.single_reflection_flight.frontend_fields` owns the scientific
member/domain projection and actual cache selection. It uses the existing SIMION
field worker, cache manager and audit implementations. The former root
`single_reflection_flight/field_stage.ps1` implementation is retired; the existing
`execute.ps1` retains only ordered dispatch and the original capacity admission,
pressure recovery, observations and receipt collection. That outer PowerShell
owner orchestration remains an open P4 migration responsibility.

A verified published source uses its original producer inventory and source
protection lease in the same capacity session. A cache HIT performs no native
work when its audit is reusable; audit-only entries keep their original zero raw
reservation. Fine-domain members bind the corresponding completed parent member
through the canonical field-plan projection. Changed selected cache generations
fail for the original owner to replan. No new owner, cache policy, scientific
threshold, automatic retry or field-family copy is introduced.

Worker export first remains in the existing transaction scratch directory; only
observed successful completion adopts the payload. Audit failure on a pre-existing
sealed payload does not repeatedly account bytes; new build/publication failures
retain conservative accounting. These software fixes do not grant native or
scientific qualification. Source/clock/particle and native Lua semantics are
unchanged by this migration.

### Member-worker fault-test boundaries

The worker contract test retains real managed cold/HIT, missing native receipt,
accounting-hold and publication-hold processes, including inherited tokens,
PID/drain and distinct ledger assertions. Corrupt-cache, known export failure
and known audit failure exercise the actual request/main/cache/report boundary
with real files, key protection and the enclosing software GATE identity. Their
inert transport supplies no OS completion facts; the report verifies their
absence. All five fault identities remain. The production observer policy and
the original large-tool preflight test are unchanged. This reduces repeated
process plumbing without treating controlled state-machine facts as native or
OS evidence; it does not close the full software performance target.
