# Paper 1 C0：理论与声明闭合

当前执行资格与下一道门槛只查[证据矩阵](evidence_matrix.md#基础与阶段)；本页维护阶段定义与进入条件。

本阶段冻结J2/J3的解释边界，未读取任何detector结果、未启动商业求解器、未改变524 Da Formal资产。

## 已闭合

- 目标同时包含条件均值间方差和条件厚度的一阶可修正残差；不得只以`J_perp`代表总峰宽。
- `J_perp,lin^min`和`F_lin`仅是固定工作点、固定事件拓扑、无界局部线性参考，不是物理下限或全局设计结论。
- 信赖域、事件拓扑、母cohort census、Liouville/发射度与无碰撞/无空间电荷边界已写入canonical理论。
- `paper1_stage_evidence.py`规定每个后续阶段必须原子发布五份stage文档，且结论枚举只能为
  `PASS_CONTINUE`、`FAIL_STOP`或`INCONCLUSIVE_REVISE`。

## C0结论

本记录定义理论／接口闭合的范围；其执行资格只由[证据矩阵](evidence_matrix.md#基础与阶段)维护。

## 禁止声明

- 不得把当前理论写成真实源、碰撞RF导引、空间电荷或实测性能结论。
- 不得把局部projector参考值写成分辨率下限或三区必然优于二区。
- 不得使用历史N=100结果作为锁定验证。

C0通过后只允许探测器盲source cohort和条件模型实现；三维优化或SIMION生产运行仍以C2闭合为前置门槛，
并须满足对应[阶段合同](../README.md#独立阶段合同)及证据矩阵的进入条件。本记录不单独授权运行。
