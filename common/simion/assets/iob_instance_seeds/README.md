# SIMION IOB 实例种子

The GUI-created one-to-ten-slot Workbench containers are installed under `src/msplatform/backends/simion/resources/`. This directory retains the original large placeholder PAs. Instance-count and no-empty-slot rules:
[SIMION 实现入口](../../README.md)。种子只提供容器结构，不定义器件、电极或项目资格。

每个槽使用不同的本地 `iob_seed_placeholder_NN.pa0`。SIMION 会让引用同一文件名的实例共享 PA
对象，因此不同占位文件使构建器可以分别替换各槽的运行 PA 路径。

## 使用方法

1. 根据实际实例数选择对应的编号种子，不依赖本页列举的某个项目当前拓扑。
2. 把种子与该实例数实际引用的占位 PA 复制到运行目录，再由消费者构建器替换所有连续槽。
3. 在 run artifact 路径保存派生 IOB，验证所有槽均指向预期运行 PA，没有残留占位实例。

构建时不需要 GEM 或 Fly2 导出。运行不得原地修改本目录种子；具体实例位姿、PA 来源及验收由
消费者的冻结输入和验证合同负责。

The byte-identified 1–10 IOB containers now live only in `src/msplatform/backends/simion/resources/`; use the canonical structural-seed selector. The existing large placeholders remain here for the original one-slot helper and frozen consumers; the package geometry builder creates private neutral placeholders instead.
