# 八极杆源模型描述性比较

<!-- DOC_STATUS: ARCHIVED_READ_ONLY -->

> 只读历史快照，2026-09-11 归档。当前权威：[PROJECT](../PROJECT.md)。

来源基线：`45a6741550aae5cbb009615896d16ef6d20618a2`。文档整治保留原记载，未重新运行求解器。

## N=1000 比较记录

- N=1000 平面冻结源与独立轴向体积快照的 SIMION 成对传输已完成，并由 recovery analysis run
  `20260830_212610__analysis__python__oct-source-model-comparison-recovery__n1000` 发布；恢复只重做 Python
  分析与绘图，未重跑求解器。两臂均为 1000/1000 传输。体积快照在源端为同刻释放、z RMS 0.6251 mm、
  vz RMS 49.2820 m/s、动能 RMS 0.1005 eV，且 z--vz Pearson r=-0.01154；平面源的 z 宽度为零、连续
  birth-time 跨度非零。体积源出口空间 RMS 为 0.4169 mm（平面 0.5381 mm）、角 RMS 为 1.3490°
  （平面 3.2660°），实际墙钟 120.9 s（平面 128.8 s）。这是 source-model 的描述性对比，不构成
  数值收敛、探测器、Candidate 或 Formal 结论。
