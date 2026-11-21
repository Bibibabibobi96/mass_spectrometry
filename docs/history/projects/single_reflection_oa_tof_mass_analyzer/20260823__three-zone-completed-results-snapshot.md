# 2026-08-17 三区加速器完成结果快照

DOC_STATUS: ARCHIVED_READ_ONLY

> `DOC_STATUS: ARCHIVED_READ_ONLY`

本文件逐字保存已完成的三区理论、真实 PA 验证和源臂敏感性结果。它是历史证据，不是当前 Formal
参数或活动入口；公式与实验口径仍以对应理论文档、run manifest 和项目机器合同为准。

针对该先导现象的三区加速器假说现已收归
[`三区理想理论与隔离验证漏斗`](../theory/three_zone_accelerator_ideal_theory.md)。它只运行精确一维解析时间和
冻结cohort，不调用SIMION、COMSOL或CAD；可选T4c的32,955仅是人工授权后的解析外层网格基数，
不是默认运行量或性能指标。现有双区resolved/profile不能静默复用为三区工程身份，任何真实场迁移必须
另开Candidate；当前Formal、baseline和资产不变。外部文档问题与处置见
[`2026-08-17审阅`](20260817__three-zone-accelerator-external-document-review.md)。

2026-08-17 canonical solver-free链执行了`T0,T1,T2,G1,T3,T4a,T4b,G2,T5`，未执行可选T4c。
T2最佳可行二区在2.2 mm cohort上的population sigma/直接FWHM为
`0.8159038773341178/0.679286964277992 ns`；冻结三区primary为
`d1=3.25 mm, l23=17.0 mm, lambda=0.30, DeltaV1=250 V`，场对比度
`2.826764127118471`、尺度化条件数`561.8473678`、尺度化
`Gamma3=1.12487848e-4`，且因`l23`命中域上界而是boundary-limited。T5的2.2 mm sigma/FWHM为
`0.18240109086706416/0.14113517445224488 ns`，相对最佳二区改善`77.6443%/79.2230%`；
1.0 mm sigma/FWHM为`0.004970459371531842/0.003840889778672363 ns`，两种宽度的sampling
差分别为`0.7647%/0.6353%`。结论为
`PRIMARY_CONFIRMATION_PASSED_OVER_BEST_TWO_ZONE`，canonical T5 run为
`20260817_122700__analysis__python__three-zone-t5`。精确口径与限制只查上述理论权威。

T5→三区`CANDIDATE_ONLY` resolved编译器、region-field schema v2和保持旧`0..19`映射且仅新增
电极ID `20`的拓扑已进入真实SIMION PA验证。二区5.1 mm与三区11.9 mm分别采用1+4个整形环；N=1
原生路径授权后，完整2.2 mm分层N=100得到100/100探测、pulse-relative
`sigma=0.2035735674 ns`、直接`FWHM=0.2338558848 ns`、质量`R=66988.23`、单峰。对应父run为
`20260817_235900__sim__cross__three-zone-segmented-rings-real-pa-full-width__n100`。这证明三区
理论收益在真实PA场中仍显著存在，但数值只是100 Th、N=100、Functional/CANDIDATE_ONLY证据；未做
COMSOL/CAD、N=1000、网格收敛或工程包络资格，不能改变524 Da Formal状态。

随后在同一真实PA、几何、数值、经验`z`点和100个ID上完成四个描述性源臂的顺序敏感性分解：
`affine_zvz_fixed_10eV_transverse_collapsed`、`observed_zvz_fixed_10eV_transverse_collapsed`、
`observed_z_vz_energy_transverse_collapsed`和`full_observed_6d`。每个N=1门均1/1探测并授权同臂N=100，
四个N=100均100/100探测；canonical顺序比较run为
`20260817_235946__analysis__python__three-zone-source-sequential-attribution__n100`。对应`sigma/FWHM/R`依次为
`0.0919962629 ns/0.1201946242 ns/130335.42`、
`0.8197245483 ns/2.4711425665 ns/6339.43`、
`0.8197190662 ns/2.4714356728 ns/6338.67`和
`0.8542897552 ns/2.5829468539 ns/6065.03`。以首尾总退化为分母，逐ID observed-affine `z-vz`偏离、逐粒子能谱
和完整横向状态的顺序份额在sigma上为`95.46563%/-0.00072%/4.53509%`，在直接FWHM上为
`95.46019%/0.01190%/4.52791%`。残差审计进一步表明，重新最小二乘匹配affine均值/斜率后仍有
`95.7478586%`的原残差均方，2—6阶多项式只捕获该non-affine/stochastic scatter的`0.92%—1.14%`。
这是冻结三区设计、100 Th、单次N=100的`FUNCTIONAL_ONLY`
敏感性结果；它不证明非线性不可通过重新编译并联合优化加速器与反射器来补偿。完整公式、权威、
run/manifest和理论升级问题集中见
[`history/20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md`](20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md)。
