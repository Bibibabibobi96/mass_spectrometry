# oa-TOF 中栅电压候选运行时覆盖归档（2026-07-20）

> **只读历史档案。** 本文件冻结首个非零设计变量端到端候选的失败、修复、人工交互缺口与无人值守
> CAD闭合证据。当前能力和开放任务只以`../PROJECT.md`为准。
> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 范围与边界

唯一设计变化是`reflectron_midgrid_voltage: 1600 → 1601 V`。运行固定524 Da、N=100和传输目标，
只验收候选合同是否被COMSOL、SIMION与CAD真实消费；不评价分辨率或优化收益，不修改baseline、formal，
也不授权晋升。

## 失败与根因

首次运行`20260720_122645__test__cross__midgrid-voltage-candidate__n100`在COMSOL保存模型回读门禁FAIL：
候选合同期望`V_mid=1601 V`，MPH实际仍为`1600 V`。底层构建器在读取显式候选合同后又按历史理论路径
重算`V_mid/V_mirror/L_stage2`，静默覆盖候选值。修复后，显式`ContractPath`成为这三项参数的权威，
构建器只根据合同电压和长度重算实际场；无显式合同的历史位置扫描行为保持不变。

## 端到端重试与CAD交互缺口

重试`20260720_123942__test__cross__midgrid-voltage-candidate__n100__r01`完成COMSOL、SIMION、25组件CAD和
结构合同PASS，终态为`success/candidate_accepted_not_promoted`。但SolidWorks在STEP导入阶段读取到
失效的机器默认零件模板路径，弹出模态对话框；本次运行在所有者手工选择空模板后才继续，因此该run
本身不证明CAD无人值守。

共享桥接器随后改为在`LoadFile4`前临时绑定SolidWorks 2022安装目录中的空白`gb_part.prtdot`，用显式
`gb_assembly.asmdot`创建装配，结束后恢复并回读核对原用户设置；所有输入/输出路径同时规范为绝对路径。

## 无人值守闭合

`20260720_132856__test__cad__blank-template-assembly__n25`复用上述候选已导出的25个STEP，不重跑场或粒子：

- 25个STEP全部保存为SLDPRT，25个组件全部加入SLDASM；
- 装配保存错误/警告均为0；
- SolidWorks revision为`30.5.0`；
- `manual_interaction_required=false`；
- 模板路径和“总是使用默认模板”开关恢复回读PASS；
- run manifest收录28项输出并重新计算SHA后PASS。

因此`reflectron_midgrid_voltage`可进入当前N=100结构候选运行时覆盖。该结论只证明输入路由、模型构建、
保存回读和CAD装配闭合，不证明1601 V性能优于1600 V，也不改变formal。
