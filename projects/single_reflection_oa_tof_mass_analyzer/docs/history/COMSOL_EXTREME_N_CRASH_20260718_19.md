# COMSOL 极小粒子数原生崩溃调查归档（2026-07-18—19）

> **只读历史档案。** 本文件冻结N=3至首次N=21阈值测试阶段的完整调查过程。文中的“当前”按
> 归档时点解释；后续边界、绕行和开放任务只以`../PROJECT.md`、`../COMSOL.md`及artifacts中的
> 新运行manifest为准。`DOC_STATUS: ARCHIVED_READ_ONLY`

## 现象与受控排除

首次五质量最小门禁在10 Da、N=3的`std2` Study Compute中连续触发`csxmesh.dll`访问冲突；524 Da、
N=3和500 Da、N=3均复现，证明低质量速度和新时间窗口不是必要条件。500 Da案例完成参数、释放表、
分段时间窗和旧解处理后仍崩溃；重建`sol2`、限制单核、切换Windows native allocator和完整Windows
重启均未消除。崩溃时仍有约23—35 GB可用物理内存，因此不符合常规OOM特征。

对`clearSolutionData`和`pp1`重写分别做关闭对照后，N=3仍在相同初始化路径失败。故在本阶段已排除
质量、时间窗、常规OOM、线程数、分配器、是否清旧`sol2`以及是否重写`pp1`是必要条件。不能由这些
排除项继续外推COMSOL内部根因。

## 阶段矩阵

|案例|唯一关键差异|结果|
|---|---|---|
|正式524 Da、保存的N=100|零改写，只运行`std2`|PASS，367.3 s|
|524 Da、N=3|不清`sol2`|FAIL，约66 s|
|524 Da、N=3|不清`sol2`且不重写`pp1`|FAIL，约64 s|
|524 Da、N=100候选路径|重导入100粒子表|PASS，100/100，粒子321.74 s|
|500 Da、N=100|改质量、时间窗和释放表|PASS，100/100，粒子318.05 s|
|500 Da、N=40|计划冒烟样本数|PASS，40/40，粒子295.73 s|
|500 Da、N=21|首次二分阈值点|FAIL，墙钟93.1 s，`csxmesh.dll+0xd086`|

N=21在模型加载、GUI输出时间配置、释放文件写入和旧解策略记录完成后，于Study Compute中发生
`EXCEPTION_ACCESS_VIOLATION`。JVM报告原生帧`csxmesh.dll+0xd086`，随后LiveLink只得到
`StudyClient.run`的`APIEngine.runMethod`空指针。这与首次模型打开的`mphload Not connected`瞬态不是
同一失败点，也不满足共享启动器的可重试白名单。

## 阶段结论与证据

截至本归档点，COMSOL 6.4 build 293在当前模型的极小粒子数路径存在可重复的原生网格/solution-mesh
初始化故障。已知N=3和N=21失败，N=40、N=100及更大样本成功；因此阻塞已可用N>=40绕开，但最小
成功整数、区间是否严格单调以及内部无效引用来源仍未证明。

N=3证据位于`artifacts/projects/oa_tof/runs/candidate_gate/`的具名运行目录。N=21证据位于
`runs/candidate_gate/extreme_n_threshold_20260719/N21/`，包括固定ION、ReleaseFromDataFile中间表、
任务报告、结构化摘要、JVM原生崩溃日志和失败manifest。后续阈值测试必须使用新的独立N目录，不得
覆盖本阶段证据。
