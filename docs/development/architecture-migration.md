# 架构迁移执行记录

本页是架构迁移的唯一进度入口；最新接续见文末“批次 B”。批次 A 完成不等于全仓迁移。输入为用户提供的
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
原有未跟踪 `artifacts/` 保留；开工时要求不改历史研究资产、不合并、不推送（后续推送授权见最终交付）。本节是本轮接续入口，
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


### 2. 作者配方单次读取

第 1 项代码/证据已提交 `c656c647`。本单元在现有 `recipes.reference.load_recipe(path)` 中单次
`read_bytes`，用该快照解析十进制 TOML，返回 SimulationRecipe.source_bytes；resolved-only 构造没有来源快照。
`reference_tracing.run_recipe` 用该份字节归档，provenance 哈希来自这份冻结文件，不再重读外部作者路径。
科学身份仍来自原 resolved 投影，来源字节不进入 task key；label-only 仍命中科学缓存。

`.venv/Scripts/python.exe -m unittest tests.contracts.test_reference_recipe tests.contracts.test_reference_workflow -v`：
12 项 PASS（6.794 s），其中可控 read_bytes hook 在首次外部读取后将 E 从 2000 改为 4000 V/m，
确认首次只读一次且计算/归档/来源 SHA 全为旧值；下一次运行才使用新值。
两次轨迹事件均由独立匀加速公式核对（位置误差 <1e-10 m），后次实际更早到达，场缓存正确失效。
Ruff 四个改动 Python 文件 PASS，diff --check PASS。
已增强原安装验收的参考片段，核对 installed CLI 的 author/resolved/provenance 与来源字节，
并输出数值误差；直接 wheel 和 sdist 重建 wheel 的离仓验收留到第 3 项之后、同一最终代码提交运行。

剩余旧消费者与上文清单相同；下一步只做已取证的历史 common_ground 读取边界修复，不启动 B。


### 3. 历史 common_ground：已修并复验

第 2 项代码/证据提交 `55144d39`。旧基线的 KeyError 仍是原始失败事实；本轮新增的技术选择是：
仅在 `backends/comsol/paired_static_model.py` 的旧资产读取边界，按嵌套 composition plan 3
解释六键 renderer 绑定，现行 plan 5 保持规范角色；外层 plan 2 本身不能区分格式。
映射依据为现有 `backends/simion/tof_electrode_mapping.py` 的版本化前端协议与冻结 electrical ON 表，
grid2 明确为 exit grid，不是第二中间网格。仅适用 three_zone_square 的 OA-only 域，
不宣称整个装配 ground 等价，不支持无证据的 plan 4。

源 plan 和 export consumer plan 即使无 expected_plan 也校验：五角色、接地、环 ID 顺序/长度、
唯一正整数、完整有限电压与冻结 electrical 严格一致。缺字段、新旧混合、角色冲突、环列表不匹配、
未知版本均拒绝。新 writer 未增加旧格式，不改历史 manifest，不放宽物理校验，不恢复旧生产框架。

5 项定向测试 PASS（7.447 s）：新旧等价/拒绝夹具、原 saved-model BVP 测试、
`PairedPulsePreparationTests.test_actual_110745_all_100_states_use_original_235338_common_field`、
export-only 及平铺来源漂移。原失败方法现通过，100 个原始状态完整绑定原 235338 公共场；
测试禁止读取 MPH/PA，未运行 COMSOL/SIMION。改动文件 Ruff 和 diff --check PASS。
历史小证据复验 SHA-256 未变：235338 manifest
`10862ABF99C5D20A094E6FE40277D81D115059153F4FCE9D6E3DECAC1EAECE83`，plan
`26EDF6019898507E5A74C3792AF465FB3096816893F07AF1D70D2336E13EA49D`。

原 Owner-02 失败报告保留，本轮定向通过不能改写为完整 Owner 门禁通过。
剩余 P4 与旧消费者仍按原清单；B 前不再受该已复现 KeyError 阻塞。
下一步仅在固定最终代码提交运行两发行离仓参考链，再登记结果与 CLOC。


### 4. 最终代码与离仓交付

最终代码提交 `991feedb805fc8278394fc5cc036983c162601cf`，此前两个独立修复提交为
`c656c647`、`55144d39`。随后用户明确授权“从现在开始远端一直保持和本地一致”；
三个修复提交已普通推送到同名 origin 任务分支，远端 SHA 与本地代码 SHA 相同。
本节为后续纯证据文档提交，不改变通过验收的代码；完成后同样普通推送。
未合并 master、未改写远端历史。开工与验收结束的已有未跟踪 `artifacts/` 保持不动。

| 验证 | 结果 | 判据与范围 |
|---|---|---|
| Store | 17 PASS，3.735 s | 真实强杀、活进程、ready、控制释放、重复恢复、publishing 恢复 |
| 配方/参考 workflow | 12 PASS，6.794 s | 单次外部读取、突变后当前/下次隔离、独立匀加速 oracle、原正反例 |
| 历史 OA reader | 5 PASS，7.447 s | 新旧等价/拒绝、原 110745/235338 方法、saved model/export/flat provenance |
| 最终两发行离仓参考验收 | PASS，346.964 s | 同一代码提交的直接 wheel、sdist 重建 wheel；普通安装，非 editable |
| Ruff / staged 开发标准 / diff --check | PASS | 实际改动范围；不代替完整 Owner/P4 或科学资格 |

直接 wheel run `bf126413427e49b096e094c68ed4b397`；sdist 重建 wheel run
`f0855480c289496b80c020bcaac2b15e`。两臂均 N=1、detected=1、101 样本，succeeded + complete，
公共 CLI 冷读统计一致、第二次运行场和批次实际复用，author/resolved/provenance 对账通过。
共同作者 SHA-256 为 `D8CC1F3B06C0F394D04D110591AB806166176E6904953584406A010CEF97CD1F`。
事件时间均 `9.185857056658535e-7 s`；独立匀加速解析解事件误差 `1.1540919197546408e-16 s`，
轨迹最大位置误差 `8.673617379884035e-18 m`（既有判据分别 <5e-15 s、<1e-10 m，未放宽）。
源树离线、已安装模块 origin、清除 PYTHONPATH/PYTHONHOME、隔离解释器均通过；
HEAD/index/status 和 3206 文件清单不变，清单 SHA-256
`d94593eec2bd34a7d60b4f7c0ba8daa33eb8b7d99bd6bfb5f23b0fbf6eec1003`。

实际运行的复现入口（仓库根、锁定环境；安装验收内部在仓库外执行公共 CLI/API）：

