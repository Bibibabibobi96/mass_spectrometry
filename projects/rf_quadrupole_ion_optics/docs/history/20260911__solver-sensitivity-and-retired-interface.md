# 四极杆数值敏感性与旧接口记录

<!-- DOC_STATUS: ARCHIVED_READ_ONLY -->

> 只读历史快照，归档于 2026-09-11。当前状态与资格见 [PROJECT](../PROJECT.md)。

本次只整理文档，未重新运行求解器；以下保留整治前记载的结果及限制。
来源基线：`45a6741550aae5cbb009615896d16ef6d20618a2`。旧授权及“当前”均按原记录时点理解。

## SIMION 结果和旧路由

无加速N=100基线和全局cell `0.4→0.3 mm`空间敏感性档已在全部四段杆施加RF并按81.1 mm近接口
统计面计数；两档均为RF-on 100/100、zero-RF 21/100，RMS半径相对变化约`9.57%`。v3当前只授权
固定`0.3 mm`、`40→80`步/周期的时间敏感性档也已完成，RMS半径相对变化约`0.034%`。空间/时间
功能PASS不构成连续数值收敛；分段杆轴向加速baseline和N=100空间档均已完成，当前仅授权
出口孔板加速N=100 baseline和空间档均已完成，当前商业求解器授权已关闭。旧分段杆、
出口带孔接口板和显式多级证据只属历史，不代表当前PA收敛、与COMSOL数值等价或机械资格。接口
N=100双端100/100但相空间严格比较为FAIL。

RF四极杆离子光学→单次反射oa-TOF下游由本项目累积pulse_capture入口驱动，以COMSOL真实局部出口canonical
状态进入只读分析器；
SIMION未独立建立同等侧孔/连接器场。功能贯通不得解释为接口场或整机Formal闭合。

许可证不能处理SIMION 2026 `.wgem`时继续使用已验证的SIMION 2020 legacy-GEM路线；该公共开放项
不在项目软件文档重复维护。

## COMSOL 数值与物理边界

- 基线网格、RF步数与最长时间只来自COMSOL数值合同；生产入口不接受hmax或步数标量覆盖。
- 无加速N=100基线与局部`0.5→0.35 mm`空间敏感性档已在四段杆实体几何上完成；两档均为
  RF-on 100/100、zero-RF 21/100，RMS半径相对变化约`0.92%`。v3当前只授权固定`0.35 mm`、
  `80→160`步/周期的时间敏感性档也已完成，RMS半径相对变化约`0.20%`。没有连续量误差预算，
  空间/时间功能PASS不得改称连续数值收敛；分段杆轴向加速baseline已完成。首次N=100空间档在
  `MESH_COMPLETE`后仅因17.752 GB超过原17.180 GB进程树帽而失败，预算v7保留8.59 GB系统
  可用内存底线、将进程树帽调整为21.475 GB后，唯一人工替代运行仍升至21.835 GB，同时系统
  可用内存降至7.653 GB。空间收敛因此为`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不再重跑；
  出口孔板加速N=100 baseline已完成；空间档在`MESH_COMPLETE`后以17.454 GB超过17.180 GB
  进程树帽，记为`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`。结合上述替代运行经验不再抬帽，
  当前商业求解器授权已关闭。
- 分段杆轴向加速使用四段、0.4 mm绝缘间隙和公共模电势；出口带孔接口板加速与显式多级案例均由各自具名合同
  决定，不在MATLAB中维护第二份电势。
- 当前模型无碰撞；旧碰撞脚本不得恢复。
- 唯一授权的无加速COMSOL N=1000 bridge在7200 s边界只完成746/1000个逐粒子release构造；
  静电场已完成，但粒子求解未启动且无出口状态。该run按`interrupted`终结并保留release日志
  校验清单，campaign关闭且不自动重试，不能作为COMSOL N=1000结果。
- 单节点向量化phase release只完成了隔离的N=100诊断，结果为
  `EXECUTED_NOT_EQUIVALENT`：离散传输分类保持不变，但RF-on逐粒子状态未在预登记固定分箱下稳定，
  且312.606 s相对逐粒子release参考312.020 s没有性能收益。不得把该实验profile用于生产或
  N=1000；活动默认仍为逐粒子`ReleaseFromDataFile`。
- RF四极杆离子光学→单次反射oa-TOF的pre_pulse_interface_transport/pulse_capture/analyzer_transport是候选局部联合链，不修改下游Formal资产，也不证明
  接口场连续或整机Formal。
