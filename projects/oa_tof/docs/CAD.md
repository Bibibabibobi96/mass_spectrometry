# oa-TOF CAD 与 SolidWorks 同步

本文件只记录STEP/SolidWorks实现。正式几何和转正状态由[`PROJECT.md`](PROJECT.md)定义。

## 正式入口

- CAD导出：`../cad/ms_export_oatof_to_solidworks.m`
- 几何构造：`../cad/oatof_cad_geometry.m`
- CAD测试：`../tests/cad/OaTofCadExportTest.m`
- 正式产物：工作区`artifacts/projects/oa_tof/formal/cad/`；主装配为`oa_tof__assembly.SLDASM`

## 硬性规则

- 正式机械几何一旦确认，必须在同一任务更新COMSOL正式MPH和SolidWorks零件/装配体。
- 不能只更新STEP；必须验证SLDPRT、SLDASM、组件数、世界坐标、保存错误和保存警告。
- 零件或目录迁移必须通过SolidWorks Pack and Go、Save As或自动化接口保持外部引用，不能只用
  文件系统移动后假定装配体仍有效。
- CAD导出器必须从实际几何动态发现零件，不得用固定数量白名单遗漏新增电极。
- SIMION检测器数值终止层不是机械检测器形状，不触发SolidWorks厚度同步。

## 转正验收

1. COMSOL与SIMION几何契约已经通过。
2. STEP数量、名称和坐标变换与当前机械参数一致。
3. 每个STEP成功生成并保存对应SLDPRT。
4. SLDASM引用全部有效，组件数量正确。
5. 组件世界中心与COMSOL目标坐标在约定容差内。
6. 保存错误和警告均为0。

未完成以上检查时，`PROJECT.md`中必须继续把几何标记为候选。

## 当前正式状态

2026-07-16已从通过门禁的正式COMSOL MPH重新导出CAD，并用SolidWorks 2022（revision 30.5.0）
生成25个SLDPRT和25组件SLDASM。组件世界中心相对COMSOL导出目标的最大误差为
`5.68e-13 mm`，所有STEP加载、零件保存和装配体保存错误/警告均为0。旧正式CAD目录整体归档为
迁移快照的`legacy-layout/cad/archive/formal_pre_baseline_sync_20260716/`，没有与新正式零件混放。可重复门禁入口为
`../tests/cad/run_oatof_formal_cad_sync.m`。
