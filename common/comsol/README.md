# COMSOL共享测试与启动器

本目录保存跨项目可复用的COMSOL启动器和组件级验证测试，不保存任何项目的正式参数、模型或
当前结论。API调用查`docs/COMSOL_API.md`，通用排错查`docs/COMSOL_DEBUGGING.md`；采用某个测试
进入正式项目后，其几何、参数、GUI节点和验收状态必须写入该项目文档。

## 正式启动入口

`run_comsol_r2025b.ps1`是当前MATLAB R2025b + COMSOL 6.4 LiveLink任务入口。项目脚本不得再次
调用`mphstart`，也不得绕过入口维护另一套长期服务连接。

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
