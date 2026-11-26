# 架构迁移执行记录

本页是 2026-11-26 批次 A 的接续入口；首轮完成不等于全仓迁移。输入为用户提供的
`ms_agent_execution_20261126` 执行包（start_agent、review_resolutions、implementation_plan、review_decisions）。
原评阅 145 同意、20 修改、2 不同意、29 处具体意见保持原意；技术实施选择不回写为原表批准。

## 开工事实与边界

- 开工 checkout HEAD：`260c354d8beeeed26a40fdc7c7602e45f06d8934`；实际实现/审计基线
  `b94e0818a4823102425b6ad77327106b07143250`。
- 用户确认旧目标分支已经合入 master；本次从当前 HEAD 创建 `task/architecture-migration-20261126`。
  用户随后授权本地分支及 GitHub 推送；不合并、不改写远端历史。
- 开工仅有未跟踪 `artifacts/`，保持不动。提交图复核确认开工 checkout 是 master 的祖先；
  已暂停所有 Agent 写入、仅暂存本任务两个依赖文件、快进合入 master，再恢复本任务改动，无冲突。
  最初将差异方向误记为审计后增量，现已纠正。master 已含 common/projects/integrations 目录迁移，
  门禁是 `tools/repository/verify.ps1`，普通安装测试是 `tests.contracts.test_installed_scientific_core`。
  master 与执行包审计提交完全相同，无需额外审计后增量分析。
- 本轮正式功能：配方/物性、静态解析 E/B 的数值 tracing、受管结果、CLI/API、复用与安全缓存 GC。
  长期验证：独立解析对照、安装验收和生命周期行为测试。B/C 与 M06–M08 不自动实施。

## 合同与 ownership（实现中）

Agent 0：CLI、工作流、Parquet/HDF5 结果、文档与联合验收。
Agent 1：`physics/`、`recipes/`、根参考 TOML；Agent 2：`fields/`、`tracing/`；
Agent 3：`storage/`；Agent 4：只读评阅映射与旧消费者核查。Git 写操作由 Agent 0 串行完成。

公共结果使用 SI + float64、int64 粒子 ID、实验相对时钟；常量冻结现有质量值，CODATA 升级独立。
场显式声明 E 与 B（零也须声明）；仅静态给定场，时变、碰撞、自洽等未支持组合失败关闭。
初态、事件、终态和轨迹独立；物理结果、停止原因、完整性、执行成功分轴。
新根由唯一 ArtifactStore 管理，禁止新旧账本共同管理。旧链暂不接管。

## 工作单元与验证

### A0：启动审查与公共合同

已读规则、执行包和 JSON 覆盖规则；具体否决优先于泛化同意。
新 CLI 为 `msplatform`，动作统一 tracing；无 transport_mode/友好解析别名。
下一步：实现参考闭环并以真实数值和生命周期行为确认 AC01–AC14。

### A1/A2：配方、单位与真实 tracing

已实现 `physics/reference.py`、`recipes/reference.py`、`fields/__init__.py`、`tracing/__init__.py`。
根 `recipes/reference/` 的四份 TOML 是唯一作者正文。参考单元明确是解析参考几何，不假装真实仪器 provider。
公共常量冻结既有 u=`1.66053906660e-27 kg`、e=`1.602176634e-19 C`；OA 历史兼容值不改。
Decimal 前缀转换一次舍入，0.9 mm 与 0.0009 m 身份一致，label 不影响 recipe/assembly 身份。
装配生成器支持规范串接序列含重复项，执行仅支持实际验证的 reference_cell；图结构明确拒绝。

独立闭式 oracle 与实际 DOP853 在 31 个相同实验时刻比较（含非零初时刻、负电荷、交叉 E/B）：

| 算例 | 最大位置分量误差 m |
|---|---:|
| 无场 | 4.86e-17 |
| 均匀 E | 1.39e-17 |
| 均匀 B | 2.08e-17 |
| 交叉 E/B 负离子 | 6.94e-18 |

最大速度分量误差 ≤1.10e-11 m/s。仅证明参考静态场范围，不证明 RF、商业后端或空间电荷。
事件使用平面根定位；步内多次穿越/切触可能漏检，必须选择合适 max_step，不能宣称任意几何完备。

### A3：存储与真实链初次集成

