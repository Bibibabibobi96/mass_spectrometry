# COMSOL共享测试与启动器

本目录保存跨项目可复用的COMSOL启动器和组件级验证测试，不保存任何项目的正式参数、模型或
当前结论。API 调用查[API 参考](../../docs/COMSOL_API.md)，通用排错查[排错指南](../../docs/COMSOL_DEBUGGING.md)；采用某个测试
进入正式项目后，其几何、参数、GUI节点和验收状态必须写入该项目文档。

本目录同时保存经实际复用的最小构建原语：圆柱、圆柱壳、开孔板、圆杆多极阵列、全局自动网格和局部
最大单元尺寸节点。调用方必须显式传入尺寸、轴向、位置、选择和网格值；原语不决定物理设计或收敛资格。
当前多极杆生产构建器使用几何与网格原语，oaTOF生产网格构建器使用同一个局部Size原语；“生产”
只描述受维护的代码入口，不授予任何模型Formal资格。

## 正式启动入口

`run_comsol_r2025b.ps1`是共享LiveLink任务入口；允许的软件版本和调用命令只以仓库根
[操作指南](../../docs/OPERATIONS.md)为权威。项目脚本不得再次调用`mphstart`，
也不得绕过入口维护另一套长期服务连接。
入口默认从Windows卸载注册表发现COMSOL 6.4，并从`ProgramFiles`派生MATLAB R2025b根目录；非标准
安装分别使用`COMSOL_64_ROOT`和`MATLAB_R2025B_ROOT`覆盖。环境变量只描述软件部署位置，不承载模型参数。

尚未创建任务报告的启动失败由入口有限重试；已经创建报告时，只有命中窄白名单的首次模型打开
瞬态允许重试：报告必须同时包含首次模型打开链路中的
`mphload`、`mphopen`和`Not connected to a server`。重试前失败报告以
`.startup_retry.<attempt>.<timestamp>`归档；进入配置、Study Compute或求解器后的空指针、断连和
原生崩溃均立即失败，不得用自动重试掩盖。分类回归入口为`test_livelink_failure_classification.ps1`。
每次启动前记录已有`comsolmphserver` PID；失败或未创建报告时只终止该次新增PID，再进入重试，
不得遗留孤立服务器，也不得终止启动前已存在的其他会话。
`-StartupReportTimeoutSeconds`默认120秒，只限制MATLAB/LiveLink创建首份任务报告的启动阶段；报告
创建后不限制Study Compute的正常长运行。`-StartupReportTimeoutAction` 默认 `stop`：超时会终止本次
进程树、清理本次新增服务器并进入有限重试，不能被记录为项目求解器或物理模型失败。
显式 `warn` 则超阈只提醒一次，继续等待同一进程的报告及真实退出，不因超时杀进程或重启；
真实退出后缺报告仍失败且不重试，最终退出码和报告判据不变。调用方须冻结这一运行策略。
`comsolstartup.m`在进入项目任务前把独立bootstrap报告写为`STATUS=RUNNING`，项目任务返回后才覆盖为
`STATUS=PASS`；异常则覆盖为`STATUS=FAIL`。launcher看到`RUNNING`只表示LiveLink已进入任务，不表示
科学计算成功，它会继续等待进程终态，并且只接受退出码0与最终`PASS`同时成立。进程退出后若报告仍为
`RUNNING`、缺失或互相矛盾，必须失败关闭。
只有未创建任务报告时，入口才保存`.launcher.attemptN.stdout/stderr.log`供启动诊断；正常任务不生成
这组冗余日志。项目运行器必须把实际产生的launcher日志纳入失败manifest。
入口启动前实际探测用户目录下的`.comsol`配置、Tomcat日志和临时目录写权限；受限环境返回
`EXECUTION_ENVIRONMENT_BLOCKED`并立即停止。此时应在允许商业软件正常访问用户配置目录的执行上下文
重试同一冻结输入，不能直接归因于COMSOL配置损坏、项目脚本或Study失败，也不能只延长启动超时。

入口的`-ProcessorCount`是可选共享内存线程上限；默认`0`表示沿用COMSOL自动选择，日常结果不变。
只有排查本地并发库崩溃或项目已验证固定线程数时才显式设置，例如`-ProcessorCount 1`。线程数属于
运行环境证据，不能借此改变物理、网格或求解器定义。

