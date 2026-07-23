# 四极杆迁移前小样本功能证据

> **DOC_STATUS: ARCHIVED_READ_ONLY**。本文冻结仓库采用 N=100 最低功能档以前的四极杆功能运行。
> 当前状态、资格和开放任务只以[`../PROJECT.md`](../PROJECT.md)及机器合同为准。

## RF-only与公共运行时

`transport_no_collision + official_fixed_25.ion`曾在COMSOL 6.4和SIMION 2020完成独立场、粒子推进、
统一事件表、manifest和GUI资产复验。

- SIMION：`20260722_233000__sim__simion__rf-transport__shared-runtime-n25__r02`，25/25到达；
- COMSOL：`20260723_054500__sim__comsol__rf-transport__complete-drive-n25`，25/25到达，四类
  canonical事件各25条；
- SIMION PA0/PA1/PA2在公共运行时迁移前后哈希相同。

这些运行证明当时的RF-only径向约束、轴向传输、公共杆阵列和状态链可执行，不构成当前Candidate、
碰撞冷却、质量过滤、机械几何或整机连接资格。

## 分段杆轴向加速

`20260723_071800__sim__comsol__rf-quadrupole-axial-acceleration__n25__r01`使用4段杆、0.4 mm绝缘
间隙和`0→-3 V`公共模阶梯。加速组25/25到达，平均末端能量5.0316 eV；相同分段几何、RF和零轴向
压降对照平均末端能量1.9949 eV，观测增益3.0367 eV。保存MPH曾完成GUI Compute及canonical状态
复核。

该运行只证明当时的COMSOL功能链，不证明SIMION独立实现、N=100功能档、分段优化、网格收敛或机械
资格。当前N=100双求解器状态只查公共家族机器合同。

## 质量过滤稀疏功能扫描

SIMION运行`20260722_231100__sim__simion__mass-filter__shared-geometry-n175__r01`对七个质量分别使用
25个配对粒子，在96、99、99.5、101.5、103、103.5和106 Th得到0%、32%、96%、100%、60%、40%和
8%的透过率。

COMSOL运行`20260723_002556__sim__comsol__mass-filter__rf-dc-n175`使用相同七质量和配对源，得到
4%、52%、92%、100%、60%、32%和8%的透过率。两求解器中心透过率均为1.0，最大端点透过率均为
0.08；最大绝对透过率差0.20出现在99 Th。

这些结果只保留“同一硬件几何可产生质量选择响应”的迁移前功能证据，不授权当前Candidate、质量
分辨率、稠密峰形、网格收敛或跨求解器数值一致性声明。