`storage/store.py` 为新根的唯一 owner；短 SQLite 事务协调 publishing/ready/delete_pending/deleted，
payload I/O 在外，独立 JSON manifest 与 SQL 记录均校验；claim_key/put_asset_claimed 消除获取/发布与GC竞争窗口。
新受管根必须在所有 Git 工作树之外；外层 workspace 本身也有 `.git`，因此实际验收根使用
`C:\Users\Liao\msplatform-artifacts\architecture-a-20261126`，不在旧账本树下。
失联 claim 保守保留；自动验证进程树后释放未实现，不用 TTL 猜测释放。

`workflows/reference_tracing.py` 接通配方→预检→场资产→完整粒子批→独立表/轨迹→发布→重读统计，
`cli.py` 与 `__main__.py` 共用实现。运行自含科学证据，缓存仅 provenance，不变为永久 pin。
缓存键含真实科学输入、相关实现摘要和 NumPy/SciPy/常量版本；无关 label/仓库文档不失效。
失去一个粒子批文件只重算该批，其他批与场保持命中；软水位自动回收后历史 run 仍可重读。

联合针对验证：2026-11-26 `python -m unittest tests.contracts.test_reference_workflow
tests.contracts.test_reference_recipe tests.contracts.test_reference_tracing tests.contracts.test_artifact_store -q`，
22 项 PASS，6.838 s；对应新主链 Ruff PASS。包含真实发布/重读、int64 大于2^53的ID、缺件局部重算、
label/物理变化、自动GC、0命中、取消和注入的求解器失败诊断保真。故障注入不冒充真实物理成功。
初次开发树 run 已完成，但安装后验收尚待执行，不据此关闭 AC13。

## 官方路径与版本

