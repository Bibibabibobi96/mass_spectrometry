# reflectron midgrid声明式campaign授权（2026-08-02）

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 授权范围

仓库所有者批准首个oaTOF声明式结构Candidate campaign。唯一开放原生轴为
`reflectron_midgrid_voltage`；固定524 Da、+1、N=100、粒子源seed `20260720`及common-random-number
配对。两行分别为理论名义值1628.8001 V和诊断值1600 V。

项目optimization envelope新增1600–1650 V窄范围。该范围覆盖既有1601 V真实COMSOL/SIMION/CAD
结构运行时验证和1628.8001 V耦合理论名义值，并仅保留小幅正侧诊断余量；它窄于catalog的静态安全
范围。campaign与单工况Candidate编译器都会在启动求解器前拒绝越界值。

## 执行与声明边界

活动表`config/experiment_campaign.json`在任何新行启动前设为`preregistered/authorized`，并冻结request、
science profile、solver numerics、变量catalog、optimization envelope、Candidate workflow和execution
profile的SHA-256。商业求解器并发固定为1、自动重试为0；全表预检先于首行启动，首个失败后停止，
不复用旧run。

本授权只允许N=100结构链执行与两行横向比较。成功不证明1600 V优于名义值，不形成分辨率、优化、
数值收敛或跨求解器等价声明，也不修改baseline、Formal资产或资格；任何晋升仍需独立事务和批准。
