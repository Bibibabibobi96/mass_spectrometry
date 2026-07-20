# oa-TOF统一分析入口

本目录只负责与求解器无关的指标、统计和图形。COMSOL模型树仍由MATLAB维护，SIMION运行时仍由
GEM/Lua/Fly2维护；Python不直接解析MPH或PA。

## 执行环境

Python版本、隔离环境和重建方法只以仓库根
[`README.md`](../../../README.md#python-311-分析环境)为权威；本目录不维护第二份工具链说明。
依赖声明和锁定版本分别为仓库根`pyproject.toml`与`requirements-lock.txt`。

## 权威边界

- 机器数据定义：`../config/analysis_contract.json`。
- 迁移基准身份与旧MATLAB参考：`../config/analysis_baselines.json`。
- 当前正式COMSOL/SIMION同源闭合记录：`../config/formal_validation.json`。
- 双区正交加速器一阶时间聚焦：`accelerator_time_focus.py`，公式来源为
  `../docs/theory/oaaccelerator_time_focus.md`。
- 二级反射镜局部闭式解：`reflectron_dual_stage_solver.py`，公式来源为
  `../docs/theory/dual_stage_reflectron.md`。
- 加速器—反射镜整机纵向耦合：`oatof_oaaccelerator_coupling.py`，公式来源为
  `../docs/theory/oatof_oaaccelerator_coupling.md`；当前Formal baseline已由该实现派生并通过晋升门禁，
  以后改动仍必须走隔离Candidate和独立晋升，分析脚本本身不能直接改写Formal。
- 候选静态消费准备：`prepare_candidate_consumers.py --contract <candidate_resolved_geometry.json>
  --output-dir <run-or-scratch-directory>`；生成SIMION Lua/Fly2和`candidate_consumption_plan.json`，其中
  COMSOL直接绑定同一合同，CAD绑定由该合同构建的候选MPH。它不启动COMSOL、SIMION或SolidWorks。
- 候选运行准备：`prepare_candidate_run.py`冻结`candidate_baseline/resolved/diff`，生成N=100粒子表及
  COMSOL、SIMION、CAD和跨软件验收的有向执行计划（粒子表本身由计划的首个运行命令生成）。它不执行商业软件，也不包含
  baseline/formal晋升。计划先进入`scratch/<task_id>/`，集成runner真正开始时才创建含三件套的run，
  避免留下不通过artifacts门禁的半成品运行目录。
- 候选运行记录后端：`candidate_run_lifecycle.py start <plan>`先在scratch组装包含
  `run_config.json/summary.json/run_manifest.json`的失效安全骨架，再原子进入`runs/<run_id>/`；
  `finalize`要求按工作流顺序提交全部阶段状态，并以success、failed或interrupted重写根summary和manifest。
  success只表示`candidate_accepted_not_promoted`，始终保持`formal_eligible=false`。
- 集成执行器：`run_candidate_workflow.py <scratch-plan>/candidate_workflow_plan.json`。它生成共享N=100
  粒子表，构建并同步检查候选COMSOL MPH，使用延迟根收口模式建立/检查SIMION PA/IOB，导出候选CAD，
  最后要求两端N=100粒子表SHA一致。当前接受范围固定为`structural_build_and_contract`，
  `performance_claim_allowed=false`；不能用这次成功替代N=1000性能、GUI Compute或正式晋升门禁。
- 数值算法：`peak_metrics.py`。
- 五质量标定、逐峰COMSOL/SIMION局部密度叠加和质心差汇总图：`mass_spectrum.py`。主图使用2×3布局，
  五个峰各自缩放局部质量偏差轴且共享各峰分箱，第六格只汇总跨求解器平均TOF差；全图图例明确
  区分两端密度、求解器峰均值、标称质量零偏差和质心差曲线。逐质量标准化KDE重叠和KS距离写入
  `mass_peak_shape_comparison.csv`并标在对应面板；该图不作Gaussian峰形拟合。同一入口另输出
  `mass_detector_landing_comparison.png`：五个质量各占一个等比例、共坐标范围子图，在每个子图中
  叠加COMSOL实心落点、SIMION空心落点、两端质心、RMS半径和质心间距。
- CSV/XLSX/SIMION TRACE导入、严格Recording审计、source mapping、bootstrap、出图和CLI：
  `reference_analysis.py`。
- 回归门禁：`verify_reference_analysis.ps1`。

回归门禁同时验证冻结迁移基准和当前`formal_validation.json`：后者会核对物理/分析契约哈希、
固定ION表、正式IOB、两侧逐粒子CSV以及Python比较指标，防止正式结果与外部artifacts静默漂移。

需要更新正式跨求解器记录时，只运行`../tests/cross_solver/run_formal_validation.ps1`。它直接加载当前
正式MPH和SIMION交付，使用同一正式N=1000 ION表重算两端、执行配对bootstrap，再由
`publish_formal_validation.py`冻结全部输入、结果、报告和资产SHA。禁止手工从候选或staging结果摘抄
数值更新`formal_validation.json`。

正式机器输入优先使用CSV/JSON。XLSX只用于接收SIMION GUI人工导出；读取后立即输出
`particles_normalized.csv`，Excel本身不是指标真值。

## 一键验证

在仓库根运行：

```powershell
.\projects\oa_tof\analysis\verify_reference_analysis.ps1
```

默认验证四个冻结数据集的文件大小、行数和SHA-256，然后生成统一指标、谱图、落点图和固定粒子
COMSOL/SIMION峰形对比。每次结果写入仓库外独立的
`artifacts/projects/oa_tof/runs/<run_id>/results/`，并同时生成三件套。

分析单个CSV或GUI导出的XLSX：

```powershell
.\.venv\Scripts\python.exe `
  .\projects\oa_tof\analysis\reference_analysis.py single `
  <input.csv-or-xlsx> --mass 524 --output <artifact-output-directory>
```

SIMION命令行TRACE可以直接作为`single`输入，不再先经MATLAB转表：

```powershell
.\.venv\Scripts\python.exe `
  .\projects\oa_tof\analysis\reference_analysis.py single `
  <simion-flight.log> --mass 524 --output <artifact-output-directory>
```

需要证明GUI Data Recording来源时，必须使用严格入口并记录Event、PA instance、X/Y/Z；只有TOF
一列的Excel只能分析峰，不能通过来源审计：

```powershell
.\.venv\Scripts\python.exe `
  .\projects\oa_tof\analysis\reference_analysis.py simion-recording `
  <recording.csv-or-xlsx> --mass 524 --output <artifact-output-directory> `
  --expected-particles 5000 --expected-pa-instance 4 `
  --expected-detector-z-mm 19.83 --detector-radius-mm 40
```

同一XLSX内并排保存多组记录时，Excel/Pandas会把重复表头改为`.1`等后缀。此时禁止依赖自动猜列，
必须显式指定每组列。例如正式Program On组使用：

```powershell
--program-state on --particle-id-column "program on" --event-column event `
--tof-column TOF --pa-instance-column "PA instance" `
--x-column x --y-column y --z-column z
```

Program Off只允许作为诊断组，可用`single`和对应`.1`列导入；它不能通过`simion-recording`
正式门禁。若两次Fly使用同一固定种子或同一显式ION表，比较时才允许增加
`--require-paired-particle-ids`；只有编号相同而没有初始粒子契约时不得假定配对。

当粒子表含`initial_x/y/z_mm`和`initial_energy_eV`时，`single`自动输出
`source_mapping_bins.csv`和`initial_z_tof_mapping.png`。配对跨求解器比较可增加
`--bootstrap-resamples 5000 --bootstrap-seed 20260715`；bootstrap与主指标使用同一KDE和直接FWHM
定义，不另设快速近似算法。若两侧同时包含检测器X/Y，`compare`还会自动输出
`detector_landing_comparison.png`、逐粒子落点CSV，以及质心距离、RMS半径差和配对落点距离指标。
严格配对时还输出右侧减左侧TOF的均值、RMS、去均值RMS和最大绝对差；均值衡量整体时移，
去均值RMS衡量不能通过统一平移消除的逐粒子映射差异。

## 跨求解器诊断

- `compare_field_profiles.py`比较同坐标轴向场，并把电极边界插值点与反射器内部指标分开。
- `compare_particle_trajectories.py`比较代表粒子的同时间位置、同z横向路径、转向深度和关键平面
  到达时间；SIMION输入必须是启用稀疏TRACE的正式quality=8日志。
- `compare_vector_field_samples.py`比较两侧在完全相同加速段坐标上的Ex/Ey/Ez。
- `analyze_longitudinal_closure.py`复用保存的轴线电势/Ez和配对比较JSON，量化COMSOL电势梯度与
  `es.Ez`差、跨求解器Ez差及初始z对逐粒子TOF差的解释率；它不启动求解器，也不替代正式重算。
- `mass_spectrum.py`按`config/modes/mass_spectrum.json`拟合
  `sqrt(m/z)=slope*TOF+intercept`，输出五点宽质量谱、标定残差、传输率、跨求解器质心差以及逐质量
  标准化KDE重叠/KS距离；经济样本禁止用于精确FWHM声明。
- `truncation_diagnostics.py`在正式配对粒子上比较能量窗、检测器有效半径和共享轴向释放宽度。每类
  截断统一重采样粒子数，半径另报告两求解器共同保留的配对交集，避免样本数变化被误判为峰宽改善。

这些入口只读取MATLAB/Lua导出的CSV，不直接解析MPH或PA。2026-07-16旧诊断产物位于oa-TOF
迁移快照的`legacy-layout/results/reference_analysis/formal_synced_2026-07-16/`；身份和关键结论由
`config/formal_validation.json`冻结。

## 维护规则

1. `R=m/FWHM_m`和直接半高宽只在`peak_metrics.py`维护一份。
2. 修改KDE带宽、网格点数或半高交点算法时，先提升契约版本，再更新基准；不得只调图形使结果接近。
3. MATLAB中为COMSOL/SIMION GUI保留的结果是软件内展示层，必须用冻结数据与本参考实现核对。
4. 本目录的通用代码只有在第二个项目实际复用后才能上移`common/`。
5. 已删除的MATLAB后处理脚本不得恢复；COMSOL MPH提取入口只导出逐粒子CSV，正式统计仍由本目录完成。
6. 修改三栅电压、间距或全局安装位置时，必须先通过`accelerator_time_focus.py`验证漂移距离和全局
   聚焦面；不得只复制文档中的旧示例数值。