```powershell
.venv/Scripts/python.exe -m unittest tests.contracts.test_artifact_store -q
.venv/Scripts/python.exe -m unittest tests.contracts.test_reference_recipe tests.contracts.test_reference_workflow -v
$readerTests = @(
  'tests.workflows.paired_accelerator.test_paired_accelerator_static_field_execute.PairedStaticExecutionTests.test_versioned_oa_voltage_projection_rejects_ambiguous_inputs',
  'tests.workflows.paired_accelerator.test_paired_accelerator_static_field_execute.PairedStaticExecutionTests.test_saved_solution_requires_bound_completion_bvp_and_backend',
  'tests.workflows.paired_accelerator.test_paired_accelerator_pulse_preparation.PairedPulsePreparationTests.test_actual_110745_all_100_states_use_original_235338_common_field',
  'tests.workflows.paired_accelerator.test_paired_accelerator_pulse_preparation.PairedPulsePreparationTests.test_export_only_source_flattens_original_model_and_binds_own_simion_plan',
  'tests.workflows.paired_accelerator.test_paired_accelerator_pulse_preparation.PairedPulsePreparationTests.test_export_source_rejects_bvp_or_flat_origin_drift'
)
.venv/Scripts/python.exe -m unittest @readerTests -v
.venv/Scripts/python.exe -m unittest tests.contracts.test_installed_scientific_core.InstalledScientificCoreTests.verify_reference_delivery -v
```

测试保留证据位于主机 Git 树外 `msplatform-artifacts/architecture-a-closeout-20261126/`：
`991feedb-installed.log`、`991feedb-cloc.log`、`991feedb-verification.json` 和
`991feedb-acceptance/acceptance.json`（含来源清单与三个发行文件摘要）。
临时安装工作区 `installed-scientific-core-yxmty_pg` 已由测试正常清理，可由上述入口重建；
释放字节数未测量。此前 A 独立交付环境及真实研究产物未清理。

本轮第 1、2 项验收完成，第 3 项为**已修并复验**。未执行完整 Changed/Owner/Repository/P4，
未重跑无关门禁、大型模拟、商业求解、GUI/CAD或 Formal 验证；原失败记录与其他 P4 残项保留。
剩余旧消费者和 B/C 入口仍见上文“活动旧消费者与退役入口”，M06–M08 未开始。
本轮三项没有未决实施选择；B 开工仍须另行授权，沿执行包既定默认方案和上述真实消费者清单推进。
若 B 将引入 queued 重新派发或原生后代执行，须在那个边界先处理相应合同：
当前 writer 登记后、mark_running 前被杀仍属 queued，旧 writer 行不会被本恢复入口清理并续用；
没有 writer token 的历史 running 也不能据 PID/超时自动判死。原生消费者须各自持权，
不能外推当前同步参考进程的锁保护。`recover_publications` 仍要求管理员确认 writer 停止并独占操作。

### 本轮 CLOC 对账

CLOC 2.10：`dad49d1c9049a5c3ba349003af4998d50ec9082e` →
`991feedb805fc8278394fc5cc036983c162601cf`。证据文档提交只改 Markdown，代码计数不变。
实际命令（LC_ALL/LC_CTYPE/LANG=C）：

```powershell
tools/repository/report_cloc_delta.ps1 -Base dad49d1c9049a5c3ba349003af4998d50ec9082e -Current 991feedb805fc8278394fc5cc036983c162601cf -ClocExe <workspace>/.tools/cloc/2.10/cloc.exe
```

原工具 CLOC_DELTA=PASS；未分类 0。每格为 baseline → result (delta)，数值直接格式化自原工具，不另行计行。

| Scope | Language | Files | Blank | Comment | Code |
|---|---|---:|---:|---:|---:|
| total | JSON | 282 → 282 (0) | 0 → 0 (0) | 0 → 0 (0) | 126022 → 126022 (0) |
| total | Lua | 119 → 119 (0) | 413 → 413 (0) | 828 → 828 (0) | 13219 → 13219 (0) |
| total | MATLAB | 186 → 186 (0) | 1066 → 1066 (0) | 2053 → 2053 (0) | 19701 → 19701 (0) |
| total | PowerShell | 150 → 150 (0) | 1100 → 1100 (0) | 1195 → 1195 (0) | 46113 → 46113 (0) |
| total | Python | 1435 → 1435 (0) | 32905 → 32921 (16) | 42461 → 42493 (32) | 396011 → 396258 (247) |
| total | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 51 → 51 (0) | 214 → 214 (0) |
| total | TOML | 5 → 5 (0) | 43 → 43 (0) | 2 → 2 (0) | 219 → 219 (0) |
| total | YAML | 2 → 2 (0) | 8 → 8 (0) | 20 → 20 (0) | 506 → 506 (0) |
| total | SUM | 2189 → 2189 (0) | 35561 → 35577 (16) | 46610 → 46642 (32) | 602005 → 602252 (247) |
| production | JSON | 259 → 259 (0) | 0 → 0 (0) | 0 → 0 (0) | 42340 → 42340 (0) |
| production | Lua | 99 → 99 (0) | 333 → 333 (0) | 703 → 703 (0) | 11141 → 11141 (0) |
| production | MATLAB | 118 → 118 (0) | 526 → 526 (0) | 1462 → 1462 (0) | 12164 → 12164 (0) |
| production | PowerShell | 138 → 138 (0) | 1037 → 1037 (0) | 1149 → 1149 (0) | 44012 → 44012 (0) |
| production | Python | 685 → 685 (0) | 16796 → 16804 (8) | 11588 → 11609 (21) | 182893 → 182981 (88) |
| production | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 51 → 51 (0) | 214 → 214 (0) |
| production | TOML | 5 → 5 (0) | 43 → 43 (0) | 2 → 2 (0) | 219 → 219 (0) |
| production | YAML | 2 → 2 (0) | 8 → 8 (0) | 20 → 20 (0) | 506 → 506 (0) |
| production | SUM | 1316 → 1316 (0) | 18769 → 18777 (8) | 14975 → 14996 (21) | 293489 → 293577 (88) |
| tests | JSON | 23 → 23 (0) | 0 → 0 (0) | 0 → 0 (0) | 83682 → 83682 (0) |
| tests | Lua | 20 → 20 (0) | 80 → 80 (0) | 125 → 125 (0) | 2078 → 2078 (0) |
| tests | MATLAB | 68 → 68 (0) | 540 → 540 (0) | 591 → 591 (0) | 7537 → 7537 (0) |
| tests | PowerShell | 12 → 12 (0) | 63 → 63 (0) | 46 → 46 (0) | 2101 → 2101 (0) |
| tests | Python | 750 → 750 (0) | 16109 → 16117 (8) | 30873 → 30884 (11) | 213118 → 213277 (159) |
| tests | SUM | 873 → 873 (0) | 16792 → 16800 (8) | 31635 → 31646 (11) | 308516 → 308675 (159) |

完整过滤口径：