`-Allocator`可选`auto/scalable/native`，默认`auto`保持COMSOL设置。Windows上若崩溃栈明确落在
COMSOL自带`tbbmalloc.dll`，可用`-Allocator native`绕过TBB scalable allocator；必须记录该运行
环境差异，并用同一物理输入核对结果，不得把分配器变化解释成物理或数值参数变化。

`-AssemblyScalabilityMode`可选`auto/off/matrix/vector/on`；默认`auto`不传开关，保持原有COMSOL设置，
并非供应商枚举值。显式模式传递官方`-memoptassem <mode>`，分别控制关闭、仅矩阵装配、仅向量装配和
全部装配的内存可扩展性优化。调用方须冻结该执行选项；它不改变入口的资源准入、精度、重试或退出判据。
依据：[COMSOL 6.4 Commands on Windows](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_running.38.31.html)，
COMSOL官方，2026-10-22复核。这里列的是当前 wrapper 接受的值；本机6.4.0.293原生解析器在真实启动中
拒绝 `on`，错误日志列出 `off/matrix/vector/all`，与该官方页面存在差异。当前 wrapper 不接受 `all`，
不能用它替代 `on` 后绕开入口。`auto` 与 `matrix` 已经通过公共入口完成真实小模型，
见[冻结配置及两份原始拒绝日志的输入绑定][assembly-evidence]；`off/vector` 本索引未登记真实运行。
替身参数传递测试、成功启动和小模型 Compute 分别只证明各自范围，不能据此声称修复 MR 矩阵装配断言、
降低大型模型内存峰值、提高性能或获得数值收敛资格。

[assembly-evidence]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_104700__test__comsol__quick-unknown-closure__r03/run_config.json

### 主机资源阶段

入口通过公共主机调度器依次申请 `prepare`、`solver`、`postprocess` 预算；COMSOL求解属于重许可阶段，
与PA refine、离子飞行及其他重任务串行；PA输入准备、GEM转PA和缓存物化默认轻任务。
轻任务按公共预算在CPU、内存和I/O准入仍满足时可与之并行，调用方不能根据瞬时低利用率自行改写任务类别。
`-ResourceBudgets` 可传入冻结资源
计划中的同名阶段预算；预算仅控制CPU、内存、I/O与独占资源，不修改模型、求解器或物理参数。
`-RunId`只绑定运行身份，公共策略是默认预算的唯一来源，本入口不维护另一套容量常量。
所有求解阶段强制追加同一个 `comsol-server-session` 具名独占资源，即使自定义预算未声明它也不能绕过。
服务器启动前的 PID 清单只在取得此锁后读取，锁一直保留到本次服务器清理完成；因此不会把排队期间
其他受管会话创建的服务器误判为本次新增进程。普通未知GATE按中央轻任务预算准入后可与COMSOL并行，
无须先完成专项峰值测量；未列入中央重任务名单的阶段默认轻任务。本入口的solver明确列为重任务，
且不开放多个受管COMSOL服务器会话并行。

launcher 启动后立即登记 PID；等待报告和 Compute 期间只检查进程与报告，不反复执行全机资源查询。
已登记的进程身份继续持有预约；进程退出后刷新一次，再按原顺序清理服务器和切换阶段。登记失败时终止
本次 launcher 并清理本次新增服务器，防止留下无归属求解器。任务成功或失败后，先关闭本次新增服务器
并确认其退出，再申请后处理预算；不关闭启动前已有的服务器。清理失败时不降级求解阶段预算，调度器
继续保留存活后代的原资源申请。阶段切换由调度器保留仍驻留的进程内存，
入口不以传入的零额外保留量清空调度器观测值。所有退出路径释放本层申请，原有连接、重试和失败报告
判据保持不变。项目调用方若仍持有全程独占父申请，内层继承该预算，不能借分阶段调用缩减父预算；
要启用阶段间并行，项目运行器须在调用前释放准备阶段申请，并在返回后为自身验证与发布另取预算。

`test_livelink_resource_stages.py` 在临时目录替换外部调度与进程启动，验证阶段顺序、登记失败清理及
重试边界；不运行商业软件、不占真实主机预算，也不代表真实求解器资格。

## 测试分组

