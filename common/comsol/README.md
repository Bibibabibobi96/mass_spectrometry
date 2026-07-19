# COMSOL共享测试与启动器

本目录保存跨项目可复用的COMSOL启动器和组件级验证测试，不保存任何项目的正式参数、模型或
当前结论。API调用查`docs/COMSOL_API.md`，通用排错查`docs/COMSOL_DEBUGGING.md`；采用某个测试
进入正式项目后，其几何、参数、GUI节点和验收状态必须写入该项目文档。

## 正式启动入口

`run_comsol_r2025b.ps1`是当前MATLAB R2025b + COMSOL 6.4 LiveLink任务入口。项目脚本不得再次
调用`mphstart`，也不得绕过入口维护另一套长期服务连接。

入口只对白名单中的启动瞬态进行有限重试：报告必须同时包含首次模型打开链路中的
`mphload`、`mphopen`和`Not connected to a server`。重试前失败报告以
`.startup_retry.<attempt>.<timestamp>`归档；进入配置、Study Compute或求解器后的空指针、断连和
原生崩溃均立即失败，不得用自动重试掩盖。分类回归入口为`test_livelink_failure_classification.ps1`。
每次启动前记录已有`comsolmphserver` PID；失败或未创建报告时只终止该次新增PID，再进入重试，
不得遗留孤立服务器，也不得终止启动前已存在的其他会话。

入口的`-ProcessorCount`是可选共享内存线程上限；默认`0`表示沿用COMSOL自动选择，日常结果不变。
只有排查本地并发库崩溃或项目已验证固定线程数时才显式设置，例如`-ProcessorCount 1`。线程数属于
运行环境证据，不能借此改变物理、网格或求解器定义。

`-Allocator`可选`auto/scalable/native`，默认`auto`保持COMSOL设置。Windows上若崩溃栈明确落在
COMSOL自带`tbbmalloc.dll`，可用`-Allocator native`绕过TBB scalable allocator；必须记录该运行
环境差异，并用同一物理输入核对结果，不得把分配器变化解释成物理或数值参数变化。

## 测试分组

|主题|测试入口|证明范围|
|---|---|---|
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