```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|tests/**/__init__.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```


## 批次 B（2026-11-27）：B0–B6 同一 Goal 连续实施

### 开工与输入

用户明确启动批次 B。开工 HEAD `a9d76aa4dcdbaf8099c9ce5aa0585d6fce18c3be` 与 B 执行包审计一致，
无相关后续增量；任务分支 `task/architecture-migration-20261126` 跟踪同名 origin，远端同步授权继续。
只有原有未跟踪 `artifacts/`，保留不动。禁止 reset、主线合并和历史改写。

已按顺序读取外部 `ms_phase_b_execution_20261126/start_agent_B.md`、acceptance_report_A.md、
implementation_plan_B.md、verification_evidence.json，再读 goal_prompt_B.md；证据索引全部文件大小/哈希核对通过。
只创建一个 active Goal：完整 goal_prompt_B 原文加完整计划路径绑定；工具目标字段最多4000字符，
15181字符的完整计划不能直接拼入目标字段，已全文读取且 B0–B6/BA01–BA15 全范围适用，不削减任务。
Goal与执行提示词是同一项工作；不只完成B0就结束，不自动加入C/M06–M08。

| 外部输入 | SHA-256 |
|---|---|
| start_agent_B.md | 6dff4ab3eea14aa574dc8372178ea47401ddc7e72fa3ce7f4df187bdeabc3664 |
| goal_prompt_B.md | 19a71f5ddbecc040f3da92fc6067f0e2ad7370db77818607a715b175b8235733 |
| implementation_plan_B.md | 102488c5782cde85e0068b0851e76ed77c4072185d3693565085519bffc6ddb7 |
| acceptance_report_A.md | 62d592da32ed98fbc9885125ffdf129d04555ef32235f35ac62e49c24f579fb8 |
| verification_evidence.json | d16c619816445cea65e2b8a6d03e73451abcf762a250a2de05c0f065732ba62b |

A独立审计的37 unittest/36 PASS/1 Linux junction SKIP及四个B0反例是输入事实，不能当本轮修复PASS。
原三项A收尾已经解决，不重新立项；原评阅状态与本轮技术选择分别保留。

Agent 0：Goal、公共合同/CLI/workflow整合、迁移记录、Git串行与最终验收；
Agent 1：B0电荷/共面终止面；Agent 2：B0干净构建说明；Agent 3：B0存储；
Agent 4：只读B2/原生移植闭包。共同文件均明确唯一写入者；原生资源执行统一协调。

### B0-03：失败 GC 候选不阻塞后续准入

已实现 `storage/store.py:collect` 单次pass冻结候选身份，每个候选最多尝试一次；pending优先，
ready转pending仍在短事务复核pin/claim/必要引用。失败保留delete_pending与原因、不虚计释放、继续其他候选。
`reserve` 继续在回收后重读实际free决定准入；没有新GC或账本。

`.venv/Scripts/python.exe -m unittest tests.contracts.test_artifact_store -q`：19 PASS（4.584 s）。
新增可控 A删除失败/B足量成功后准入、pin/claim保护、全部失败每轮只尝试一次且零释放。
free是受控观测（0→6 B，准入需求5 B），不是对真实卷释放量的测量。原writer/publishing恢复仍通过。
对应两文件Ruff PASS。临时夹具自动清理，没有删除真实研究数据。

剩余：B0-01/02/04正在独立实施；之后立即进入B1公共合同、B2拆分/B3场源、B4原生链、B5 mass_scan、
B6旧执行退役/交付。当前旧消费者清单仍见上文，不声称B或BA01完成。CLOC将在该主题提交后按实际SHA核对。


### B0-01/02：电荷精确表示归一和共面竞争

已复核 `physics.normalize_charge_c`：保留既有binary64整数×e规范值和科学身份，精确接受该表示或
同一冻结十进制常量精确相乘后一次舍入的表示，不采用通用ULP窗口/相对容差。
±3的作者辅助charge_c=±4.806529902e-19 C归一到旧规范值±4.806529901999999e-19 C；
常量数值未升级，真实矛盾拒绝。author/resolved/tracer使用同一函数，实际输出初态采用规范值。

`tracing.preflight` 拒绝相同axis/精确位置的竞争终止面，与声明顺序无关；共面observation合法。
求解前将非终止observation排在terminal前，确保同根处的合法观测不会被终止截掉，两种作者顺序均验证。
不扩展为任意三维角点/切触算法改写；CLI validate/run均在昂贵执行前走同一预检。

`.venv/Scripts/python.exe -m unittest tests.contracts.test_reference_recipe tests.contracts.test_reference_tracing tests.contracts.test_reference_workflow -v`：
20 PASS；±1/±3的author/resolved/tracer/output，真实矛盾、竞争两顺序、合法观测两顺序及原参考闭环均通过。
Ruff与diff --check PASS。初版测试曾误认为terminal具有charge_c而得到4个KeyError，已按实际合同
核对initial电荷与终态一致性后通过，初版错误不作为生产失败或PASS。旧审计探针只作观察，不代替回归。
tracer实现摘要改变已进入现有批缓存键；物理规范值和版本化常量保持不变。

B0-03已提交/推送 `0873971a`；B0-04干净构建正在验证独立backend进程的可靠命令，尚未计通过。
下一步立即推进B1的既有Study/Assembly接线；B2只读闭包已确认OA本来只复用一次，不能重写第三套OA。


### B0-04：干净构建说明已验证；B0退出

`docs/TRACING.md` 改为固定已提交快照的git archive、干净Python3.11 venv、pyproject声明的
setuptools65.5.0/wheel0.38.4，并分别在两个独立Python backend进程构建wheel和sdist。
不再假定锁文件安装了build frontend。固定源 `a9d76aa4` 干净构建PASS：wheel5706249 B、
sdist4851908 B；主机小证据 `.tools/b0-04-build-evidence-20261127/build-evidence.json` 含来源/版本/摘要。
初次同进程连续调用退出0却将sdist写入source/bdist_wheel，已纠正文档并用全新快照重验；
初次部分构建不作为PASS。此项仅构建可复制性验证，不冒充本轮最终安装/native验收。

自动批准审查拒绝递归清理本次临时目录 `msplatform-b0-04-997974f7bbbc433abe14f3264bc55430`，
仅报告blocked by policy，无更具体原因；没有重试或换方式绕过。约1081448135 B逻辑文件仍保留，
未声称释放；都是本次可重建源码/venv/发行产物，不涉及既有研究数据。清理限制不是B原生资格PASS。

B0-01/02已提交/推送 `f0febc9e`；四项B0现在闭合，BA01只声明其实际验收范围。
B1共同合同沿现有StudyDefinition(component_requests/recipe/drive/physics/release/numerics)、
components.resolve_component和assembly.assemble，不另造第二Study/Assembly或CLI。
同一load_recipe将以版本化native作者配置绑定完整自包含Study JSON的path+SHA，单次读字节、冻结/归档依赖；
运行时不重读可变科学源。预检区分实现/主机/证据，不以parse成功代替native支持。

