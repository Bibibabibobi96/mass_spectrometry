# 无加速多极杆离散跟进

> DOC_STATUS: ARCHIVED_READ_ONLY
>
> Historical snapshot: statements are interpreted at the document date; current authority is the applicable active contract and current project/integration documentation.

## 范围与声明边界

本次按运行前冻结的合同，对四、六、八极杆无加速N=100工况完成：

- SIMION五臂各向异性矩阵：`A=(0.3,0.3,0.3) mm/80`、径向加密`R`、轴向加密`Z`、
  各向同性加密`I=(0.2,0.2,0.2) mm/80`和时间加密`T=(0.2,0.2,0.2) mm/160`；
- COMSOL在出口接口局部`0.20 mm`网格上比较`160→320 steps/RF period`；
- 所有比较使用同一N=100母样本、同一物理设计和预登记固定分箱合同；
- 统一图固定24个bin、200 DPI，并在同一项目内共享坐标范围。

本活动只评价求解器内部的离散敏感性。它不评价绝对精度、求解器优劣、跨求解器数值等价、碰撞、
空间电荷、N=1000、Candidate或Formal。

## 执行结果

SIMION 15个科学臂和COMSOL 5个新增科学臂均成功、清单校验通过、RF-on 100/100，未触发资源帽或
自动重试。四极杆SIMION锚点在成功前保留两个不可变失败父run：一次宿主中断、一次把活动预登记误作
可选evidence contract；二者均排除在科学分析外。首个四极杆分析run因冻结不存在的namespace
`__init__.py`失败，修正后的`__r02`为当前成功分析，失败run同样只保留追溯。

SIMION结果如下。表中百分比为RMS出口半径的求解器内相对变化，不是PASS阈值。

|项目|A→R径向|A→Z轴向|Z→I径向|R→I轴向|I→T时间|固定分箱时间状态|
|---|---:|---:|---:|---:|---:|---|
|四极杆|2.597%|0.246%|2.511%|0.333%|0.00595%|STABLE|
|六极杆|16.953%|1.077%|14.891%|0.999%|0.000529%|STABLE|
|八极杆|3.066%|0.309%|2.809%|0.051%|0.000133%|STABLE|

三项目的空间比较均有粒子跨越预登记固定分箱，因此空间状态均为`SENSITIVE`。径向是主要敏感方向，
其中六极杆最显著。`I→T`只支持“在当前固定工程分辨率下时间稳定”，不能升级为连续时间收敛。

COMSOL时间结果如下：

|项目|时间比较|RMS出口半径相对变化|固定分箱状态|
|---|---|---:|---|
|四极杆|0.20 mm，160→320|0.0807%|SENSITIVE|
|六极杆|0.20 mm，160→320|2.265%|SENSITIVE|
|八极杆|0.20 mm，160→320|3.980%|SENSITIVE|

三个COMSOL时间pair均有粒子跨越固定分箱，故时间收敛没有建立。SIMION的时间稳定不能替代COMSOL
时间证据；相反，两者共同说明数值结论必须限定到各自求解器和离散轴。

## 结果与图组身份

每个项目的机器结果登记在其`no_acceleration_followup/followup_result.json`。SIMION五臂图组位于：

- 四极杆：`20260731_011001__analysis__python__quad-noacc-followup-factorial__r02`；
- 六极杆：`20260731_011101__analysis__python__hex-noacc-followup-factorial`；
- 八极杆：`20260731_011201__analysis__python__oct-noacc-followup-factorial`。

每个run均包含`simion_exit_state_factorial.png`、figure JSON、factorial JSON、summary和已验证manifest。
COMSOL二臂图组分别位于`20260731_021001/021101/021201__analysis__python__*-comsol-t160-t320`。
每个run均包含`comsol_exit_state_pair.png`、figure JSON、pair JSON、summary和已验证manifest。

现有oaTOF三源横向图组
`20260731_030000__analysis__cross__source-triangle__n100`继续保持
`POSTHOC_DESCRIPTIVE / INCONCLUSIVE_DIAGNOSTIC_ONLY`。本次新增离散臂没有预注册新的
`SourceRevisionId`或下游binding，因此没有把它们事后接入oaTOF，也没有启动新的下游商业运行。

## 处置与后续

本轮总裁决为`INCONCLUSIVE_NUMERICAL_CONVERGENCE_NOT_ESTABLISHED`：功能传输保持闭合，但连续数值
资格没有闭合。当前优先级不是加速多极杆，也不是直接把COMSOL与SIMION差异解释为精度；应先建立
新的空间收敛活动，优先处理SIMION径向离散，且从六极杆开始。新活动必须在运行前冻结更细径向档、
资源预算、停止条件和下游可辩护误差尺度。

完整15臂SIMION加5臂COMSOL矩阵保持一次性审计，不加入每次实验的常规门禁。常规实验只自动生成
单run出口状态图和校验manifest。以下变化才触发重新预登记完整审计：机械几何、场/网格策略、轨迹
积分器或时间步政策、粒子源、handoff接口、固定分箱合同、求解器大版本，或Candidate/Formal里程碑。
这样保留方向敏感性证据，同时避免把分钟级SIMION和长时COMSOL成本施加到日常开发测试。