|主题|测试入口|证明范围|
|---|---|---|
|共享连接冒烟|`test_livelink_connection.m`|确认统一入口连接真实COMSOL服务器并读取版本/模型标签；不创建模型、不运行求解器|
|多极杆几何与静电场|`test_multipole_geometry.m`、`test_multipole_es.m`|偶数多极杆几何、交替电位和近轴场|
|四极稳定性|`test_quadrupole_stability.m`、`test_multipole_stability.m`|特定理想条件下的稳定/不稳定工作点|
|Einzel透镜|`test_einzel_lens.m`、`test_einzel_cpt.m`|静电透镜最小几何、场与轨迹验证|
|线性离子阱|`test_lit_geometry_es.m`、`test_lit_cpt.m`|RF径向与DC轴向约束的最小组合|
|磁场与线圈|`test_magnetic_coil.m`、`test_cpt_magnetic_force.m`|Numeric Coil和CPT磁力最小链路|
|磁扇形场与ICR|`test_magnetic_sector.m`、`test_icr_cell.m`|回旋半径标度和组合捕集最小模型|
|碰撞|`test_collision_cell.m`、`test_resonant_charge_exchange.m`|碰撞父/子特征及可观察碰撞效应|
|空间电荷|`test_space_charge.m`|粒子间库仑作用的开启/关闭对照|
|Wien过滤器|`test_wien_filter.m`|交叉电磁场的速度选择条件|
|GPU对照|`test_collision_cell_gpu_comparison.m`|同一小型测试中CPU/GPU结果与耗时对照|

这些文件是组件验证基线，不是生产脚本，也不代表任一正式仪器已经完成。新的共享测试必须有
明确理论对照或开启/关闭对照，生成GUI可检查的MPH节点，并说明适用边界。

### 源码覆盖与运行证据