B2取证已确认实际仪器OA开口与standalone第一隙约束不同，必须由OA owner表达受验证的仪器机械输入；
OA↔下游连接须由真实端面/开口和位姿推导验证，不能伪造port、空连接或按同电位合并ground身份。
剩余旧消费者与原清单一致，B1–B6/BA02–BA15均在推进、尚未验收；下一步公共配方和独立组件合同。


### B1/B2 首个实体单元：版本化包含关系与真正下游 provider

已实现 `assembly/containment.py`、recipe2/plan6和interface4；旧recipe1/plan3–5、interface1–3原义保留。
ports为空只用于没有实际机械对接面的新接口；显式containment把实际成员AABB经刚体变换核验到
provider派生圆柱包络内，检查关系唯一/无环/连通和scope边界，不伪造端口/接触面。
`assembly/electrode_binding.py` 已允许group身份相同的interface3/4，仍以instance+group为唯一科学键，
OA ground与下游ground不合并。包络只证明包含，不表示无障碍、joint field正确或native资格。

独立 `components/single_reflection_tof` 只拥有飞管、双级reflectron与detector的真实下游输入；
下游公式从旧geometry_contract真实提取，旧复合reader委托同一owner，未复制第二套活跃物理公式。
OA仪器机械输入复用已存在的受版本/producer/壁开口校验的instrument投影，原standalone第一隙校验未放宽。
source→resolved→interface独立重算，伪造bounds拒绝。registry/依赖图/source_closure已同步。

独立oracle来自 `d55198ff7b4387ba54807906a23b96cd2c5bcb88` 的原geometry_contract源码，
源SHA256 `0b28054be43cd0b98feacfa01efd3c7b136873654a89bb641975c7d553c091c6`，
冻结于 `tests/contracts/fixtures/split_tof_legacy_projection.json`，非新实现自比。
45条电极完整属性/电压、detector面及局部范围逐值相等。原已有detector/OA屏蔽重叠
在点 `[58,0,-0.5] mm` 精确查询均interior；保持原几何，限制已写新组件PROJECT，未宣称无碰撞。

最终本单元命令：`.venv/Scripts/python.exe -m unittest tests.contracts.test_split_tof_provider
 tests.assembly.test_containment_layout tests.contracts.test_geometry_members
 tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_installed_geometry_provider
 tests.components.orthogonal_accelerator.analysis.test_bare_three_zone_component -q`：30 PASS（4.405 s）。
原assembly22项先前PASS；独立5项containment含变换/负例/版本隔离/电极scope。
对应生产/测试Ruff PASS。Agent5只读复核发现的v4电极绑定缺口和原同实现自比夹具均已修复。
B1配方/结果/native保护桥仍为未提交的独立单元，不把它们夹进本主题；真正compiler/source/drive/native
消费者闭包和BA03/04整体验收尚未结束。

主机工具预检：首次未提供Python选择而启动拒绝（不是工具/物理失败）；随后
`$env:SIMULATION_PYTHON_EXE=(Resolve-Path .venv/Scripts/python.exe).Path;
 pwsh -NoProfile -File tools/repository/verify_toolchain.ps1 -SkipSolidWorksProbe`
PASS，实际MATLAB R2025b探测True；SolidWorks文件基线检查、COM运行探测SKIPPED，未做CAD/GUI资格。
后续COMSOL仍须正式6.4/R2025b launcher与实际资源准入。

剩余：SIMION完整frontend/prepared/track正在迁移，三格native均未验证；COMSOL既有全仪器CPT为static ON，
OA-only gate不可套整仪器关掉常开反射场。新路径必须同模型保存OFF/ON两解，再组合背景+OA脉冲差场；
不能把独立MPH的withsol引用误当共同解，也不能用reader fixture冒充原生完成。B4实际host与Store prelaunch
接线、B5 mass_scan、B6旧执行退役继续，不停止Goal。


### B4 结果格式单元：原生出生与旧初态快照分开

`results/model.py:TraceResult` 成为同一 solver-neutral 结果对象；`tracing.TraceResult` 保持同一公开对象。
`results/particle_data.py` 增加显式 schema2/native_birth_verified，初态 primary_birth 与 schema1 的
unavailable_initial_snapshot 分离；没有把旧快照升级成出生证据。Parquet/HDF5/execution 的版本、frame、
clock、出生依据交叉核验；次级谱系仍明确不支持。真实出生须由各 native adapter 从实际初始化记录核验，
reader fixture 的显式标记不是原生资格。

定向命令 `.venv/Scripts/python.exe -m unittest tests.contracts.test_native_particle_data
 tests.contracts.test_reference_workflow tests.contracts.test_reference_tracing tests.contracts.test_native_recipe
 tests.contracts.test_reference_recipe -q`：27 PASS（10.717 s），包括合成schema2读写/篡改负例及原参考链。
本次结果主题只提交结果对象/格式、原公开重导出和相应边界声明；配方/后端/保护桥继续独立实施。
B3/4三格原生仍未执行，不把格式往返计为BA08。下一步接实际源/终态与同一公共CLI。

Agent3已修复尚未提交的native完成回执过早删除活holder控制问题，继续真实process-owner prelaunch绑定。
其临时测试目录 `C:/Users/Liao/AppData/Local/Temp/tmphou0uqsj` 清理同样被自动批准审查拒绝，仅有blocked
by policy，已停止重试；未声称释放容量。保留已知窗口的保守保护，不用裸PID/超时自动释放。


### B1 配方冻结单元

结果格式主题已提交/推送 `19c2d0ce`。`recipes/reference.py:load_recipe` 同一入口新增schema2 native作者配置，
`recipes/native.py` 只读一次显式path+SHA绑定的完整Study JSON；resolved内嵌原字节和来源哈希，并冻结小型clock/epoch资源。
validate仅从冻结bytes重编译现有components.resolve_component/assembly.assemble，不重读可变科学源。
assembly可读名由同一assembly_name生成器生成，名称、内容assembly_id和recipe_id分别表达；作者label/来源路径不入科学身份。
常量版本与vacuum在作者输入显式选择，resolved冻结public constants/gas dataset；不支持旧常量隐式升级、碰撞或自洽。
COMSOL数值采用其真实CPT控制maximum_step_us/relative_tolerance/absolute_tolerance，非把采样输出间隔冒作积分步长。

