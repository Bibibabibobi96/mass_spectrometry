# oa-TOF CAD 与 SolidWorks 同步

本文件只记录STEP/SolidWorks实现。正式几何和转正状态由[`PROJECT.md`](PROJECT.md)定义。

## 正式入口

- CAD导出：`../cad/ms_export_oatof_to_solidworks.m`
- 实体发现与导出清单：`../cad/oatof_cad_export_manifest.m`
- STEP导出实现：`../cad/export_oatof_cad_step.m`
- CAD测试：`../tests/cad/OaTofCadExportTest.m`
- 重命名前的只读Formal产物：工作区`artifacts/projects/oa_tof/formal/cad/`；历史主装配为
  `oa_tof__model_physical_components.SLDASM`，准确路径和SHA以
  [`../config/formal_assets.json`](../config/formal_assets.json)为机器权威。该文件名是正式资产清单
  记录的既有命名例外，不得只按通用命名示例猜测或擅自重命名。

MATLAB导出任务必须通过根`common/comsol/run_comsol_r2025b.ps1`获得既有LiveLink连接；
`export_oatof_cad_step.m`只校验LiveLink是否可用，不自行发现MLI或调用`mphstart`。SolidWorks安装由
`common/solidworks/`共享解析器从注册表或`SOLIDWORKS_2022_ROOT`发现，项目脚本不得保存安装盘符。
该入口的`load_only`模式只加载MPH并解析动态CAD manifest与实体对象，不创建输出目录、不导出STEP、
不运行求解器，也不保存模型；它用于把LiveLink/模型读取故障与STEP/SolidWorks故障分层。

`common/solidworks/import_step_to_solidworks.m`通过pywin32 COM桥接调用
`import_step_to_solidworks.py`。该桥接必须使用仓库根`.venv\Scripts\python.exe`的64位Python 3.11，
并安装由`requirements-lock.txt`冻结的Windows `pywin32`；系统PATH中的Python、MATLAB自身的Python
或其他Python版本都不是替代运行时。候选运行会冻结该Python可执行文件身份并把其目录置于CAD子进程
PATH首位，因此依赖缺失属于运行环境失败，而非STEP、SolidWorks或几何结果。修改此环境后必须先在
该`.venv`导入`pythoncom`与`win32com.client`并运行`pip check`，再以新的冻结Candidate run完成适用的
SolidWorks保存、引用与报告验收；不得修改或重用失败run的冻结输入。

Formal CAD目录对普通运行保持只读。MATLAB R2025b写入合同回归确认：普通CAD导出指向Formal时必须
拒绝；只有`OATOF_PROMOTION_TRANSACTION`中角色为`cad_root`且目的地与Formal CAD根精确一致的独立
晋升事务才能授权，任何相邻或不同路径仍被拒绝。该合同测试没有导出STEP、启动SolidWorks或修改
Formal资产。

CAD不直接解析候选JSON。`workflows/design_candidate/prepare_candidate_consumers.py`先把候选合同绑定到唯一候选MPH路径，
随后本文件的`modelPath`入口只读该MPH导出STEP和SolidWorks装配。这样机械几何继承已持久化的COMSOL
模型树，同时避免CAD另建一套参数推导；候选MPH不存在或未通过同步门禁时，CAD状态必须保持阻塞。
隔离任务`workflows/design_candidate/run_candidate_cad_sync.m`只接受候选MPH和`runs/<run_id>/cad/`输出目录；它不会读取、
覆盖或提升正式装配。通过SolidWorks保存检查后仍须等待跨软件候选验收和独立晋升决定。

STEP导入会让SolidWorks为每个外部实体新建原生零件，因此会读取机器默认零件模板。若该首选项仍指向
旧版本或失效路径，`LoadFile4`会弹出“默认模板不可用”对话框并阻塞无人值守运行。共享桥接器现在于
每次导入前临时绑定SolidWorks 2022安装目录中的空白`gb_part.prtdot`，同时显式使用
`gb_assembly.asmdot`创建装配；结束时恢复用户原来的模板路径和“总是使用默认模板”开关。报告中的
`templatePolicy`记录实际策略。不得把空字符串传给`NewDocument`冒充空模板，因为该API要求有效的
完整模板路径。

## 2026-07-27 Candidate CAD 闭合

零变化N=100运行
`artifacts/projects/oa_tof/runs/20260727_154500__test__cross__zero-change-candidate-bytecodefix-n100/`
通过完整Candidate结构链。CAD从本次候选MPH导出25个STEP，生成25个原生SLDPRT和一个25组件SLDASM；
全部零件及装配保存错误/警告为0，SolidWorks revision为`30.5.0`。根summary的五个阶段均为
`success`，manifest以`success`冻结130个输出；Formal目录没有修改。该证据只支持
`structural_build_and_contract`，不支持性能或晋升声明。

前一运行
`20260727_152000__test__cross__zero-change-candidate-durable-retry-n100`在COMSOL、SIMION和CAD完成后，
因Python模块导入向冻结`inputs/code/common/solidworks/`写入两个`.pyc`而无法通过最终源码闭包检查。
桥接器现同时使用Python `-B`和临时`PYTHONDONTWRITEBYTECODE=1`，并在调用后恢复原环境；154500运行
确认冻结源码内`__pycache__`和`.pyc`均为0。更早的
`20260727_145500__test__cross__zero-change-candidate-full-retry-n100`因父监督链中断而保持
`interrupted`。这两个run均不复用、不提升。包含CAD的正式长跑使用可恢复execution cell持续监督，
不通过`Start-Process`脱离运行终态；154500由cell `243`以退出码0在`1056.5 s`结束。

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

当前Formal CAD release由2026-07-29 vNext原子发布；它绑定拆层后的N=1000验证和独立CAD evidence。
其SolidWorks 2022 revision为`30.5.0`，包含25个组件；当前装配和导出报告的精确身份只认
`formal_assets.json`与Formal asset manifest。2026-07-20的耦合纵向CAD结果保留为来源历史：组件世界
中心相对COMSOL导出目标的最大误差为`6.82e-13 mm`，所有STEP加载、零件保存和装配体保存错误/警告
均为0；晋升前整套Formal资产已归档到
`artifacts/projects/oa_tof/archive/20260720_204500__superseded__cross__pre-coupled-baseline/`，没有与新正式零件混放。可重复门禁入口为
`../workflows/design_candidate/run_candidate_cad_sync.m`；它只在Candidate run内生成CAD资产。
Formal发布只允许通过
`../workflows/formal_reference/run_formal_validation.ps1 -Phase Publish`消费冻结装配与报告，
不再提供直接写Formal CAD目录的脚本。

当前CAD manifest把COMSOL的`accelshield`作为单一`accelerator_shield`实体导出，因此正式装配同样
没有沿RF→oa注入方向的侧孔。未来侧孔、法兰或接地注入管一旦进入候选，必须先在候选MPH形成真实
实体/切除，再由现有CAD链重新导出和验证；不得仅在SolidWorks装配中手工打孔形成第二份几何真值。

2026-07-22运行`20260722_121500__test__cad__load-only`通过统一R2025b/COMSOL 6.4入口只读加载当前
正式MPH，并解析出25个manifest特征和25个可导出实体；未运行求解器、未创建STEP输出目录、未修改
Formal。输入MPH哈希及两份轻量输出已由run manifest复核。该测试只证明CAD读取边界，不替代完整STEP
导出、SolidWorks装配或Formal CAD同步门禁。
