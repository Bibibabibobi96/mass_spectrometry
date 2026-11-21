# Ion Processor原流程闭合与联合母群验证

DOC_STATUS: ARCHIVED_READ_ONLY

本页冻结2026-10-17原流程闭合、联合N100及同场可加载包的里程碑。质心工作点通过，束团检测率仅19%，
没有全束匹配、能量验收或时间聚焦资格。当前选择与入口见[PROJECT](../PROJECT.md)。

## 输入权威与目标纠正

原OA运行名称虽含y360，其冻结materialization的`target_slow_turn_y_mm`实际为340mm。
误将名称当参数的360mm目标不能用于解释约20mm慢转折残差的物理根因。
新目标只改变该L字段，其他能量、源、几何、数值与判据逐项保持；不缩放源速度。

|对象|完整运行身份与证据|
|---|---|
|原OA目标|[20261014_134039__sim__simion__converging-te1-trusted-fullstep-resume-stage-013](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_134039__sim__simion__converging-te1-trusted-fullstep-resume-stage-013/results/two_prism_trial_materialization.json)|
|原OA束团对照|[20261015_040845__sim__simion__converging-y360-z002-gaussian-ey-sigma0p15-n100](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_040845__sim__simion__converging-y360-z002-gaussian-ey-sigma0p15-n100/results/two_prism_trial_materialization.json)|
|新目标权威|[20261017_171041__analysis__python__ip-original-mr-target-authoring](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_171041__analysis__python__ip-original-mr-target-authoring/results/target_revision.json)|
|原流程闭合|[20261017_172646__sim__simion__ip-original-target340-stages](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_172646__sim__simion__ip-original-target340-stages/summary.json)|
|实际联合N100|[20261017_181502__sim__simion__ip-closed-mrtof-joint-n100](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_181502__sim__simion__ip-closed-mrtof-joint-n100/run_manifest.json)|
|可加载联合包|[20261017_183222__analysis__python__ip-closed-joint-workbench](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_183222__analysis__python__ip-closed-joint-workbench/run_manifest.json)|

005908源专属能量参考保留：Ws=5.374387143093758eV/q，clean参考Ez=4359.320021348885、
Ey=5.213248384775397eV/q；有效慢势Ψ与实际电势分开记账。Prism消费实际yz速度向量，
不分别把Ey、Ez当独立可补偿输入；静电场中的K与H=K/q+φ也不混用。

显式重锚先按旧目标核验50个旧子运行，保留16候选／51计划和未执行051的完整放弃证据。
051的trial目录从未创建，旧parent与子进程停止证据进入原manifest；新实际飞行从052继续。
沿原P→S／返回相位→P和完整返回逻辑执行，不建第二控制器，不放开接地S2。

## 质心闭合

052／053／054分别提供S1／P1／P2实测响应，第17候选／055实飞通过原完整工作点判据。
S1=−26.988823504884756V，S2=0V，P1=369.1837635354015V，P2=−212.53723079548377V。

|实际残差|值|原容差|
|---|---:|---:|
|首次正镜转折y/mm|+0.083549980889|0.1|
|clean有效慢能量/eV/q|+0.008216214100|0.052489801182|
|慢转折y−340/mm|−0.020811814000|0.1|
|返回相位y/mm|+0.008540325653|0.1|

四项最大归一化残差0.835499808886；S阶段外层的0.208118140只统计后两项，不能称为四项最大值。
完整返回事件顺序通过、检测器命中；K=24.5，终端49快速半周期。原总fast-turn记录50含注入前一次，
不能据此认定多飞了一次设计半周期。累计17候选／55计划、54次实际飞行，预算未清零。

## 联合N100的明确负结果

源为原100母群的97颗实测出口状态；ID24/64/80上游未交接。下游所有97颗均有唯一终止，
检测19，损失78，超时0；分别为母群19%和已交接群19.587629%。
76颗为原生接触终止，79／95为`unexpected_post_return_mirror_turn`拓扑拒绝且`physical_collision=0`。
原日志未记录逐电极编号，现证据不能逐个判定具体电极或电压根因；接触位置和沿程原始记录均保留。

P2固定z=33mm观察面仅61颗到达，以下为这61颗的总体标准差，存在到达选择效应：

|P2平面量|均值|总体标准差|
|---|---:|---:|
|x/mm|−0.0646664|0.952075|
|y/mm|−9.3142255|2.04138|
|有符号yz角/deg|2.01688416|0.12677613|
|Ey/eV/q|5.43439062|0.68146261|
|Ez/eV/q|4364.4979226|38.1428823|

图中的冻结P2工程参考角2.00802287°属于原P2平面诊断；均值差+0.00886127°，
不能与新clean相位能量目标混比，也未声明全束角度或能量验收阈值。
不能只用19颗检测幸存者描述97颗初始束团。

首批10颗完成45秒资源观测后，原调度器自动启动余下87颗；2批全部完成、失败批次0。
CPU容量9但实测进程峰值40.93GiB，内存限制最大并发为1；reserve=0，压力为warning，未提前停止。

[默认诊断收据](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_181502__sim__simion__ip-closed-mrtof-joint-n100/results/diagnostics/diagnostics_receipt.json)
绑定Prism相空间、空间云、母群损失图及CSV。7个时刻由实际birth、4类事件中位数、实测寿命中点及末终止自动确定，
不手调固定时间。轨迹观测间隔0.1μs，积分仍Q8／最大0.004μs；插值仅在已观测支撑内进行。
81份逐损失JSONL恰覆盖78颗下游损失及3颗上游未转移，原始行和终止证据完整，无异常粒子删除。

## 可加载包与验证边界

[joint.iob](../../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_183222__analysis__python__ip-closed-joint-workbench/results/joint_workbench/runtime/joint.iob)
使用同一055场；五层场、四实例、三优先级探针、保存重载及98点接口场审计通过。
97颗FLY2为29381B，SHA为5426911515438849459CB0C76B78D37FB74375A0E3C2102B5DF52FD57420B6F4，
与N100源逐字节一致；20个分析器电压、15个IP电压、6D、原ID和时钟相同。
保留Q8、0.004μs、超时1634.1655525637068μs、K24.5及epoch7500.63364963072μs。
OA默认与IP两provider继续可选；没有操作GUI或对发布包另启Fly。该包复现上述有限接受度结果。

L1改动范围174路径通过；两项后续夹具隔离修复的原失败用例、RF19项、integration65项及并行文档检查通过。
最终L2实际退出0，MR静态1408项（10项跳过）；源码门禁不授予全束性能或GUI资格。
CLOC2.10以1745c194b3a3c18682da7ad87a49cdb42440ec63→WORKTREE计量混合工作树：
total378745→403405（+24660），production261075→273968（+12893），tests117670→129437（+11767）。
这不是本次窄修复的独立净增；完整语言／files／blank／comment／code及过滤由公共`report_cloc_delta.ps1`输出。

051及已用052／053／054响应场均通过公共owner机制退役PA／surface，合计释放129202550736B，
小证据和重建输入保留，最终055场继续保留。
误建的重复runs/runs轻证据包经完整同项目备份后公共退役1865362B，原错误owner／类别不改写；
New-RunPackage创建前检查规范项目根。上述治理与测试修复没有改变物理输入。