定向 `.venv/Scripts/python.exe -m unittest tests.contracts.test_native_recipe tests.contracts.test_reference_recipe -q`，
以及对应Ruff通过；此前结果/配方/reference联合27项PASS（10.717s），加入公共入口声明后boundary等27项PASS（18.904s）。
测试覆盖外部Study一次读取/变更后本run不变、SHA/冻结内容篡改拒绝、label/path身份稳定、缺显式数值/clock/源拒绝。
这里只交付解析冻结，不把parse成功当native支持；公共capability报告、真正运行、三组合新证据仍在整合。

旧消费者：原复合OA–TOF公开native入口的跨组件HandoffResult/state_relaunch/segmented_upstream仍需合并本轮守卫；
IP–MR及其他C链的合法续传和历史reader不全局禁用。下一步合并独立编译、实际birth源示例及同一CLI执行。


### B2/B3/B4 SIMION 软件消费者闭包与原始出生

配方冻结主题已提交/推送 `1d12e480`。分体模型现在由 `backends/simion/split_compiler.py` 编译，
`operations.build_geometry/prepare_model/solve_fields` 复用既有owner，`fields/native_plans/field_execution`
按真实独立OA/RF/TOF实例准备carrier_off、可选rf_reference和pulse_delta；同一parent域中的真实电极见证、
下游3PA优先级/电压/探测器面保持。原parent域z_max的5.7e-14 mm舍入差采用既有32ULP边界规则，
原118×76×3201网格不变，实际缩域0.1mm仍拒绝。包络及准备通过不是joint场/无碰撞资格。

`tracking_execution/program/collection` 消费独立组件与实际首个RF（无RF时OA）的原birth和真实位姿；
保留全局实验时间，不在OA重新释放。旧复合与新split真实OA–TOF scope均拒绝HandoffResult（空也拒）、
state_relaunch及segmented_upstream；独立RF和C的IP–MR合法续传不变。统一结果适配在实际collection后，
从initialize/terminate/有限圆面观测核验原始ID/6D/记录；未证明detector面交叉不冒充detected，缺件明确incomplete。
trajectory product声明5个schema2科学数据文件，版本证据取实际Windows executable固定资源并核对文件身份。

