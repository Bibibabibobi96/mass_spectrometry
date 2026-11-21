# 横向热源功能复现与用户GUI确认里程碑

DOC_STATUS: ARCHIVED_READ_ONLY

冻结日期：2026-10-16。用户本轮明确确认最新SIMION GUI加载／飞行检查没有问题，独立器件功能阶段暂封存。
该确认属于用户验收，不冒称Agent再次操作GUI、数值收敛或厂家装置资格。

## 冻结范围

当前基线为半径1 mm、全高5 mm、524 u／+1、纵向正值Gaussian能量5±1 eV、横向300 K参考Gaussian速度。
真实N100运行`20261016_121423__sim__simion__ion-processor-thermal-n100-auto`为97引出、3入口solver_stop；
全部母群、损失ID24/64/80及17组默认诊断保留。用户检查的是
`20261016_122844__test__simion__ion-processor-thermal-user-workbench/simion/processor.iob`。

本轮不删除最新加载包或唯一轨迹，不改变冻结运行。后续MR需求可能改变电压、几何、源或时序，应建立新身份，
不能覆盖此已验收参考，也不能把其约3892 eV锁定为后续接口要求。

## 原始当前文档快照

收缩前完整当前文档已按原字节保存为[PROJECT.txt](20261016__thermal-source-gui-accepted/PROJECT.txt)。
SHA-256：`64AE5FA03A1865C761392C6455190BF22FF05282827E49C62C60DF2731839049`。
快照包含此前源变化、ID20因果、损失边界、结构尺寸、诊断定义与公共退役记录；不是新的活动配置。
当前视图回到[PROJECT](../PROJECT.md)，MR接口准备归MR项目拥有。