上表描述测试设计覆盖，不是逐文件最近一次 PASS 清单。本索引未建立全部组件测试的独立 run 与
GUI 验收映射；选择测试时须读取其判据，并核对对应冻结输入、summary 和 manifest，不能由名称、
注释中的“验证”或现存 MPH 推定实际运行。关键调用的现有小模型证据在
[关键能力证据索引](#关键能力的证据索引)集中定位，不在这里复制数值结论。

| 要查的层级 | 现有入口 | 证据的含义 |
|---|---|---|
| 替身／纯逻辑 | `test_livelink_resource_stages.py`、`test_livelink_failure_classification.ps1`、`test_livelink_environment.ps1` | 分别检查调度与清理、重试分类、环境预检；运行结果须另存，不证明真实 COMSOL 求解 |
| 真实连接 | `test_livelink_connection.m` | 只连接与读版本；不能替代模型创建或 Compute |
| 真实组件 Compute | [关键能力证据索引](#关键能力的证据索引)中的场／CPT／插值记录 | 核对模型、唯一变量、解析或对照判据；有负结果时保留，不将整组改称 PASS |
| 保存重开 | 同一索引中的 Time 属性检查 | 当前证据是空模型属性持久化；不是求解精度，也不是 GUI 点击 Compute |
| 项目功能与 GUI Compute | 根 [项目导航](../../README.md#项目导航)→目标项目 README→PROJECT／验证合同 | 必须绑定具体资产、输入与验收；不从共享组件测试继承项目资格 |

### 关键能力的证据索引

本表只索引已保留证据的范围，不发布新的通用数值设置或仪器资格。真实 Compute 指脚本中的
Study/Solver 执行；GUI Compute 指 Desktop 重开后操作，二者不能互换。项目参数、功能精度和资格
仍由各项目 README 导向其 PROJECT 与机器合同。

| 能力 | 官方语义与本地实现入口 | 已登记验证 | 尚不能证明 |
|---|---|---|---|
| 活动 Time 步策略 | [Time API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.51.html)；[活动键映射](../../docs/COMSOL_API.md#time-节点的活动步策略) | [OA 修复记录第 2 节](../../projects/single_reflection_oa_tof_mass_analyzer/docs/history/20261021__oatof-cpt-fixed-policy-reference-and-full-flow.md#2-已完成的实现验证及其边界)：GA/BDF/DP5 空模型写入、保存重开、回读；DP5/GA 小模型另有真实 Study.run 前后回读 | 空模型不是轨迹求解；诊断配置未完成正式资产保存重开与 GUI Compute 晋升 |
| 固定网格的代数停止误差 | [CG-AMG](../../docs/COMSOL_API.md#稳态cg-amg与电势阶次)；[场探针冻结结果][api-field] | 同一 4,879 四面体、7,292 DOF 的线性电势模型，真实 CG 默认/加严及 PARDISO 参考三案，保存活动引用与采样误差 | 未做仪器空间收敛；不能据此规定全仓 stol 或直接法 |
| 原生粒子读取 | [mphparticle 官方参考](https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_ref.9.51.html)；[数值提取](../../docs/COMSOL_API.md#数值提取) | [输出双通道小模型][api-output]核对默认 p/v 与显式坐标/速度；[OA README](../../projects/single_reflection_oa_tof_mass_analyzer/README.md)导航到真实 N100 配对与事件回归 | 数组有限不代表数值准确；固定 t 查询不能自动获得精确壁面位置或停止时间 |
| 原生插值函数驱动 CPT | [函数 API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.34.html)；[小模型结果][api-interpolation] | 规则线性表、显式单位、范围外行为和解析轨迹的真实 Compute | 非均匀三维仪器场的采样收敛、能量一致性及整体提速仍未验证 |
| 平面 Freeze 与停止时间 | [粒子状态](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.02.html)、[Freeze](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.38.html) | [平面常速小模型][api-wall]核对全部 N100 的解析停止时间；OA 新一轮稀疏固定 t 查询保留负结果，见该项目 README 的完成记录 | 不能直接替换整机检测器；曲面、多壁面与目标边界身份须另验 |
| 装配内存选项 | [Windows 命令](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_running.38.31.html)；[共享入口边界](#正式启动入口) | [冻结启动与恢复配置][api-assembly]：本机拒绝 on，auto/matrix 已完成真实小模型；原始拒绝日志已绑定 | 官方页和当前 wrapper 枚举不等于本机均可启动；没有大型装配峰值或 MR 断言修复结论 |

上述场、插值和输出小模型由 OA 容器承载，仅用于组件诊断；不能算作第二个仪器项目验证。
共享组件测试的源码分组见[测试分组](#测试分组)。

后续[原生回读与 Counter 五案](../../projects/single_reflection_oa_tof_mass_analyzer/docs/history/20261022__native-event-readback-and-counter-validation.md)
另验证了普通时刻库存、实际停止时刻查询，以及 Counter 的求解前／后创建与输出敏感性；
其中稀疏 Counter 两案为 failed。它补充接口证据，不授予生产检测器资格。

[api-field]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_102831__test__comsol__field-and-cpt-followup__r02/results/field_followup_summary.json
[api-output]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_104700__test__comsol__quick-unknown-closure__r03/results/output_controls_summary.json
[api-interpolation]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_104700__test__comsol__quick-unknown-closure__r03/results/interpolation_summary.json
[api-wall]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_104700__test__comsol__quick-unknown-closure__r04/summary.json
[api-assembly]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_104700__test__comsol__quick-unknown-closure__r03/run_config.json

### 组件测试的输出上下文

使用 `common_artifact_paths` 的组件测试以 `runDir` 为第一个必填参数，其余物理参数及默认值不变。
调用方先准备已有的 `artifacts/projects/<project>/runs/<run_id>` 或 `scratch/<task_id>` 容器；
测试仅在其 `comsol/` 保存模型、`results/` 保存图表，不再写共享 `common/models`、`common/results`。
求解器启动仍使用上述统一入口，launcher 的 `TaskScript` 脚本负责传入该上下文，不新增启动器。

同一测试链的构建和消费阶段必须传入同一个目录，例如任务脚本中的
`test_multipole_geometry(runDir, 4); test_multipole_es(runDir, 4);`。
Einzel 和 LIT 的构建、CPT阶段同样共享上下文，以读取该次生成的模型；不得从全局目录选取旧模型。
独立试验使用不同容器，禁止向已发布终态run追加或覆盖模型。可引用运行仍由调用方按
[生命周期](../../docs/LIFECYCLE.md)冻结输入、summary与manifest；临时测试在scratch执行后按该规则清理。
[路径回归说明](../paths/README.md)提供组件显式上下文的静态检查和独立 MATLAB 路径行为测试；
两者均不代表真实 COMSOL 求解已经验收。