官方依据：SIMION [global segment](https://simion.com/info/workbench_program_extensions.html#sim-segment-global)、
[time](https://simion.com/info/time.html)、[roadmap](https://simion.com/info/roadmap.html)，2026-11-27查阅，
本机8.2.0.11；ion_time_of_flight包含TOB，age另减birth，不能再次加birth；segment_global适用8.2。
此次仍未执行SIMION Refine/Fly，Lua/合成日志只证明声明的软件边界。

`ion_release/dotnet_box.py` 注册box策略并直接复用旧唯一 .NET RNG/ION11 generator；保留.8E实际输入精度，
原generator文件未改。显式选择public u/e转换为canonical速度，尚未证明与SIMION initialize速度等值；
旧OA兼容u和旧COMSOL舍入e没有偷偷替换为新值。两/三组件作者例已冻结原几何、域/网格、V(t)、clock；
OA N=3是原算法N1000的确定前缀，原ION11三行CRLF SHA256 47dead2ebc4d21dfd87244bbc3c24baa1ea22ecdd0e63f16d620594c5cb5a757；
RF N=3为原100母群前缀。小N与新组合是本轮技术选择，不是原评阅批准或旧native资格。

本单元联合 `.venv/Scripts/python.exe -m unittest tests.contracts.test_split_tof_simion
 tests.contracts.test_split_tof_tracking tests.contracts.test_simion_particle_data
 tests.contracts.test_split_native_example tests.contracts.test_native_workflow -q`：20 PASS（6.291s）；
其中native_workflow公共入口尚为独立未提交整合，其他17项验证本主题的软件入口与负例。
对应生产/测试Ruff PASS；旧ION11四项PASS，原SIMION compiler/native-plan兼容15项曾PASS。
未启动商业软件，不把上述结果计为BA06/08/09整体验收。

实际COMSOL独立几何候选已由正式6.4/R2025b launcher完成build+冷开+owner发布：run_id
`20261127_012417__build__comsol__geometry-b9b8d5258ade`，manifest SHA256
50948D07CCD42623117A05AAB9CBD6D51EAB7D4A457B7E39B0F17413224FE4A5；来自冻结的WORKTREE源，
不伪称HEAD已验证。45 member/43电压group/5理想片；未求场、未CPT，owned_scope_unknown资源观测警告保留。
源记录位于本轮原生owner run。后续提交冻结后需按实际影响复验。

下一步B4：先补实际旧载荷跨阶段及原生后代防删保护，再启动SIMION公共链；原TTL/terminal读锁不能独自证明GC安全。
B5 mass_scan纯原语已测试，公共多物种执行仍未接入；COMSOL三格新求场/飞行与普通安装仍未完成。


### B 累计 CLOC（至SIMION软件闭包）
CLOC 2.10：`a9d76aa4dcdbaf8099c9ce5aa0585d6fce18c3be` → `7091001768b8852f687af5b99b5d8fd4e358d3a6`，PASS，unclassified=0。
实际命令：`tools/repository/report_cloc_delta.ps1 -Base a9d76aa4dcdbaf8099c9ce5aa0585d6fce18c3be -Current 70910017 -ClocExe C:/Users/Liao/mass_spectrometry/.tools/cloc/2.10/cloc.exe`；LC_ALL/LC_CTYPE/LANG=C。
结果来自指定提交；执行时WORKTREE有并行未提交改动，未将其计入指定SHA。表格直接格式化工具输出。

| Scope | Language | Files | Blank | Comment | Code |
|---|---|---:|---:|---:|---:|
| total | JSON | 282 → 288 (6) | 0 → 0 (0) | 0 → 0 (0) | 126022 → 129000 (2978) |
| total | Lua | 119 → 119 (0) | 413 → 413 (0) | 828 → 828 (0) | 13219 → 13219 (0) |
| total | MATLAB | 186 → 186 (0) | 1066 → 1066 (0) | 2053 → 2053 (0) | 19701 → 19701 (0) |
| total | PowerShell | 150 → 150 (0) | 1100 → 1100 (0) | 1195 → 1195 (0) | 46113 → 46113 (0) |
| total | Python | 1435 → 1456 (21) | 32921 → 33131 (210) | 42493 → 42597 (104) | 396258 → 398704 (2446) |
| total | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 51 → 51 (0) | 214 → 214 (0) |
| total | TOML | 5 → 7 (2) | 43 → 45 (2) | 2 → 2 (0) | 219 → 251 (32) |
| total | YAML | 2 → 2 (0) | 8 → 8 (0) | 20 → 20 (0) | 506 → 506 (0) |
| total | SUM | 2189 → 2218 (29) | 35577 → 35789 (212) | 46642 → 46746 (104) | 602252 → 607708 (5456) |
| production | JSON | 259 → 264 (5) | 0 → 0 (0) | 0 → 0 (0) | 42340 → 44385 (2045) |
| production | Lua | 99 → 99 (0) | 333 → 333 (0) | 703 → 703 (0) | 11141 → 11141 (0) |
| production | MATLAB | 118 → 118 (0) | 526 → 526 (0) | 1462 → 1462 (0) | 12164 → 12164 (0) |
| production | PowerShell | 138 → 138 (0) | 1037 → 1037 (0) | 1149 → 1149 (0) | 44012 → 44012 (0) |
| production | Python | 685 → 698 (13) | 16804 → 16929 (125) | 11609 → 11668 (59) | 182981 → 184350 (1369) |
| production | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 51 → 51 (0) | 214 → 214 (0) |
| production | TOML | 5 → 7 (2) | 43 → 45 (2) | 2 → 2 (0) | 219 → 251 (32) |
| production | YAML | 2 → 2 (0) | 8 → 8 (0) | 20 → 20 (0) | 506 → 506 (0) |
| production | SUM | 1316 → 1336 (20) | 18777 → 18904 (127) | 14996 → 15055 (59) | 293577 → 297023 (3446) |
| tests | JSON | 23 → 24 (1) | 0 → 0 (0) | 0 → 0 (0) | 83682 → 84615 (933) |
| tests | Lua | 20 → 20 (0) | 80 → 80 (0) | 125 → 125 (0) | 2078 → 2078 (0) |
| tests | MATLAB | 68 → 68 (0) | 540 → 540 (0) | 591 → 591 (0) | 7537 → 7537 (0) |
| tests | PowerShell | 12 → 12 (0) | 63 → 63 (0) | 46 → 46 (0) | 2101 → 2101 (0) |
| tests | Python | 750 → 758 (8) | 16117 → 16202 (85) | 30884 → 30929 (45) | 213277 → 214354 (1077) |
| tests | SUM | 873 → 882 (9) | 16800 → 16885 (85) | 31646 → 31691 (45) | 308675 → 310685 (2010) |

完整过滤口径：

```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|tests/**/__init__.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```
classifier SHA256=d3abfc94e920066445561b696c76131b43eab9713a0cbcb9e2c1270ba7136952；language definition SHA256=985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6。
日志存本轮外部证据根 `70910017-cloc.log`。后续native生命周期/公共运行/COMSOL主题尚未计入，最终交付按最终实际SHA再累计。


### B4 跨阶段原生资产读取保护

`execution/native_source_guard.py:guard_native_source` 按显式真实owner root和expected_kind，
在既有terminal共享锁/容量decision锁的建立窗口冷读原manifest与owner，再对manifest/run_config/产品data逐文件
使用既有guarded_file_identity，持防写/防删OS句柄至context退出；不引入第二GC/TTL租约，也不接管旧payload删除权。
terminal共享锁本身不能挡旧GC：已真实子进程证明同时仍可取capacity decision锁；不能误称它是PA保护。
正常跨阶段保护与native后代保护不同，后者仍需PS owner自行持有完整不可变输入句柄。
既有source lease仍避免账本先标pending的管理争用，遇pending不猜测修账，失败关闭或按原owner重算。

`.venv/Scripts/python.exe -m unittest tests.execution.test_native_source_guard -q` 两项PASS；
真实Windows小fixture子进程对manifest/run_config/payload写入/删除，以及原remove_recorded_files删除均被拒绝，
context退出后允许；错root/kind/散列拒绝。生产/测试Ruff PASS。
加入公共workflow/mass_scan/reference定向联合18项PASS（11.248s），仍无商业工具调用。
helper首次保护包含原reader与guard的两次大文件hash，尚未测性能，未为优化放松信任边界。
下一步同一CLI运行将持此guard直到下游接管和SI结果复制完成；原native子进程持权接线由Agent3继续独立验证。


### B5 物种母群与归并单元（公共原生执行仍在整合）

`workflows/mass_scan.py` 复用唯一sample_release：canonical_mass_scan_request仅组合非空species_requests，
质量/电荷/N/分布仍来自各原release_spec，不复制第二套物种权威。物种唯一，同epoch，显式粒子ID全局唯一；
缺省/None ID按物种顺序避开所有显式ID确定分配，权重局部映射冻结为全局映射，样本N与物理权重分开。
`recipes/native.py` 同Study release入口接受该版本化集合，每个源/clock/显式控制分别校验；
COMSOL原生出生比较的SI容差必须作者显式声明，不用输出采样间隔替代积分控制。

merge_mass_scan只归并已成功完整批、保留真实ID与各6D/事件/轨迹，拒绝缺终态/外来身份/重复/混合谱系；
analyze_mass_scan独立报告各species原始和加权检测率，0-hit和1-hit可作为完整科学负结果，
峰统计/标定不足给not_applicable，不将分析准入倒灌成追踪失败，也未假称实际拟合已执行。
实际失败/缺件不能用零命中掩盖。各批frame/clock由运行owner在归并前验证，TraceResult本身没有伪造元数据。

mass_scan定向5项及Ruff PASS，含单物种、不等N、同mass +1/+2、权重、null/显式ID、混合clock、
0/1-hit、缺件/重复与schema2冷读；native_recipe+native_workflow联合16项PASS（5.622s）。
其中nativeworkflow新公共调度仍未提交，本主题软件原语不代表真实+1/+2原生完成或BA12全通过。
下步同一run_recipe按物种完整批运行，共享实际场依赖、缺批局部重算，之后以真实小N+1/+2闭合。

COMSOL后续工程probe（WORKTREE源）固定几何/5mm mesh实际6,277,920元素；已知5m工程守卫在求场前拒绝，
run `20261127_013605__sim__comsol__pulse-basis-baa1c658928b`，peak快照约4,927,029,248 B，
owned_scope_unknown限制仍保留。没有OFF/ON解，没有CPT；mesh元素不是节点或DOF，不拿默认二阶推断冒实测。


### B4 当前接线与原生运行恢复入口（继续Goal）

当前已提交/推送到 `7b48a0fe`，前一读取保护提交为 `d0c7cbbf`，未合并主线。
原有artifacts保留。以下是进行中事实，不作为批次完成：

- Agent3单worker真实host prelaunch ACK/worker登记/持久completion已冻结；父controller被杀仍保护，
  正常/非零退出/登记前死亡/nonce错拒绝均实际小进程测试；新增public recover_controls自动重读原私有work回执，
  recover_interrupted_runs可收尾，坏回执原因可查询且保护保留。Store19 PASS；native首次8/9的唯一错误文案断言已修，
  对该真实10.600s用例单独重验PASS，另一登记前死亡用例PASS，不重复无关完整suite。
  PS现在即便有Python immutable_input_session仍自行持原source防删句柄；真实父死后源PA不能unlink，worker结束后可删。
  sourceguard/前端field精确读输入已补，working/refine私有写目标不误加immutable。
  原生group尚失败关闭，未验group副本留工作区外.tools/native-group-wip-20261127，不能把单worker外推group。
- Agent2/5双基场适配现使用两个真实OFF/ON解，Eoff+gate*(Eon−Eoff)保留常开反射场；共享reader验证同MPH的两个
  独立solution/dataset/request/coldread/mesh/vacuum/真实producer product，18项软件合同PASS。
  五槽世界background PA未闭合，public scalar admission仍拒绝，不让PA联集之外静默零场；Agent4正在复用原neutral机制。
  split模型native_drive_rows的JSON顺序漂移已规范排序并重编译精确等值，尚待独立提交。
- 新native_tracing同一CLI/run_recipe的schema2公共执行仍WORKTREE，单次作者bytes/冻结Study/clock、分阶段Store小引用缓存、
  原owner exact product文件guard、全母群schema2重读、多物种批及分析准入已接，18项workflow/mass/reference/sourceguard联合PASS。
  增强preflight实际走tracking planner，拒绝无RF装配中的RF专属数值；新增cache kind必填/完整性/clock资源/原生资源字节身份。
  新CLI还没有真实完成run，COMSOL helper已新增且正在整合；不宣称BA02/06/09/12/15全通过。
- COMSOL独立几何与未求解模型真实冷开PASS；100万/500万工程mesh上限两次均在Compute前停止，第二次实测6,277,920元素。
  固定5mm网格、阶次/BVP不变的7m上限新run `20261127_014602__sim__comsol__pulse-basis-82a20bcf1fb3` 已通过mesh守卫，
  mesh_facts独立事实文件先关闭保存，仍在求场。最新单点COMSOL14.24GiB/MATLAB1.26GiB/系统可用8.16GiB，接近16GiB树预算，
  原owner保留守卫；曾出现owned_scope_unknown，未证明全程资源观测完备，不扩大预算或伪称求场成功。
  若明确越限且owner未行动，须沿受管取消/drain保留失败；不得裸杀Python后声称native已停。

恢复后先核对上述7m native实际状态/证据与当前Git差异，接Agent3冻结单元、COMSOL公共helper，补完整世界carrier再跑SIMION。
不重新做全仓P4，不重复已完成A/B0，不自动启动C/M06–M08。后续CLOC按实际提交累计（上一完整表至70910017）。


### 预算语义纠正与单worker原生生命周期单元

Agent0此前将16GiB工程工作集观测预算误认为硬停止条件，指示过早结束7m run。
已重新完整核对 DEVELOPMENT_STANDARDS 6节与 REPOSITORY_OPERATIONS 资源观察：预算越限只告警，
健康原生进程应自然完成，只有中央策略确认持续物理危险才可危险停止。原资源代码和期望测试没有改成硬停。
`20261127_014602__sim__comsol__pulse-basis-82a20bcf1fb3` 实际由Agent人为中断，
owner随后确认writers_stopped/正式host release；17,417,613,312B峰值是同时观测值，
但该越工程预算不构成模型/solver失败或发布禁令。旧记录原样保留，不能改写为物理失败或PASS。
本次没有合格field，无CPT；未确认recovery不用于伪checkpoint。纠正性同网格/BVP/阶次/精度新run
`20261127_015508__sim__comsol__pulse-basis-fd136b758ffa` 已启动，不因预算告警/unknown杀健康solver。

本单元实现入口：storage/store.py 的claim_token/bind_native_controls/record_native_worker/complete_native_controls，
execution/native_artifact_controls.py 的scope与真实持久receipt验证，原processes/process_owner/resources以及
RunSession的明确operation_id接线。native启动前原host grant+nonce ACK、启动后登记确切creation identity并ACK；
controller死亡不放行未启动工作，已启动工作保护延续至原owner/drain/非inherited release正式证明。
原work中留host/ACK/worker/receipt事实；public recover_controls/interrupted_runs自动只查已登记私有work并幂等对账，
坏回执不释放、native_recovery_issues可查询。complete不删活holder跨stage控制，holder最终退出/OS token才释放。
没有超时/裸PID失联判死，没有新调度器/daemon/第二资产owner。

PS即便接到Python immutable session，也自行用原Protect-ImmutablePaSource持精确输入防写/防删句柄，
到native后代drain结束才释放；field_worker与field workbench补全既有owner的真实source输入清单。
原始raw/parent保护，工作私有PA保持可写。controller正常跨阶段由已提交guard_native_source补足。

验证：Store19 PASS（5.366s）；native单worker9项首次8 PASS，仅坏nonce文案断言过严失败，
修正后对应真实controller强杀/自动恢复10.600s用例PASS；另一登记前死亡自动恢复已PASS。
此前单worker/Store/原process联合29 PASS（48.538s）、非零exit3真实例13.482s PASS；
最新field输入+session父死源防删+future geometry四项12.235s PASS；相关Ruff PASS。
独立静态审查未发现被guard源PA同阶段原生写回，未把静态审查当Refine/Fly证据。
此前直接field suite无enclosing GATE且文件编辑中得到1 ERROR，不作为当前验收；必要GATE后续相称补跑。

限制：本提交只单worker和原生文件生命周期，scope下group明确未实现，副本保留外层.tools待下一主题；
不是BA09全部闭合。SIMION真实Refine/Fly、COMSOL真field/CPT、wheel/sdist新链离仓仍待完成。

### B 原生求场事实与失败收尾修复（80f0164d → 本主题提交）

纠正性 run `20261127_015508__sim__comsol__pulse-basis-fd136b758ffa` 的 OFF/ON 两次原生
Compute 均实际完成：6,277,920 mesh elements、各9,363,200 DOF，共存 MPH 3,082,205,877 B。
Python 后验拒绝 MATLAB JSON 的精确整数浮点表示 `6.27792E+6`；这不是原生求解失败，原失败 manifest 不改写。
后续恢复只捕获现存输出身份并冷开校验，捕获时点显式记为失败 Python 校验之后；不能倒称旧输出已经发布封存。
工程 BVP 为有限外箱0 V、真空εr=1、mesh auto5/electrode_hmax5 mm，是新增 probe 技术选择，
不是 SIMION Neumann 同边值问题或数值收敛资格。owned_scope_unknown 的观测限制仍保留。

一次恢复因旧 verifier 只接受单 study 而原生退出1；期间 Agent1修改原 action 源，导致最终化又受阻。
这两项诊断均保留。新 owner 修复：确认真实 writer 停止后，源改变成为明确失败事实而不掩盖原异常；
`RunSession.declare_file` 原子保存明确角色日志。`owner.recover_failed_finalization` 只接受该既存
reopen_pulse_basis 失败状态、冻结 action/完整文件角色/配置/真实 process 与 launcher/原 host release 证据，
仍走原 `_finalize`，不运行 action、不启动原生、不产生科学成功产品。缺证据保持保护。
实际35个 run 文件与35个配置输入（20外部）逐项核对后，原 hold 已收尾 failed/complete，
capacity lease 已释放，3.08 GB 源 MPH 未复制或改写；失败终态 manifest SHA256
`2B31B84B149073F0753E277D8D4B96936A822B73C9BE3B83B20EBD4F47E49F38`。

本主题命令：`.venv/Scripts/python.exe -m unittest tests.contracts.test_owner_action_freeze tests.contracts.test_owner_failed_recovery -q`，
11 PASS（9.908 s）；相关 Ruff PASS。覆盖真实动作源改变后的失败关闭和缺件/角色/身份/release 反例，
不将 inert fixture 当成原生求场验证。下一次冷开 run
`20261127_023910__analysis__comsol__basis-recovery-e7a42a44d31e` 正执行0 Compute校验，
整个 action/native/owner 闭包保持冻结直到最终化返回；尚未宣称该次成功或 basis 合格。

当前 HEAD 在本主题前为80f0164d，任务跟踪分支普通推送同步；原有 artifacts 与所有其他并行改动保留。
剩余旧消费者：旧复合新执行入口退役、plan6 recorded-birth 读取与准备仍在定向迁移；
SIMION Refine/Fly、COMSOL CPT、桥接实际采样/Fly、普通安装及 BA01–BA15 最终对账尚未完成。
后续主题包括group生命周期与公共三组合调度；当前不代表批次B完成，不启动C。

### B4 group 原生控制基线（7082d495 → 本主题提交）

冻结group operation集合，原PS owner登记每个实际worker的PID+creation identity并取得精确ACK，
在原句柄逐一drain和非继承host正式释放后才对账Store；未启动集合必须明确证明，缺件/nonce错/身份冲突保留保护。
quick-exit直接读取原Process句柄退出事实，不伪造host live登记；坏live登记不能回退为quick-exit。
实现为既有 store/native_artifact_controls/processes 及两个PS owner，不新增调度器或TTL。

隔离代码树实际16项原生短子进程测试PASS（188.200s），Store19及Ruff PASS。
main接线后，使用共享主机账本环境变量
`MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=C:/Users/Liao/mass_spectrometry/artifacts/platform/host_resources.sqlite3`，
运行 `tests.repository.test_native_artifact_controls` 的
`test_single_quick_exit_receipt_covers_success_and_failure` 与
`test_group_controller_death_preserves_all_workers_and_automatically_recovers`，2 PASS（36.344s）；
边界16 PASS（8.639s）。首次main尝试漏该必需环境变量而在worker启动前失败，修正后复验，不记为通过。

限制：中央持续物理危险可能停止并重新调度同一operation；当前operation→单身份不能自动闭合多attempt，
仍保守留权。Agent3已按真实scheduler路径只读确认，下一主题保留冻结operation集合，为每次实际启动增加身份与ACK，
不改预算/调度策略或强制单worker；不能把本基线称为BA09全通过。
测试临时目录 `C:/Users/Liao/AppData/Local/Temp/tmpft8zbwq3` 已确认无活进程，精确清理被自动策略拒绝，
保留原目录且未换路径/命令绕过。未清理任何真实研究产物。

### B3 显式原生资产的唯一配方快照

`recipes/native_assets.py` 扩展同一load_recipe：可显式冻结COMSOL共存OFF/ON manifest；桥接时同时冻结
原SIMION source-free FieldBundle作为碰撞载体，并要求作者显式world/windows采样。只读各小manifest一次，
不复制或在配方解析时读取PA/MPH；实际owner/几何/物理/采样覆盖由消费者另行验证。
`recipes/native.py` 冻结验证只读snapshot；科学身份纳入manifest内容身份与采样，不纳入路径或label。
错product/kind/未绑定产品/递归world碰撞源/非有限或下溢采样/错误策略均拒绝。

`.venv/Scripts/python.exe -m unittest tests.contracts.test_native_assets tests.contracts.test_native_asset_recipe tests.contracts.test_native_recipe -q`
14 PASS（3.420s），相关Ruff PASS。真实公开解析集成覆盖首次读取后外部manifest变化、冻结验证不重读、
路径/label不失效以及采样/碰撞内容变更失效。不是场解或原生追踪验收；桥接导出与实际Fly待下一主题。

### B3 COMSOL 双解与原生追踪软件闭包

`backends/comsol/assembly_particle_tracing.py` 与 MATLAB `solve_assembly_pulse_basis.m` 在同一模型保存
两个独立stationary解，原静态场保留，OA按原pulse切换；`trace_assembly_particles.m` 实际CPT入口消费
同一原birth、统一实验时间、显式积分控制与现有public物性。`particle_data.py` 输出schema2完整SI母群/终态/事件/轨迹；
缺失或无法归属的原生状态保持不完整，不能补成成功。`workflows/comsol_tracing.py` 编译同一冻结Study，
显式basis reference分支保护background/on并逐项比较实际projection与两组request，可跳过Compute直接追踪。
目前该CPT和reference编排只通过软件测试，未运行真实粒子，不能认定BA06/07/08/12通过。

`assembly_native_scope.py` 按真实manifest-bound run_config与geometry来源重建project身份，
旧复合project的新geometry/model/solve/basis/CPT执行明确拒绝；历史read/export/0Compute恢复保留。
不凭实例名猜物理角色。两项旧inert transport fixture不具备provenance，明确mock该独立scope检查，
另有真实冻结链与错误/不一致projection正反例，不把mock当owner科学证明。

设置共享host账本环境后，运行COMSOL scope/workflow/particle_tracing/world_scalar_contract/
assembly_electrostatic_model_managed/stationary_managed_failure 六模块，23 PASS（98.623s），相关Ruff PASS。
新增projection mismatch负例单独PASS。真实冷开脚本为外部workspace `recover_basis.py`，最终run
`20261127_023910__analysis__comsol__basis-recovery-e7a42a44d31e` 已success、writers_stopped=true、host released、
workspace workflow leases=0，background/on产品发布；manifest SHA256
`E2F7AC36D7854589C72C0C5DD375D8F90323154688709F447463194066030CB2`。
本次compute_calls=0，比较两solution/dataset、43组电压、mesh与真空均与真实Compute report一致。
借用原MPH SHA256 `02179DB42E4A25922315A13B4AAF8347C8B18C3BD9C291EF952FB3A72FEFA031`，
3,082,205,877 B、solver_native_binary；身份是Python失败之后新捕获。无新的Compute或收敛资格。
下一步固定已安装代码，从离仓同一公共CLI引用此basis跑真实小N CPT；新场与追踪证据分开报告。
