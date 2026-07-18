# oa-TOF 项目使用指南（AI 与人类共用）

本目录是独立的 oa-TOF 项目，不是某个“components”分类下的附属部件。当前分析器方案为
正交加速、双级环栈反射镜；离子源、多级杆和电子枪分别属于其他平级项目。

本文件既是入口，也是本项目的知识路由规则。开始任务时先读本文件，再按任务类型选择一份
权威文档；不要默认从COMSOL、SIMION或历史日志开始阅读。

## 固定阅读顺序

1. 所有任务先读[`docs/PROJECT.md`](docs/PROJECT.md)，确认当前参数、正式/候选状态和开放任务。
2. 修改加速器或反射器的时间聚焦、场强、电压或轴向长度时，先读`docs/theory/`中对应推导；
   三栅加速器读`三栅加速器总长度符号推导.docx`，二级反射器读
   `单次反射TOF二级反射镜等时聚焦推导.docx`及其指定的Python参考实现。
3. 操作COMSOL时再读[`docs/COMSOL.md`](docs/COMSOL.md)。
4. 操作SIMION时再读[`docs/SIMION.md`](docs/SIMION.md)。
5. 操作STEP/SolidWorks时再读[`docs/CAD.md`](docs/CAD.md)。
6. 只有追溯旧结论时才进入`docs/history/`；历史文件不能覆盖当前项目结论。

历史入口仅由本文件提供：`docs/history/PROJECT_HISTORY.md`、
`docs/history/SIMION_VALIDATION.md`、`docs/history/SUPERSEDED_RESULTS.md`和
`docs/history/NUMERICAL_VALIDATION_20260716_18.md`。四份日常文档不再横向链接历史。

## 本项目的知识边界

知识归属、提升条件和星形引用规则以仓库根[`README.md`](../../README.md)为唯一权威。本项目只补充：
人工设计写入`config/baseline.json`，程序读取自动生成且禁止手改的`config/resolved_geometry.json`；
分析契约、迁移基准和正式闭合结果分别写入`config/analysis_contract.json`、
`config/analysis_baselines.json`和`config/formal_validation.json`。当前统一结论只写`docs/PROJECT.md`。

## 权威入口

- 人工设计入口：[`config/baseline.json`](config/baseline.json)；程序入口为自动生成的
  [`config/resolved_geometry.json`](config/resolved_geometry.json)，禁止手改。
- 全项目门禁：`verify_project.ps1 -Level Static|Candidate|Formal`。
  `Candidate`用`-CandidateTarget SIMION|COMSOL|CAD`只启动目标软件；COMSOL还需
  `-CandidateModelPath`，CAD需候选装配和导出报告路径。`Formal`单命令包含工具链、正式MPH重开与
  静电Compute、SIMION/CAD/COMSOL资产合同和Python正式分析；2026-07-18实测`166.159 s`。
- SIMION正式交付与收敛参考冻结清单：[`config/simion_stable_entry.json`](config/simion_stable_entry.json)。
  它冻结IOB、完整PA家族、Program、Fly2和粒子表的实现身份，不定义或替代统一物理baseline。
- 正式COMSOL生产脚本：
  [`comsol/run_oatof_model.m`](comsol/run_oatof_model.m)（具名参数稳定入口）；底层模型树构建器为
  `comsol/ms_oaTOF_two_stage_ringstack_reflectron.m`，物理组件实现位于同目录`oatof_*.m`模块。
- SIMION正式文本入口：
  [`simion/workbench/formal/oatof_ideal_grounded.lua`](simion/workbench/formal/oatof_ideal_grounded.lua)和
  [`simion/workbench/formal/oatof_ideal_grounded.fly2`](simion/workbench/formal/oatof_ideal_grounded.fly2)
- SIMION正式交付构建：[`simion/workbench/build_formal_delivery.ps1`](simion/workbench/build_formal_delivery.ps1)
- SIMION加速器网格相位诊断：
  [`tests/simion/test_accelerator_grid_phase.ps1`](tests/simion/test_accelerator_grid_phase.ps1)；统一分析为
  [`analysis/analyze_accelerator_grid_phase.py`](analysis/analyze_accelerator_grid_phase.py)。
- CAD正式入口：[`cad/ms_export_oatof_to_solidworks.m`](cad/ms_export_oatof_to_solidworks.m)
- 跨求解器门禁：
  [`tests/cross_solver/verify_geometry_contract.ps1`](tests/cross_solver/verify_geometry_contract.ps1)
- 统一分析契约：[`config/analysis_contract.json`](config/analysis_contract.json)
- 当前正式跨求解器验证：[`config/formal_validation.json`](config/formal_validation.json)
- 宽质量标定候选模式：[`config/modes/mass_spectrum.json`](config/modes/mass_spectrum.json)；只评价
  峰位、标定和传输率，不替代524 Da正式分辨率基线。
- 当前正式N=1000直接重算与发布入口：
  [`tests/cross_solver/run_formal_validation.ps1`](tests/cross_solver/run_formal_validation.ps1)；发布器只在
  两端1000/1000、统一比较PASS且当前资产/结果SHA齐全时更新机器契约。
- 三栅加速器时间聚焦参考实现：
  [`analysis/accelerator_time_focus.py`](analysis/accelerator_time_focus.py)
