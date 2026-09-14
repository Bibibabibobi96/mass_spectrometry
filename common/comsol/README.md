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
创建后不限制Study Compute的正常长运行。超时会终止本次进程树、清理本次新增服务器并进入有限
重试，不能被记录为项目求解器或物理模型失败。
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

### 主机资源阶段

入口通过公共主机调度器依次申请 `prepare`、`solver`、`postprocess` 预算；COMSOL求解属于重许可阶段，
与PA构建、内部并行离子飞行及其他重任务串行。轻任务按公共预算在CPU、内存和I/O准入仍满足时可与之
并行，调用方不能根据瞬时低利用率自行改写任务类别。`-ResourceBudgets` 可传入冻结资源
计划中的同名阶段预算；预算仅控制CPU、内存、I/O与独占资源，不修改模型、求解器或物理参数。
`-RunId`只绑定运行身份，公共策略是默认预算的唯一来源，本入口不维护另一套容量常量。
所有求解阶段强制追加同一个 `comsol-server-session` 具名独占资源，即使自定义预算未声明它也不能绕过。
服务器启动前的 PID 清单只在取得此锁后读取，锁一直保留到本次服务器清理完成；因此不会把排队期间
其他受管会话创建的服务器误判为本次新增进程。普通未知GATE按中央轻任务预算准入后可与COMSOL并行，
无须先完成专项峰值测量；未分类商业计算仍属重任务，且不开放多个受管COMSOL服务器会话并行。

launcher 启动后立即登记 PID；等待报告和长时间 Compute 期间持续刷新后代进程记录。登记失败时终止
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
