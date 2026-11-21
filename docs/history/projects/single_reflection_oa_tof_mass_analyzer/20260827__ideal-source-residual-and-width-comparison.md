# 2026-08-27 理想场数值源：残差调压与束宽接受比较

DOC_STATUS: ARCHIVED_READ_ONLY

## 目的、入口和证据

按用户指定顺序，先做残差扫描及调压前后比较，再做两区/三区束宽接受比较；
不启动SIMION、COMSOL或三维场，不修改524 Da Formal资产。复用现有精确轴向时间、
两级反射器解和公共峰宽分析，只增加统一数值源、批量入口及自动判定。
入口说明见[analysis README](../../analysis/README.md#自动理想场比较)，
科学输入见[实验配置](../../config/experiments/ideal_source_comparison.json)。

成功run：`20260827_132146__analysis__python__ideal-source-comparison`，位于工作区
`artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/`。84/84比较、168计算臂完成，
计算和出图耗时51.505秒（不含随后manifest发布验证）；schema-v2 manifest校验成功，登记191项输出。
每臂1000粒子、三个种子20260827—20260829；全部168臂均保留完整1000-ID母样本并到达轴向模型检测面。
这是理想轴向模型适格率，不是实际小孔收集率或三维传输率。

残差和束宽阶段各输出summary；每个case有CSV、指标JSON和完整性校验；总报告在`results/report.md`，
PNG/SVG和图形来源元数据在同一目录。三种子范围不是bootstrap置信区间。图形是run证据，尚非投稿排版验收。

## 冻结条件与对照含义

- 100 Th、单电荷；均匀轴向位置分布，`v = vc + kappa*(x-xc) + epsilon`，
  `epsilon`为独立Gaussian残差。`xc=1.498375640839315 mm`，`vc=-2.9323518410018137 m/s`，
  `kappa=228.80604377795845 m/s/mm`。源生成器也支持指定二次项，本轮二次项为零。
- 每个seed固定位置和标准化随机抽样，改变残差幅度不重新选择粒子；调压前后输入粒子完全相同，
  不拟合或归一化有限样本残差，不使用共同命中交集。
- 残差扫描束宽固定1 mm，标准差为0、1、3、10、30、60、100 m/s。
- 调压前：在相同中心速度下忽略源斜率设计反射器；调压后：按照已知源斜率重算反射器。
  只改变镜中间电位`1697.640102→1701.742647 V`及背板电位`2640.265686→2651.805603 V`。
  加速器电压、几何及加速器出口至反射器总距离642.742615 mm保持不变。
- 束宽比较使用相同外部几何和源斜率匹配；两区为`eta=0`，三区为既有锚点
  `eta=-1.0391326394747527`，各自重算反射器。不是两种结构分别全局优化后的比较。
- 使用脉冲起算TOF和公共直接质量峰FWHM分辨率；同时保存时间FWHM、分位宽、模式、尾部及分类计数。

## 残差阶段结论

|残差标准差（m/s）|调压后相对分辨率收益，三种子范围|
|---:|---:|
|0|+77102.7%～81814.4%|
|1|+8044.9%～9225.8%|
|3|+2687.8%～3116.6%|
|10|+739.5%～874.2%|
|30|+175.5%～221.9%|
|60|+48.6%～74.3%|
|100|+11.99%～36.03%|

例如seed20260827、残差1 m/s时，调压前后R为5099.32和475551.86，直接时间FWHM为
3.078386和0.032942 ns；主要KDE模式从2变为1。这里的很高R没有探测器响应、脉冲抖动、
横向像差或工程场误差，不能外推为仪器性能。

自动结论为`NOT_SUPPORTED`，精确含义是预先声明的组合条件中，低残差收益≥20%通过，
但最高测试残差下全部seed收益≤10%未通过；原因码
`GAIN_REMAINS_ABOVE_THRESHOLD_AT_MAXIMUM_TESTED_RESIDUAL`。不是软件失败，也不是否定调压有效。
支持低残差收益显著、随残差增大收益明显衰减；不支持把100 m/s处称为完全无效。
初始忽略斜率的工作点不是全局优化后的最强传统对照，因此不能单凭这些大比例宣称算法新颖或优于全部前人方案。
调压仅改变输入分布映射到时间的方式，没有降低源本身的随机残差。

## 束宽阶段结论

判据为三个seed均达到R≥25000且完整母样本轴向模型适格率为1。下表为连续已测通过点，
不是对点间连续区间的数学保证，也不是精确物理上限。

|残差（m/s）|两区通过至（mm）|两区首个失败点（mm）|三区通过至（mm）|三区首个失败点（mm）|
|---:|---:|---:|---:|---:|
|0|2.2|2.6|2.8|未达到|
|1|2.2|2.6|2.8|未达到|
|10|1.5|2.2|2.6|2.8|

零残差、2.2 mm时，两区R=33930～34502，三区R=109692～113720；
零残差、2.8 mm时，两区R=14352～14715，三区R=29647～31207。
残差10 m/s、2.2 mm时，两区R=24892～25976，三区R=38280～45062。
本轮支持指定三区工作点有更宽的已测接受范围；不能重复“两区接受上限只能1 mm”，
不能说三区2.8 mm已是极限。25000附近判定仍受有限样本和KDE影响。

## 自动化与失败闭合

单一命令自动顺序运行两阶段、绘图、写报告和manifest。技术失败停止并输出阶段、case及异常；
科学负结果不阻断下一项独立低成本比较。`--resume-from`仅在代码、配置、seed和数值环境一致时，
将已校验完成case复制至新run，旧run不修改；未完成case继续计算。测试覆盖故障注入、断点复用、
身份不匹配、文件损坏、缺少case、模型不可用事件及未知峰宽，避免空结果被视为通过。

完整矩阵复用验收run：`20260827_133059__analysis__python__ideal-source-comparison`，84/84 case全部
复用，没有重算粒子；复制和重新出报告/图耗时2.85秒，191项manifest校验通过。它只是恢复机制
验证，不是新增独立重复实验。L1及项目Static通过：315 tests，1 skipped。

首轮`20260827_131839__analysis__python__ideal-source-comparison`完成84计算后，发布manifest遇到
Windows命令行长度限制。现已改用run内相对输出路径并增加回归测试；该首轮保留为failed，
记录明确原因并通过failed manifest校验，不冒充成功。随后以新身份完整重跑并得到上述成功证据。

新增execution profile后，同文件哈希变化影响已retired的旧campaign状态查询。已确认旧campaign引用的
`validated_structural_candidate`内容完全未变，仅刷新活动retired索引的文件哈希；旧run内冻结合同、
campaign身份与结果均未改写，未重新授权任何商业模拟。35个本主题及旧campaign focused测试通过。

全仓L2已运行，但未全绿：integration的524 tests中2项失败，都指向既有
`family_runtime_implementation.json`内`run_artifact_support`哈希过期；其他已运行阶段通过。
基线HEAD `02d2653`中声明哈希为`1C9E0B3A1B8CB280E0D285D90172CFA4B1D0B381DB2B6FB5D8CA12CCCCFE6824`，
同一HEAD的`runtime/run_artifacts.ps1`规范文本SHA为
`C72A812D849223E1179175C481BCE1BFEEB92DC787B59E983D01BFB97C93B05C`。
这两个文件的worktree与HEAD均相同，证明不是本轮理想场入口引入；本轮没有修改integration或
静默刷新其运行身份。该既有问题独立记录，不影响本轮理想场计算及manifest，亦不表述为L2通过。

## CLOC审计

口径：`common/report_cloc_delta.ps1 -Base 02d265356fa3b35f70ac268672a26a6b8f9d581f -Current WORKTREE`，
CLOC 2.10。下列result是本主题待提交worktree，不含本Markdown。每个四元组依次为
`files / blank / comment / code`，零变化也列出；unclassified=0。

|分类|baseline|result|delta|
|---|---|---|---|
|total|1099 / 12797 / 6146 / 208711|1108 / 12962 / 6222 / 209918|+9 / +165 / +76 / +1207|
|production|836 / 8134 / 4748 / 149978|842 / 8248 / 4818 / 150875|+6 / +114 / +70 / +897|
|tests|263 / 4663 / 1398 / 58733|266 / 4714 / 1404 / 59043|+3 / +51 / +6 / +310|

|分类/语言|baseline|result|delta|
|---|---|---|---|
|total JSON|388 / 0 / 0 / 37554|390 / 0 / 0 / 37630|+2 / 0 / 0 / +76|
|total Python|451 / 10769 / 3347 / 127880|458 / 10934 / 3423 / 129011|+7 / +165 / +76 / +1131|
|total Lua|38 / 242 / 174 / 4348|38 / 242 / 174 / 4348|0 / 0 / 0 / 0|
|total MATLAB|105 / 965 / 2245 / 12661|105 / 965 / 2245 / 12661|0 / 0 / 0 / 0|
|total PowerShell|104 / 778 / 298 / 25884|104 / 778 / 298 / 25884|0 / 0 / 0 / 0|
|total SIMION_GEM|10 / 35 / 81 / 246|10 / 35 / 81 / 246|0 / 0 / 0 / 0|
|total TOML|1 / 4 / 0 / 24|1 / 4 / 0 / 24|0 / 0 / 0 / 0|
|total YAML|2 / 4 / 1 / 114|2 / 4 / 1 / 114|0 / 0 / 0 / 0|
|production JSON|384 / 0 / 0 / 37444|386 / 0 / 0 / 37520|+2 / 0 / 0 / +76|
|production Python|245 / 6686 / 2525 / 74514|249 / 6800 / 2595 / 75335|+4 / +114 / +70 / +821|
|production Lua|31 / 167 / 156 / 3559|31 / 167 / 156 / 3559|0 / 0 / 0 / 0|
|production MATLAB|67 / 506 / 1693 / 9001|67 / 506 / 1693 / 9001|0 / 0 / 0 / 0|
|production PowerShell|96 / 732 / 292 / 25076|96 / 732 / 292 / 25076|0 / 0 / 0 / 0|
|production SIMION_GEM|10 / 35 / 81 / 246|10 / 35 / 81 / 246|0 / 0 / 0 / 0|
|production TOML|1 / 4 / 0 / 24|1 / 4 / 0 / 24|0 / 0 / 0 / 0|
|production YAML|2 / 4 / 1 / 114|2 / 4 / 1 / 114|0 / 0 / 0 / 0|
|tests JSON|4 / 0 / 0 / 110|4 / 0 / 0 / 110|0 / 0 / 0 / 0|
|tests Python|206 / 4083 / 822 / 53366|209 / 4134 / 828 / 53676|+3 / +51 / +6 / +310|
|tests Lua|7 / 75 / 18 / 789|7 / 75 / 18 / 789|0 / 0 / 0 / 0|
|tests MATLAB|38 / 459 / 552 / 3660|38 / 459 / 552 / 3660|0 / 0 / 0 / 0|
|tests PowerShell|8 / 46 / 6 / 808|8 / 46 / 6 / 808|0 / 0 / 0 / 0|

完整过滤口径：

```text
extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;
excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;
excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;
language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;
production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);
tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|*Test.m|*.Tests.*;
unclassified=other_code_below_test_or_tests_path;
worktree_source=git_tracked_plus_nonignored_untracked
```
