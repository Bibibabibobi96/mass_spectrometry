# 六极杆迁移前小样本功能证据

> **DOC_STATUS: ARCHIVED_READ_ONLY**。本文冻结仓库采用 N=100 最低功能档以前的六极杆功能运行。
> 当前状态、资格和开放任务只以[`../PROJECT.md`](../PROJECT.md)及机器合同为准。

## L1与L2

- 理想L1运行`20260722_210400__sim__python__rf-hexapole-family-contract__l1-n25`得到RF 25/25、
  0 V对照1/25。
- 二维圆杆筛选`20260722_180121__sim__comsol__rf-hexapole-ion-guide-round-rod-screen__l2`选择
  `r_rod/r0=0.55`：杆半径2.2 mm、中心半径6.2 mm、相邻表面间隙1.8 mm；边界归一化
  `A9/A3=0.0023644`、`A15/A3=0.0028776`。
- 谐波重建场运行`20260722_181607__sim__python__rf-hexapole-ion-guide-round-rod__l2-n25`得到
  RF 25/25、0 V对照1/25，出口RMS半径0.4206 mm。

## 有限三维与连接器

COMSOL运行`20260723_052000__sim__comsol__rf-hexapole-family-contract__complete-drive-n25`从入口端板
外侧释放25个粒子。RF组25/25到达外部检测面，零RF对照1/25到达；RF检测面RMS半径0.528788 mm，
杆区最大半径0.902589 mm。

正长度连接器运行`20260723_054900__sim__comsol__rf-hexapole-connector__exit2-n25`只把出口接地管
从0改为2 mm，检测面由81.1移至83.1 mm；RF仍为25/25，零RF仍为1/25，RF出口RMS半径
0.523226 mm。该结果只证明参数化正长度连接器当时可执行，不证明2 mm优于直连。

SIMION运行`20260722_233001__sim__simion__rf-hexapole-family-contract__shared-runtime-n25__r08`
得到RF 25/25、0 V对照1/25。SIMION与COMSOL出口RMS半径分别为0.467682和0.524896 mm，最大杆区
半径分别为0.740731和0.820490 mm。计数一致不等于网格收敛或数值等价。

## 分段杆轴向加速

COMSOL运行`20260723_073100__sim__comsol__rf-hexapole-axial-acceleration__n25__r02`使用4段杆、
0.4 mm间隙和`0→-3 V`公共模阶梯。加速和零轴向压降对照均为25/25，平均末端能量分别为5.0103和
1.9823 eV，观测增益3.0280 eV。

以上小样本只证明迁移时的功能贯通，不构成当前Candidate、N=100双求解器、优化、网格或机械资格。
