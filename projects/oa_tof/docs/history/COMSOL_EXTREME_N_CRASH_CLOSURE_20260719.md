# COMSOL 极小粒子数原生崩溃调查关闭归档（2026-07-19）

> **只读历史档案。** 本文件冻结N=21之后的边界收紧、干扰项辨别、工程绕行验证和停止调查决定；
> N=3至首次N=21阶段见`COMSOL_EXTREME_N_CRASH_20260718_19.md`。后续当前状态、重启条件和绕行只以
> `../PROJECT.md`与`../COMSOL.md`为准。`DOC_STATUS: ARCHIVED_READ_ONLY`

## 调查目标与固定条件

目标不是证明COMSOL内部源码根因，而是判断极小N失败能否稳定绕开，并避免把启动器、沙箱或
LiveLink故障混入粒子数阈值。边界序列固定为500 Da、种子20260713、正式`sol1`静电场、同源
ReleaseFromDataFile、正式分段输出和每个N独立LiveLink进程。长期入口为
`tests/comsol/run_extreme_particle_count_case.ps1`；每次运行独立写`case_summary.json`、失败或成功
manifest、任务报告、ION/中间释放表以及可用的JVM原生崩溃日志。

## 完整边界矩阵

|求解N|运行阶段|结果与证据性质|
|---:|---|---|
|3|Study/solution-mesh初始化|多质量复现原生FAIL；质量、时间窗、清旧解和重写`pp1`均非必要条件|
|21|Study/solution-mesh初始化|`csxmesh.dll+0xd086`原生FAIL，阈值证据有效|
|25|Study Compute|`Xmesh.assemInit`原生FAIL，140.76 s，阈值证据有效|
|27|Study Compute|`Xmesh.assemInit`原生FAIL，93.94 s，阈值证据有效|
|28|Study Compute|`Xmesh.assemInit`原生FAIL，92.70 s，阈值证据有效|
|29首次|结果提取|Study已返回解尺寸；首次`mphparticle(t=0)`时JVM GC线程原生FAIL，415.52 s|
|29复跑|任务配置|设置分段输出表达式时JVM GC线程原生FAIL，未进入Study，不具阈值判定资格|
|30有效复跑|全链路|30/30 PASS；粒子阶段295.58 s、完整运行437.94 s，manifest复核通过|
|40、100及更大|全链路|已测案例均PASS；后续正式检查统一N=100，统计统一N=1000|

N=25/27/28的结构一致失败支持极小N与solution-mesh初始化有关，但N=29两次在不同阶段失败，且首次
Study已经完成。因此不能把N=30解释为严格、确定且只由粒子数控制的内部阈值，也没有证据把原因断言为
某个具体闭源求解器实现。N=31--39和其他粒子表未测试，不需要为工程绕行补齐。

## 已排除项与启动干扰

受控对照排除了质量、时间窗口、常规物理内存不足、线程数、Windows native allocator、是否
`clearSolutionData`、是否重写`pp1`和完整Windows重启是必要条件。崩溃时仍有约23--35 GB可用物理
内存，故不符合常规OOM特征；这些排除不能继续外推内部根因。

首次N=30尝试在任务报告创建前被会话中断；若干后续尝试停在MATLAB/LiveLink启动阶段，没有进入项目
脚本或Study。`extreme_n_threshold_20260719_retry4`的launcher stderr显示用户`.comsol`配置/Tomcat
日志拒绝写入；在允许写该目录的环境中，`retry5`完成30/30。因此这批启动失败属于编排沙箱权限，
不能计入N=30求解器FAIL，也不证明用户COMSOL配置损坏。

## 绕行验证与适用边界

当前CPT只包含`ReleaseFromDataFile`、外加静电场的`ElectricForce`和探测器`Wall/Freeze`，没有空间
电荷、库仑相互作用、粒子间碰撞或其他集体效应。同一种子下N=3与N=30表的前三行完全相同；成功的
N=30和N=40解中，前三个粒子的TOF、落点、初始条件和能量在CSV记录精度下均为零差。因此逻辑上
只需少量粒子时，可求解统一N=100承载集合后仅分析目标前缀ID，并同时记录求解N和逻辑N。

该绕行只在粒子相互独立时成立。若加入任何集体效应，承载集合会改变目标粒子的运动方程，必须停止
截取复用并重新验证。绕行证明生产工作不受阻，不证明COMSOL 6.4 build 293的原生不稳定已经修复。

## 证据位置与停止决定

N=21证据位于`artifacts/projects/oa_tof/runs/candidate_gate/extreme_n_threshold_20260719/N21/`；
N=25/27/28/29及N=29复跑分别位于同级具名`..._n25`、`..._n27`、`..._n28`、`..._n29`和
`..._n29_repeat`目录；有效N=30证据位于`..._retry5/N30/`。失败记录保留原生`hs_err_pid*.log`和
结构化摘要，成功记录保留输出CSV和通过复核的manifest；不同案例不得互相覆盖。

2026-07-19决定停止主动深挖：当前N=100/N=1000合同完全绕开问题，小N没有生产需求，继续扫描不能
提高现阶段模型可信度。只有PROJECT列出的条件出现时才重新启动；届时创建新的日期化调查和运行目录，
不得回写本归档或从N=3开始重复已经完成的排除矩阵。