- 二级反射器闭式解参考实现：
  [`analysis/reflectron_dual_stage_solver.py`](analysis/reflectron_dual_stage_solver.py)
- Python参考分析：[`analysis/README.md`](analysis/README.md)
- 路径解析：[`oatof_paths.m`](oatof_paths.m)

## 当前状态速览

- 自2026-07-15起标准质量为524 amu，+1电荷，初始能量`5±0.4 eV`。
- 质量分辨率只按`R=m/FWHM_m`定义；窄峰时间域等价式为`R=T/(2*FWHM_t)`。
- SIMION常规统计使用N=5000；COMSOL快速闭合可使用较小但固定的同源粒子表。
- 紧凑加速器、10 mm封闭屏蔽罩、正式COMSOL MPH和SolidWorks 2022装配体已同步；细z检测器
  终止层仍只属于SIMION数值实现，不复制为机械厚度。
- SIMION正式运行资产已集中到`artifacts/projects/oa_tof/models/simion/formal/oatof_524amu/`；
  IOB只引用同目录四套PA；PA家族现由baseline/resolved契约和版本化GEM独立重建并通过N=1000
  等价门禁，可将整个目录作为同事复现包交付。
- 正式COMSOL日常档为真实加速器`hmax=1 mm`、敏感窗口`0.2 ns`、无场区`50 ns`，全部窗口由
  质量/电压/长度公式计算并在GUI中可见；N=100与`1 ns`分段档逐粒子等价，粒子阶段快`1.77x`。
- 同源N=1000正式统计、严格聚焦资产提升和N=100网格/时间步收敛均已有记录；入口不再重复易漂移的
  性能数字，精确值和身份分别以`docs/PROJECT.md`与`config/formal_validation.json`为准。不为追平
  单一R而改动求解器精度。
- 求解器无关峰形、FWHM、source mapping、Recording审计和bootstrap已固定到Python 3.11参考入口；
  四个纯MATLAB后处理入口已删除，旧数值只在历史/冻结基准中保留作迁移对照。
- 五点宽质量N=40候选已完成，COMSOL/SIMION两端各物种40/40命中并通过标定与manifest；该候选只
  评价峰位、传输率和质心差，不替代524 Da正式分辨率。COMSOL build 293的N=3原生崩溃已用N=40
  稳定绕开但保留为开放诊断，精确矩阵见`docs/COMSOL.md`。
- 五质量各N=1000候选已完成，两端每种1000/1000命中；主图现为五个逐峰COMSOL/SIMION局部叠加
  子图和一个质心差汇总子图，峰形差异保留为诊断，不提升为正式分辨率结论。
- 500 Da的N=100/300/1000/5000计时标定表明COMSOL固定开销占主导、SIMION近似线性且N=5000约
  151 s；后续N=40只作冒烟测试，常规五质量候选用N=300，峰宽/分辨率正式统计继续用N=1000。
  可复算入口为`tests/performance/run_single_mass_scaling_benchmark.ps1`，精确口径见`docs/PROJECT.md`。

精确数值、候选/正式边界和开放任务以`docs/PROJECT.md`为准。

## 目录职责

```text
oa_tof/
├─ README.md          # 本文件：项目入口和知识路由
├─ config/            # 跨软件机器参数契约
├─ docs/              # PROJECT/COMSOL/SIMION/CAD、理论推导及只读历史
├─ comsol/            # COMSOL/MATLAB正式生产源码
├─ simion/            # GEM、Lua、Fly2及构建/分析源码
├─ cad/               # COMSOL→STEP→SolidWorks可复现源码
├─ analysis/          # 与求解器无关的轻量分析
└─ tests/             # COMSOL、SIMION、CAD和跨求解器长期门禁
```

大型模型和结果位于工作区同级的`artifacts/projects/oa_tof/`，不进入Git。正式模型、候选模型、
运行记录、提升后的结果和临时文件必须分别进入`models/`、`runs/`、`results/`和`scratch/`，
不得重新创建旧的`artifacts/components/...`路径。

## 项目特有硬规则

- COMSOL与SIMION联动时必须使用同一几何、坐标、有效探测面、粒子表和FWHM定义。
- 正式或候选的几何尺寸必须参数化联动，禁止手工移动一个器件后遗漏相关选择集、屏蔽件或探测面。
- SIMION检测器PA是高于飞行管屏蔽罩的GUI可见数值终止层，只表示有效面和口径，不等于机械
  检测器厚度；当前正式契约中的Lua/Data Recording槽位与GUI优先级均为4。
- Program与Data Recording必须同时开启；关闭Program对话框不等于禁用Program。

通用GUI对等、SolidWorks同步、清理和参数单向派生规则不在本项目重复，直接适用根README与
仓库`AGENTS.md`。

## 修改后的最低检查

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tests\cross_solver\verify_geometry_contract.ps1 -SkipRuntime
.\analysis\verify_reference_analysis.ps1
git diff --check
git status --short --branch
```

正式COMSOL、SIMION或SolidWorks入口发生变化时，还必须执行对应软件文档规定的运行时验收。
完整N=100/1000粒子重算和SolidWorks装配重建仍是按变更类型触发的转正专项门禁，不纳入每次
`Formal`，避免日常检查膨胀到20分钟以上。
