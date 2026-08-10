# oa-TOF CAD与SolidWorks同步

本文件只记录STEP/SolidWorks实施与独立验收。正式几何、资格和当前资产身份由
[`PROJECT.md`](PROJECT.md)及机器合同定义。

## 入口与资产

- CAD导出：`../cad/ms_export_oatof_to_solidworks.m`
- 动态实体清单：`../cad/oatof_cad_export_manifest.m`
- STEP实现：`../cad/export_oatof_cad_step.m`
- CAD测试：`../tests/cad/OaTofCadExportTest.m`
- Candidate同步：`../workflows/design_candidate/run_candidate_cad_sync.m`
- Formal发布：`../workflows/formal_reference/run_formal_validation.ps1 -Phase Publish`
- Formal资产身份：[`../config/formal_assets.json`](../config/formal_assets.json)

历史Formal位于项目descriptor登记的只读archive；路径、文件名和SHA只认asset manifest。既有主装配
`oa_tof__model_physical_components.SLDASM`是清单记录的命名例外，不得擅自重命名。

## 工具链

MATLAB任务必须经根`common/comsol/run_comsol_r2025b.ps1`使用既有LiveLink连接；CAD脚本不得再次
调用`mphstart`。`load_only`只加载MPH并解析动态实体，不创建目录、导出STEP、运行求解器或保存模型。

SolidWorks 2022由`common/solidworks/`共享解析器发现。STEP桥接使用根`.venv`中的64位Python 3.11
和锁定的pywin32；其他Python不是替代运行时。导入期间桥接器临时绑定SolidWorks 2022零件/装配模板，
结束时恢复用户设置，避免失效默认模板阻塞无人值守运行。

## 数据流与隔离

CAD不直接解析候选JSON：

`candidate contract → candidate MPH → dynamic CAD manifest → STEP → SLDPRT/SLDASM`

候选MPH不存在或未通过同步门禁时，CAD必须阻塞。Candidate只写本次
`runs/<run_id>/cad/`；普通运行不能写Formal。Formal CAD只有独立晋升事务可以原子更新。

导出器从实际COMSOL几何动态发现实体，不能用固定数量白名单。加速器屏蔽若新增侧孔、法兰或连接件，
必须先进入候选MPH，再由同一链导出；不能只在SolidWorks手工修改形成第二几何真值。

## 硬规则

- 正式机械几何确认后，同一事务同步COMSOL MPH和SolidWorks零件/装配。
- 不能只更新STEP；必须验证SLDPRT、SLDASM、组件、世界坐标、保存错误和警告。
- 迁移装配使用Pack and Go、Save As或自动化接口保持外部引用，不能只移动文件。
- 动态manifest必须覆盖全部可制造实体。
- SIMION detector数值终止层不是机械厚度，不触发CAD同步。
- Python冻结源码不得产生`__pycache__`或`.pyc`。

## 转正验收

1. COMSOL与SIMION几何合同通过。
2. STEP数量、名称和坐标与当前resolved几何一致。
3. 每个STEP成功保存对应SLDPRT。
4. SLDASM引用有效且组件完整。
5. 组件世界中心满足坐标容差。
6. 零件和装配保存错误/警告均为0。
7. 报告、资产和SHA进入run manifest，并由独立Formal发布消费。

任一项缺失时，`PROJECT.md`必须保持候选或阻塞状态。

## 当前边界

当前Formal CAD由vNext原子发布绑定，SolidWorks 2022独立evidence已通过；精确组件数、revision、路径、
SHA和来源run只认`formal_assets.json`与Formal manifest。已完成Candidate闭合、模板故障和旧load-only
探针的运行时间线保存在
[`history/`](history/)及2026-07-28文档快照，current不复制run ID或结果表。
