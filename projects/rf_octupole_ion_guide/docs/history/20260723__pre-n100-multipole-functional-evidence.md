# 八极杆迁移前小样本功能证据

> **DOC_STATUS: ARCHIVED_READ_ONLY**。本文冻结仓库采用 N=100 最低功能档以前的八极杆功能运行。
> 当前状态、资格和开放任务只以[`../PROJECT.md`](../PROJECT.md)及机器合同为准。

## L1与L2

- 理想L1运行`20260722_210401__sim__python__rf-octupole-family-contract__l1-n25`得到RF 25/25、
  0 V对照1/25。
- 二维圆杆筛选`20260722_180355__sim__comsol__rf-octupole-ion-guide-round-rod-screen__l2`选择
  `r_rod/r0=0.36`：杆半径1.44 mm、中心半径5.44 mm、相邻表面间隙1.2836 mm；边界归一化
  `A12/A4=0.0038734`、`A20/A4=0.0031532`。
- 谐波重建场运行`20260722_181611__sim__python__rf-octupole-ion-guide-round-rod__l2-n25`得到
  RF 25/25、0 V对照1/25，出口RMS半径0.5560 mm。

## 有限三维

COMSOL运行`20260723_052500__sim__comsol__rf-octupole-family-contract__complete-drive-n25`从入口端板
外侧释放25个粒子。RF组25/25到达外部检测面，零RF对照1/25到达；RF检测面RMS半径0.508183 mm，
杆区最大半径1.081394 mm。

SIMION运行`20260722_233002__sim__simion__rf-octupole-family-contract__shared-runtime-n25__r02`
得到RF 25/25、0 V对照1/25。SIMION与COMSOL出口RMS半径分别为0.629088和0.601705 mm，最大杆区
半径分别为1.007620和1.110295 mm。计数一致不等于网格收敛或数值等价。

## 分段杆轴向加速

COMSOL运行`20260723_072300__sim__comsol__rf-octupole-axial-acceleration__n25`使用4段杆、0.4 mm间隙
和`0→-3 V`公共模阶梯。加速和零轴向压降对照均为25/25，平均末端能量分别为4.9925和1.9881 eV，
观测增益3.0044 eV。

以上小样本只证明迁移时的功能贯通，不构成当前Candidate、N=100双求解器、优化、网格或机械资格。
