# oa-TOF 当前项目状态

本文件只保存当前权威状态、关键验收结果和开放任务。人工设计以
[`../config/baseline.json`](../config/baseline.json)为准，程序读取自动生成的
`../config/resolved_geometry.json`并按`../config/modes/`运行；精确性能、资产身份和分析定义分别以
`../config/formal_validation.json`、`../config/simion_stable_entry.json`和
`../config/analysis_contract.json`为机器权威。详细诊断过程只进入`docs/history/`，不得反向覆盖本文件。

## 当前正式状态

- 方案：524 amu、+1电荷的正交加速TOF，双级环栈反射镜，一级10环、二级5环；初始能量
  `5±0.4 eV`，负能量重采样。
- 统一坐标：检测器有效面中心与精确一阶时间焦点为`z=0`，`+z`从加速器指向反射器；COMSOL与CAD
  直接使用此坐标，SIMION局部PA必须通过IOB变换映射到同一坐标。
- `baseline → resolved → COMSOL/SIMION/CAD`是唯一参数链。现有软件文件、网格坐标和GUI显示不能
  反向修改baseline；候选覆盖不能改写正式参数。
- 正式COMSOL MPH、SIMION四实例自包含交付和SolidWorks 2022的25组件装配均已建立并通过各自
  资产门禁。SIMION正式PA顺序为`shield 1 < reflectron 2 < accelerator 3 < detector 4`。
- 当前只完成oa-TOF分析器本体；尚未与RF四极杆正式连接。

## 物理与几何基线

紧凑三栅加速器保持对称等间距：`d1=3.0 mm`、`d2=16.8 mm`，五环中心间距均为`2.8 mm`。
repeller/grid1/grid2全局z为`-19.92918680341103/-16.92918680341103/
-0.12918680341103 mm`；释放体为`1×1×1 mm³`，轴向范围
`-18.92918680341103...-17.92918680341103 mm`。加速器平移量和焦点位置来自解析式，不得按显示
精度手工取整。

反射器一级长度`120 mm`、二级工程长度`86.8328 mm`，总反射区`206.8328 mm`；工程长度保留四位
小数。屏蔽罩内半径`350 mm`，侧壁和端盖厚度`10 mm`。加速器出口的`30×30 mm`理想透明栅网是
独立器件，不是屏蔽罩端盖。

SIMION日常加速器网格为`xy=0.25 mm,z=0.05 mm`，`z=0.025 mm`只作轴向收敛参考；轨迹质量为8。
检测器数值PA半径`40 mm`、有效面`z=0`、槽位与GUI优先级均为4。其0.1 mm吸收层只负责数值终止，
不等于COMSOL/CAD中的机械检测器厚度。

反射器长度、电压及所有派生坐标的完整公式和精度规则位于baseline及`docs/theory/`。修改加速器或
反射器前必须先重算理论，再同步三个软件和CAD，不得在本文件另建公式副本。

## 当前验证结论

质量分辨率统一定义为`R=m/FWHM_m`；窄峰时间域等价式为`R=T/(2*FWHM_t)`。只有近似高斯时才可
用`2.3548×sigma`代替直接半高宽。求解器无关分析由Python 3.11参考实现执行。

`config/formal_validation.json`冻结的同源N=1000正式比较为：

| 指标 | COMSOL | SIMION |
|---|---:|---:|
| 命中 | 1000/1000 | 1000/1000 |
| 平均TOF (us) | 71.99021389 | 71.99101518 |
| 直接质量FWHM (Da) | 0.01346719723 | 0.01177287159 |
| 质量分辨率R | 38909.36 | 44509.11 |

该记录由`current_assets_n1000_20260718`直接加载当前正式MPH和当前正式SIMION包重算，平均TOF差
`0.80130 ns`、逐粒子TOF RMS差`1.09302 ns`、落点RMS差`0.14351 mm`。标准化KDE重叠为
`0.72556`；5000次配对bootstrap的绝对R差异2.5%/中位数/97.5%分位为
`0.963%/12.824%/24.101%`。下限接近零，说明直接FWHM差异对多模态重采样仍敏感；不能把单一R差
解释为确定的场误差，也不能为追平它而调网格、时间步、quality或场参数。

现有原因定位表明：反射器内部独立场相对RMS差约`0.000528%`，主要差异来自加速区纵向场和
z-to-TOF映射。COMSOL加速器`hmax=1 mm`是日常档，`0.5 mm`是收敛参考；后者改善横向梯度伪影，
但没有消除纵向焦点差。SIMION fractional surface使静电场基本不受网格相位影响，但固定距离越过
透明数值栅网会放大粒子TOF差；当前加速器和反射器跳转均为`0.0001 mm`。

先前严格聚焦staging比较与当前直接重算的平均TOF差、逐粒子TOF RMS差和落点RMS差分别为
`0.84220/1.12383 ns/0.14466 mm`与`0.80130/1.09302 ns/0.14351 mm`，结构一致。前者现只作为
提升过程证据；当前权威只引用新版`formal_validation.json`及其直接运行产物。

## 正式资产与门禁

- COMSOL：`artifacts/projects/oa_tof/models/comsol/formal/`中的正式MPH；GUI重开后几何、选择集、
  网格、Study/Solver、数据集和绘图组必须可检查并可由Study Compute等价复算。
- SIMION：`artifacts/projects/oa_tof/models/simion/formal/oatof_524amu/`中的IOB、四套PA、Lua、Fly2、
  ION、SHA和manifest；整个目录可作为同事复现包。
- CAD：正式SolidWorks装配为25个零件/25组件；几何变更必须同任务重建并检查版本、变换、保存错误
  和警告。
- 门禁：`verify_project.ps1 -Level Static|Candidate|Formal`。完整N=100/1000粒子重算和SolidWorks
  重建由相应物理、数值或几何变更触发，不塞入每次Formal身份检查。

候选只有在共享几何契约、同源粒子比较、差异解释或收敛、COMSOL GUI Compute以及SolidWorks同步
全部通过后才能转正。模型或CAD没有改变时，不为形式主义重复重建昂贵资产。

## 下一步

1. **SIMION透明栅网去网格相位化。** 若继续追求亚ns逐粒子闭合，实现自动越过实际数值电极层，
   并证明对网格相位收敛；不能继续扫描固定跳转距离追平单一R。
2. **按需发布复现ZIP。** 从正式自包含目录生成不含日志、收敛参考和临时轨迹的ZIP及独立SHA；发送后
   ZIP可删除，源码构建链和正式目录继续保留。
3. **制造与装配误差预算。** 以baseline为唯一参数源，对尺寸、同轴度、间隙、倾斜、电压、检测面、
   热膨胀和装配基准先做局部灵敏度，再做受公差约束的Monte Carlo，输出分辨率良率和制造公差建议。
4. 二维轴对称COMSOL混合模型仍为未来优化；在RF四极杆接口闭合前，不建立正式多部件连接模型。