查阅日期 2026-11-26，使用官方库API，无自建文件编码器：
[Python 3.11 TOML](https://docs.python.org/3.11/library/tomllib.html) 的 parse_float=Decimal；
[SciPy solve_ivp](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.solve_ivp.html)
的 DOP853、分量atol、事件根定位（在线文档1.18，锁定1.17.1，本轮测试验证实际安装行为）；
[Arrow write_table](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.write_table.html)
26.0.1 的显式schema读写；[h5py datasets](https://docs.h5py.org/en/stable/high/dataset.html)
3.16.0 的float64/int64分块数据集；
[SQLite事务](https://docs.python.org/3.11/library/sqlite3.html#transaction-control)、
[os.replace](https://docs.python.org/3.11/library/os.html#os.replace)、
[shutil.rmtree](https://docs.python.org/3.11/library/shutil.html#shutil.rmtree)。
Parquet/HDF5 为本次用户指定公开数据合同，取代旧“先证明CSV性能瓶颈才引入”的前置限制；
未借此迁移无关旧结果。新增 pyarrow=26.0.1、h5py=3.16.0 纳入发行与锁文件。

## 剩余消费者与下一批

旧 SIMION tracking/state relaunch、FullJoint 分段分支、Candidate/Formal 资格路径及旧容量账本
仍存在；按真实连续生产链接管进入 B/C，不将新参考链通过当作其退役证据。
具体文件清单、验收数值和交付 HEAD 在各工作单元完成后补录。

## A2/A3 补齐与隔离验证

首次 Changed 门禁运行期间，逐条验收复核发现了物性资源、事件标识和运行控制的实际缺项。
为保护正在消费的源码快照，后续修正置于临时隔离 checkout；原工作树和已有产物保持冻结。
临时 checkout 不创建另一条任务分支，最终由当前任务分支接入同一代码提交。

已补齐：`physics/data/reference.json` 随包发布唯一的新链常量/真空/none 数据，旧版本常量值不变；
初态 `parent_particle_id=null`、`lineage_status=unavailable_initial_snapshot` 明确未知谱系，
初态只是快照，不伪造真实 birth/次级事件。事件有每粒子连续 `event_sequence` 和法向速度符号方向；
磁场下同一观测面的重复穿越保留独立事件。public tracer 与 CLI 均拒绝未知科学字段、非公共常量、
非真空及未实现组合；真实有限输入数值溢出报告 numerical_failure，诊断经发布/重读保留。

`begin_run/mark_running/run_status/finish_run` 将执行状态与 publication 状态分轴，运行前即有固定
run_id/月桶和冻结输入；容量不足保留 queued 及原因，不伪造启动。当前无后台调度器。
`recover_controls` 在持有精确 token 的 OS 锁后才释放失联 claim/预留，无 TTL 猜测。
当前参考 tracer 只在本进程计算；后续 native/独立消费者必须自行持有使用保护，不能根据父进程退出
推断全部后代退出。Windows junction 和多硬链接载荷拒绝，外部目标保持不变。
软水位统计包含登记 run 的占用；只清合格 cache。工作流按本 run 新增字节减少未落盘预留。

来源记录单列 `repository_source`：显式传入完整 SHA 时记 declared，否则诚实记 unavailable；
不会从 cwd 猜来源，也不将整仓 SHA 用作科学缓存键。author.toml 与 resolved.json 均冻结在 run 内。

隔离开发验证：49 项 PASS，26.665 s；包括 6 配方、6 tracing、15 storage、5 完整工作流、
16 科学边界和 1 旧门禁缺陷定向复验。Ruff 与 diff-check PASS。局部验证设置源码路径，
**不作为安装后证据**。旧缺陷是 `test_adapter_uses_real_facade_with_isolated_ledger` 强选
`sys._base_executable`，使虚拟环境任务误用未装包的系统 Python；已仅改两处为当前 `sys.executable`，
不在全局安装包、不修改生产 facade。先前 PATH 重试仍失败的事实保留在验收记录。

### 29 处具体意见的落实表

“原状态”来自评阅表，下面的实现细节属于执行包选择；不把它们回写为新增同意。

| ID | 原状态 | 本轮落实 / 后续边界 |
|---|---|---|
| A02 | 同意 | 版本化严格合同、公共能力预检、依赖摘要；新组合仍须独立验证 |
| A10 | 修改 | 规范 single_reflection_tof 不含 OA、无 alias；真实拆分 B |
| A11 | 修改 | Assembly 物理内容与 SimulationRecipe 分工；真实仪器 B |
| A13 | 修改 | 新链仅连续 tracing；旧重发射 B/C 按链退出 |
| A15 | 同意 | 自洽未实现且明确拒绝；M06 独立 |
| A20 | 修改 | SI/float64、Decimal 边界、分量容差、冻结常量；不混入 CODATA 升级 |
| A24 | 修改 | 独立 ArtifactStore、SQLite/OS锁、预留/GC/恢复；旧 owner 收敛 C |
| N02 | 修改 | msplatform CLI 与 python -m 同实现 |
| N04 | 修改 | SR-TOF 仅显示；真实 provider B |
| N05 | 修改 | RF-MP 仅显示；现有 RF 变体保留 |
| N06 | 修改 | MR-TOF 仅显示；规范名 multi_reflection_tof |
| N07 | 修改 | MR 不设空 variant；真实模型/注册对齐 C |
| N09 | 修改 | IP 不设空 variant；真实模型/注册对齐 C |
| N13 | 不同意 | 不注册 reflectron 子部件；内部几何语义保留 |
| N14 | 不同意 | 不注册 drift_region 子部件；内部几何语义保留 |
| N15 | 修改 | 单一名称生成器、无友好解析 alias；真实 OA 组合 B |
| N16 | 修改 | 同一生成规则；真实 RF/OA/TOF 配方 B/C |
| N17 | 修改 | 同一生成规则；真实 IP/MR 配方 B/C |
| N21 | 同意 | 通用 mass_scan 的自由物种/数量及分析条件进入 B，不本轮扩展 |
| N24 | 修改 | 新链无 segmented；旧生产执行链 B/C 完整退役 |
| N26 | 修改 | 公共 ParticleTracer/particle_tracer/tracing 一致 |
| N27 | 修改 | 新合同不含 transport_mode，也无单值替代枚举 |
| N43 | 同意 | 结局/停止分轴、参考面归属、原生不可用显式 null；真实映射 B |
| N54 | 同意 | 新主题拆至 TRACING/ARTIFACT_STORE/index；旧原生正文其余 C |
| N58 | 修改 | 双锥独立 dual_cone_tandem_quadrupole，覆盖泛化 DCI 旧提案 |
| P07 | 同意 | E/B 显式声明、能力边界；时变/自洽未实现 |
| P08 | 修改 | 新公共领域 tracing；旧自有 tracking 逐链 B/C |
| P24 | 修改 | 新 Store 固定 runs/YYYY/MM/run_id，UTC 元数据 |
| G04 | 同意 | 耗时优化项与正确性失败分开，不按理想分钟数伪报通过 |

### 活动旧消费者与退役入口

以下路径均在 `src/msplatform/` 下，仍可执行，不因参考链完成自动改写；历史产物 owner/状态保持。

| 旧消费者/字段 | 当前 owner | 目标 / 批次 | 退出或保留条件 |
|---|---|---|---|
| assembly/handoff.py 的 HandoffResult；backends/simion/operations.py 消费 | assembly + SIMION | 连续完整母群/时钟合同，B | 先抽出正确校验；对应连续链接管后退役执行支路，历史只读 |
| backends/simion/tracking_execution.py 的 segmented_upstream/state_relaunch；tracking_collection/program writer | SIMION | tracing adapter，B/C | 连同 writer/默认值/门禁退出；保留原 ID 完整批分与真正检查点 |
| contracts/schemas/assembly_registry.schema.json 的 segmented_handoff | assembly registry | 连续链注册，B | 随真实消费者迁移，不只删除字符串 |
| workflows/resources/accelerator_interface.ps1 的 FullJoint 范围/重释放分支 | 原工作流 | 连续实际替代，B | 确认物理场范围/实验时钟后逐分支退役 |
| workflows/single_reflection_mass_spectrum*.py 的 candidate_mass_spectrum、固定五质量/命中约束 | 旧质量谱工作流 | mass_scan，B；等级收敛 C | 校准条件回归具体分析，不限制通用追踪；历史保留原名 |
| components/registry.py、examples/rf_oatof_functional_v1.json 的 single_reflection_oa_tof | 原 provider/示例 | OA 与 SR-TOF，B | 不重写已经复用的 OA 物理；按真实几何与源/场对照 |
| MR/IP 旧长包名和注册；双锥长 package ID | 各组件 | multi_reflection_tof/ion_processor；独立双锥，C | 按真实 provider 迁移，不把项目ID、组件ID、显示名混同 |
| execution/artifact_retention.py、capacity_session、reconcile_artifact_capacity | 旧生命周期 owner | 按根接管，C/剩余M03 | 新旧 owner 不同时管理对象；新 Store 不读取这些目录进行删除 |
| Candidate/Formal 旧 Schema、目录与政策 | 各原生生产链 | 执行/验证/保留/基线分轴，C | 只读历史保留原意；不能整体字符串替换 |

物性/单位的剩余活动消费者：

| 路径 | 当前来源与迁移边界 |
|---|---|
| components/single_reflection_oa_tof/reflectron_dual_stage_solver.py | 使用公共 LEGACY_OA_TOF_ATOMIC_MASS_CONSTANT_KG；B 先冻结旧版本，再单独评估数值升级 |
| backends/comsol/matlab/oatof_configure_particle_model.m、oatof_build_saved_particle_solution.m | 内嵌 u/kg、e/C 换算；B 随 OA/COMSOL 先复现后迁移 |
| backends/comsol/matlab/configure_oatof_segmented_output.m | 质量/电荷表达式；其中 segmented 为采样策略，不按名字自动当跨组件重发射删除 |
| components/dual_cone_tandem_quadrupole_ion_interface/config/ion_transport_science.json → backends/simion/resources/dual_cone_gas_assisted_transport.lua | SDS 气体质量/直径来自配置，Lua 不重复硬编码；B/C 从公共物性与研究环境生成，保留直径定义 |
| components/dual_pressure_rectilinear_ion_processor/config/baseline.json → gas_regions.py / backends/simion/resources/rf_ip_tracking_hs1.lua | 独立气体质量/HS1 截面，现有 placeholder 适用性不伪装已校准；B 迁移且不与 SDS 直径混同 |
| components/dual_cone_tandem_quadrupole_ion_interface/config/gas_flow_science.json → backends/comsol/matlab/build_and_solve_axisymmetric_gas_flow.m | SI 物性与 kB；C 按冻结值生成视图。backends/simion/gas_runtime.py 已复用公共 kB，不误报重复权威 |

下一批 B 的入口依次为 OA/SR-TOF 拆分、现有原生后端公共端口、自由 mass_scan、对应分段链退役；
C 处理剩余消费者/生命周期 owner/总等级/命名和文档收敛。两批均须另行启动，M06–M08 不混入。

### 必要门禁的首轮事实

原工作树的首轮 Changed 门禁使用显式 37 个本任务路径，排除开工已有 artifacts，
摘要位于外部 `architecture-a-gate.json`。完整普通 wheel + sdist 安装验收 PASS，2090.848 s；
machine_contracts 的另外两个分组 PASS（约 780/736 s），静态/文档/Ruff PASS。
总门禁仍为 FAIL：machine_contracts__tests_04 中仅旧 facade 夹具误选系统解释器；
修正后的同一方法已定向 PASS，不把失败的原调用改写成成功。
instrument_assembly 四个分组按首错策略 BLOCKED，尚需补跑；没有据此声称其通过。

末次物性/事件/存储变化仅影响新参考域及其安装资源；原生实现未变化。
`InstalledScientificCoreTests.verify_reference_delivery` 是显式窄验收入口，复用同一父方法的
wheel/sdist 构建、inventory、sdist 重建和相同参考探针，在昂贵旧夹具前选择实际受影响范围。
普通全量测试默认行为保留。窄入口另核验 HEAD/index/status/冻结输入字节、两臂 offline 源树与模块 origin，
子进程清除 PYTHONPATH 并使用隔离解释器。它不替代旧原生能力验收。
最终候选的该窄安装与尚未执行的装配范围将在候选提交后运行；目前未记作 PASS。

## 批次 A 最终验收

科学代码提交：`8ba6a4e91c86df8b68913b2209e12dc552363c4a`，基线为 `b94e0818a4823102425b6ad77327106b07143250`。
已将隔离候选快进接入本地 `task/architecture-migration-20261126`；原有未跟踪 artifacts 保持不动。
本节替代上一节“尚待运行”的状态；上一节保留首轮事实，不回写失败为通过。
最终文档提交仅补证据，不改变该科学代码与安装资源。

### 实际安装运行与复现

最终候选普通 wheel 和 sdist 重建 wheel 的显式窄验收 PASS：430.867 s（外层墙钟431.600 s），
两臂均运行公共 console 与 `python -I -m msplatform`、API、独立 E 解析 oracle、冷读和真实复用。
两棵源码树临时 offline，installed module origin PASS，冻结输入 3206 项，清单摘要
`85e1b47ed06c4a66bfd380d80fea08797ebe917a40c6c0f2d46234b3e5628731`，HEAD/index/status 对照通过。
命令为：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.contracts.test_installed_scientific_core.InstalledScientificCoreTests.verify_reference_delivery
```

另外用普通 wheel 在全新虚拟环境通过 pip 安装实际声明依赖（配套锁约束，无 editable、无源码路径注入），
保留了用户可直接运行的交付目录：
`C:\Users\Liao\msplatform-artifacts\architecture-a-delivery-8ba6a4e9`。
其中 `distribution/` 有 wheel、sdist 与锁，`env/` 为已安装环境，`study/` 保存原 TOML 及实际命令 JSON，
`store/` 为唯一 ArtifactStore 根。可复制运行：

```powershell
$delivery = 'C:\Users\Liao\msplatform-artifacts\architecture-a-delivery-8ba6a4e9'
$cli = Join-Path $delivery 'env\Scripts\msplatform.exe'
$recipe = Join-Path $delivery 'study\uniform_e.toml'
$store = Join-Path $delivery 'store'
& $cli --help
& $cli validate $recipe
& $cli run $recipe --artifact-root $store --source-revision 8ba6a4e91c86df8b68913b2209e12dc552363c4a
& $cli results inspect c9f03dc2ac9d44379918f1c5dde92738 --artifact-root $store
```

| 实际对象/唯一变化 | 结果 |
|---|---|
| 首次普通安装运行 `c9f03dc2ac9d44379918f1c5dde92738` | succeeded；完整母群1、终态1、检测1、101个float64采样 |
| 初态100 u/+e、vx=10000 m/s、E=(2000,0,0) V/m、B=0；x=0.01 m检测平面 | 事件时刻 `9.185857056658535e-7 s`；physical_outcome=detected、stop_reason=normal |
| 对独立匀加速闭式解，使用同一物理采样时刻 | 最大位置分量误差 `8.673617379884035e-18 m`；检测时刻误差 `1.1540919197546408e-16 s` |
| 同一输入第二个 run | field.reused=true；particle batch.reused=true |
| 通过已安装 CLI 执行 GC | 实际释放39,490字节合格缓存；不删除run科学证据 |
| GC 后运行 `9b5b03d63ce14fe8b4111bb2c120554a` | 场与批均MISS并真实重算成功；首次run再次冷读成功 |
| 缺件局部重算（两个完整独立粒子批的行为fixture） | 缺一批终态缓存文件后仅该批重算，另一批及场HIT；label不失效，物理输入变更失效 |

`study/first.json`、`reused.json`、`gc.json`、`rebuilt.json`、`retained.json` 是实际命令结果；
run 内冻结 author/resolved/provenance/execution/summary/manifest、三张 Parquet 和 HDF5。
GC 删除的是明确可回收的性能层，原结果自含科学证据；不是删除唯一载荷后补造结果。

### AC01–AC14 对账（仅批次 A 声明范围）

| AC | 证据与结论 |
|---|---|
| AC01 | 29意见表、唯一规范修订与B/C清单；原145/20/2及否决不改写，实施选择单列 |
| AC02 | 新CLI/端口统一tracing；6配方/6tracing测试与已安装能力预检，未知科学字段和不支持组合拒绝 |
| AC03 | assembly物理指纹、生成名、recipe_id、owner、label、run_id独立；重复运行新ID且科学缓存不受label影响 |
| AC04 | Decimal单位边界、分量容差、非零实验初时刻、公共常量冻结；无常量数值升级 |
| AC05 | 已安装physics/data资源实际加载；本轮真空/none/常量单源，六类旧消费者逐项列出 |
| AC06 | 4种独立闭式oracle与实际DOP853、重复磁场穿面；安装后E链另有实测误差，未宣称时变/RF验证 |
| AC07 | 发布后三表/HDF5冷读，母群闭合、权重独立、int64大ID大于2^53仍精确 |
| AC08 | 0命中/截断可成功，取消/真实溢出/受控solver失败/缺记录分别表达，诊断经序列化保留 |
| AC09 | 参考平面精确component/electrode/surface归属；未知native信息显式null/不可用，不从终点猜测 |
| AC10 | 15项storage验证包含共享必要引用、原子获取/删除竞争、发布/删除中断恢复、真实短进程死亡控制恢复 |
| AC11 | run占用也计软水位；软超限可继续，实际free不足先GC并保留queued原因，保护对象不删 |
| AC12 | 首/次运行、相关输入变更、label、缺件单批重算、真实GC后重算均有行为证据 |
| AC13 | 最终普通wheel/sdist窄验收与独立交付环境真实全链通过；软件门禁的旧基线失败另表保留，未冒充全仓PASS |
| AC14 | A已实现/验证范围与下列旧链正确性欠项、未实现能力、耗时优化分开；B/C和M06–M08未开展 |

### 软件门禁结果与旧链正确性欠项

| 检查 | 实际结果 | 范围/限制 |
|---|---|---|
| 最终针对测试 | 49 PASS，26.665 s | 单位、数值、数据、存储、依赖边界及旧解释器夹具定向修复；开发树验证 |
| 完整原普通安装验收 | PASS，2090.848 s | 首轮冻结源码；不冒充末次资源/字段修改后的证据 |
| 最终候选参考安装 | PASS，430.867 s | 普通wheel和sdist重建；只关闭受影响参考链 |
| 静态/文本字节/Ruff/文档 | PASS | staged标准、Owner前置和文档结构；不是商业或GUI资格 |
| Changed首轮 | FAIL，约2149 s | 单个旧测试强选base Python；修正后同方法定向PASS，原FAIL保留 |
| instrument_assembly Owner | FAIL，约697 s | 01/03/04分组PASS；02组193测试仅1个历史资产兼容ERROR |

Owner 唯一失败为
`tests.workflows.paired_accelerator.test_paired_accelerator_pulse_preparation.PairedPulsePreparationTests.test_actual_110745_all_100_states_use_original_235338_common_field`。
原因是历史 schema2 plan 的 `grounded_shield_id`、其他角色键及环ID列表与当前消费者硬取 `common_ground`
等键不兼容。这是实际旧链正确性缺陷，**不是性能项，也不是PASS**。
用独立 b94 checkout 和同一235338 manifest/plan只读调用即可重现；相关消费者与基线字节完全一致，
故不归因于A参考实现。按本轮不混入B的边界，保留为B的明确入口；不能修改旧manifest使其通过。

可复制只读基线复现（运行后退出1并报告common_ground，无模拟/无产物写入）：

```powershell
$env:PYTHONPATH='C:\Users\Liao\mass_spectrometry\.tools\p4-composed-candidate-r1\src'
Set-Location 'C:\Users\Liao\mass_spectrometry\.tools\p4-composed-candidate-r1'
& 'C:\Users\Liao\mass_spectrometry\simulation_repo\.venv\Scripts\python.exe' -c "import json; from pathlib import Path; from msplatform.backends.comsol.paired_static_model import load_paired_static_model_source; p=Path(r'C:\Users\Liao\mass_spectrometry\artifacts\projects\instrument_assembly\runs\20261025_235338__sim__cross__paired-accelerator-static-field'); plan=json.loads((p/'inputs/bvp/paired_accelerator_static_field_plan.json').read_text(encoding='utf-8-sig')); print(__import__('msplatform.backends.comsol.paired_static_model',fromlist=['']).__file__); load_paired_static_model_source(p/'run_manifest.json',p/'run_manifest.json',expected_plan=plan)"
```

该历史 manifest SHA256=`10862ABF99C5D20A094E6FE40277D81D115059153F4FCE9D6E3DECAC1EAECE83`，
plan=`26EDF6019898507E5A74C3792AF465FB3096816893F07AF1D70D2336E13EA49D`；
`backends/comsol/paired_static_model.py` 文件SHA256=`078DA8AFE33EBD263101A5AB72D3B4E6A6DE55B707430069794EC6C94B70D9B4`，
`workflows/paired_accelerator_pulse/prepare.py`=`80841BDBC0050964F670805E342BBF71F117D860D3955D2321C219036A9CCC12`，当前与b94一致。
修复入口是明确版本/形状的只读映射、环列表及电压/几何语义校验和最小行为fixture，不重写原科学历史。

未实现/未验证：真实仪器组件迁移、SIMION/COMSOL新端口、RF时变、自洽、真实birth/次级生成、
native内部checkpoint、完整索引重建、后台自动派发、全3D/AMR/丰富可视化。它们不被本轮参考链证明。
耗时优化：原完整安装约35分钟、窄参考安装约7分钟、Owner约12分钟，均未作为科学或软件PASS替代。
未为追求理想时间重跑完整回归或大型模拟；只有实际受影响的安装范围和原先BLOCKED范围补验。

提交后在原工作树对同一49项重新核验 PASS，23.256 s，使用当前已安装开发环境，无源码路径注入。
该次绑定已接入的8ba代码，覆盖最终junction测试的明确cwd/timeout。它是小型针对性核验，不是全仓回归。

临时隔离 checkout 已确认路径和干净状态后经 `git worktree remove` 删除，移除文件逻辑大小
221,673,169字节（约211MiB），可从8ba提交完整重建。开工已有 artifacts、基线checkout及历史manifest未动。
成功安装验收的临时环境由既有验收框架清理；两次失败门禁的诊断保留用于B旧链复核。
独立交付环境、发行文件、真实run证据与早期小型开发诊断保留在Git树外；不删除必要科学结果。

### CLOC 明细

CLOC 2.10，基线 b94e0818a4823102425b6ad77327106b07143250 → 代码提交 8ba6a4e91c86df8b68913b2209e12dc552363c4a。最终证据文档不改变以下代码计数。

命令：tools/repository/report_cloc_delta.ps1 -Base b94e0818a4823102425b6ad77327106b07143250 -Current 8ba6a4e91c86df8b68913b2209e12dc552363c4a -ClocExe <workspace>/.tools/cloc/2.10/cloc.exe。首次本机Perl locale不支持C.UTF-8，改用LC_ALL/LC_CTYPE/LANG=C后原工具通过，未替换计数口径。

每格：baseline → result (delta)。未分类为0，无静默归类。

| Scope | Language | Files | Blank | Comment | Code |
|---|---|---:|---:|---:|---:|
| total | JSON | 281 → 282 (1) | 0 → 0 (0) | 0 → 0 (0) | 125984 → 126022 (38) |
| total | Lua | 119 → 119 (0) | 413 → 413 (0) | 828 → 828 (0) | 13219 → 13219 (0) |
| total | MATLAB | 186 → 186 (0) | 1066 → 1066 (0) | 2053 → 2053 (0) | 19701 → 19701 (0) |
| total | PowerShell | 150 → 150 (0) | 1100 → 1100 (0) | 1195 → 1195 (0) | 46113 → 46113 (0) |
| total | Python | 1419 → 1435 (16) | 32657 → 32905 (248) | 42260 → 42461 (201) | 394041 → 396011 (1970) |
| total | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 51 → 51 (0) | 214 → 214 (0) |
| total | TOML | 1 → 5 (4) | 10 → 43 (33) | 2 → 2 (0) | 58 → 219 (161) |
| total | YAML | 2 → 2 (0) | 8 → 8 (0) | 20 → 20 (0) | 506 → 506 (0) |
| total | SUM | 2168 → 2189 (21) | 35280 → 35561 (281) | 46409 → 46610 (201) | 599836 → 602005 (2169) |
| production | JSON | 258 → 259 (1) | 0 → 0 (0) | 0 → 0 (0) | 42302 → 42340 (38) |
| production | Lua | 99 → 99 (0) | 333 → 333 (0) | 703 → 703 (0) | 11141 → 11141 (0) |
| production | MATLAB | 118 → 118 (0) | 526 → 526 (0) | 1462 → 1462 (0) | 12164 → 12164 (0) |
| production | PowerShell | 138 → 138 (0) | 1037 → 1037 (0) | 1149 → 1149 (0) | 44012 → 44012 (0) |
| production | Python | 673 → 685 (12) | 16622 → 16796 (174) | 11480 → 11588 (108) | 181604 → 182893 (1289) |
| production | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 51 → 51 (0) | 214 → 214 (0) |
| production | TOML | 1 → 5 (4) | 10 → 43 (33) | 2 → 2 (0) | 58 → 219 (161) |
| production | YAML | 2 → 2 (0) | 8 → 8 (0) | 20 → 20 (0) | 506 → 506 (0) |
| production | SUM | 1299 → 1316 (17) | 18562 → 18769 (207) | 14867 → 14975 (108) | 292001 → 293489 (1488) |
| tests | JSON | 23 → 23 (0) | 0 → 0 (0) | 0 → 0 (0) | 83682 → 83682 (0) |
| tests | Lua | 20 → 20 (0) | 80 → 80 (0) | 125 → 125 (0) | 2078 → 2078 (0) |
| tests | MATLAB | 68 → 68 (0) | 540 → 540 (0) | 591 → 591 (0) | 7537 → 7537 (0) |
| tests | PowerShell | 12 → 12 (0) | 63 → 63 (0) | 46 → 46 (0) | 2101 → 2101 (0) |
| tests | Python | 746 → 750 (4) | 16035 → 16109 (74) | 30780 → 30873 (93) | 212437 → 213118 (681) |
| tests | SUM | 869 → 873 (4) | 16718 → 16792 (74) | 31542 → 31635 (93) | 307835 → 308516 (681) |

完整过滤口径（由原工具报告，以下仅格式化其数值，未自行计行）：

```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|tests/**/__init__.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```


## B 前收尾（2026-11-26，本轮不启动 B）

对照交付 `dad49d1c9049a5c3ba349003af4998d50ec9082e`；开工 HEAD 与此相同，分支
`task/architecture-migration-20261126` 跟踪同名 origin 分支，无后续提交。
原有未跟踪 `artifacts/` 保留；不改历史研究资产，不合并、不推送。本节是本轮接续入口，
上文 A/P4 的原始结果保持原义，不能把本轮定向复验外推成 Owner/P4 全门禁通过。

### 1. 计算写入者失联

已完成：`storage/store.py:run_writer/recover_interrupted_runs` 使用原 OS 文件锁机制，
`reference_tracing.run_recipe` 从 running 前到发布/异常收尾持锁。只有取得原随机 token 锁且
尚无 publishing/ready 记录的 running 才变为 failed，原因明确为 writer interrupted before publication。
原 ID、冻结输入、部分 work 字节保留，`run_status.work_path` 可查询；不生成终态、不发布成功缓存。
无 token 的旧 running 保守保留待调查。claim/预留经原 recover_controls 释放；活 writer、已发布结果不变。
已校验的 publishing 恢复可消除此前发布 I/O 异常留下的 failed 状态，以 manifest 的真实状态收尾。

验证：`.venv/Scripts/python.exe -m unittest tests.contracts.test_artifact_store -q`，17 项 PASS（3.735 s）；
真实 spawn 短子进程在写入后/发布前被 terminate，死/活 writer 对照、清单及 SHA-256 不变、无捏造终态、
精确控制释放、再次 reserve、ready 不回退、二次恢复无变化及原 publishing 恢复均通过。
`.venv/Scripts/python.exe -m unittest tests.contracts.test_reference_workflow -v`，5 项 PASS（5.657 s）；
正常发布/失败/取消、queued 准入失败、复用、GC、缺件局部重算接线仍通过。
Store 两个改动文件 Ruff PASS。测试临时根自动清理；未触碰真实研究产物。

剩余旧消费者仍为上文旧 owner/原生链清单，本轮只接入 reference_tracing；
下一步处理同一次运行的 TOML 单次读取，再处理有证据支持的旧资产读取边界。
