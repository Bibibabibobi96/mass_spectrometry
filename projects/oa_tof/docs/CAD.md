# oa-TOF CAD 与 SolidWorks 同步

本文件只记录STEP/SolidWorks实现。正式几何和转正状态由[`PROJECT.md`](PROJECT.md)定义。

## 正式入口

- CAD导出：`../cad/ms_export_oatof_to_solidworks.m`
- 几何构造：`../cad/oatof_cad_geometry.m`
- CAD测试：`../tests/cad/OaTofCadExportTest.m`
- 正式产物：工作区`artifacts/projects/oa_tof/formal/cad/`；主装配为`oa_tof__assembly.SLDASM`

CAD不直接解析候选JSON。`analysis/prepare_candidate_consumers.py`先把候选合同绑定到唯一候选MPH路径，
随后本文件的`modelPath`入口只读该MPH导出STEP和SolidWorks装配。这样机械几何继承已持久化的COMSOL
模型树，同时避免CAD另建一套参数推导；候选MPH不存在或未通过同步门禁时，CAD状态必须保持阻塞。
隔离任务`tests/cad/run_candidate_cad_sync.m`只接受候选MPH和`runs/<run_id>/cad/`输出目录；它不会读取、
覆盖或提升正式装配。通过SolidWorks保存检查后仍须等待跨软件候选验收和独立晋升决定。

STEP导入会让SolidWorks为每个外部实体新建原生零件，因此会读取机器默认零件模板。若该首选项仍指向
旧版本或失效路径，`LoadFile4`会弹出“默认模板不可用”对话框并阻塞无人值守运行。共享桥接器现在于
每次导入前临时绑定SolidWorks 2022安装目录中的空白`gb_part.prtdot`，同时显式使用
`gb_assembly.asmdot`创建装配；结束时恢复用户原来的模板路径和“总是使用默认模板”开关。报告中的
`templatePolicy`记录实际策略。不得把空字符串传给`NewDocument`冒充空模板，因为该API要求有效的
完整模板路径。

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

2026-07-20已从耦合纵向正式COMSOL MPH重新导出CAD，并用SolidWorks 2022（revision 30.5.0）
生成25个SLDPRT和25组件SLDASM。组件世界中心相对COMSOL导出目标的最大误差为
`6.82e-13 mm`，所有STEP加载、零件保存和装配体保存错误/警告均为0。晋升前整套Formal资产已归档到
`artifacts/projects/oa_tof/archive/20260720_204500__formal__pre-coupled-longitudinal-baseline/`，没有与新正式零件混放。可重复门禁入口为
`../tests/cad/run_oatof_formal_cad_sync.m`。

当前CAD manifest把COMSOL的`accelshield`作为单一`accelerator_shield`实体导出，因此正式装配同样
没有沿RF→oa注入方向的侧孔。未来侧孔、法兰或接地注入管一旦进入候选，必须先在候选MPH形成真实
实体/切除，再由现有CAD链重新导出和验证；不得仅在SolidWorks装配中手工打孔形成第二份几何真值。
