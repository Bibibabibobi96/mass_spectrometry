# 电子轰击离子源当前项目状态

本文件是项目当前状态的唯一权威。跨项目规则适用仓库根README；精确物理实现以
[`../comsol/ms_stage1_ei_source.m`](../comsol/ms_stage1_ei_source.m)为准。

## 当前状态

项目目前只有COMSOL实现，尚无正式或可提升候选资产。现存三个MPH与三张结果图等旧模型和结果
已冻结在`archive/20260719_212436__migration-snapshot__repo__pre-v2-layout/legacy-layout/`，
只能作为旧试验证据。新模型与结果必须统一写入`runs/<run_id>/{comsol,results,logs}`；未形成run config、summary和已复核manifest前，
不得从scratch提升或声明正式完成。

## 当前物理边界

现有脚本建立半径5 mm、长度100 mm的长细电离管，阴极至阳极电压70 V；默认中性气体密度为
`1e19 1/m^3`，常数电离截面为`2e-20 m^2`，电离能损失为15 eV。该模型只统计主电子的电离碰撞，
关闭二次电子释放，也不追踪独立重离子；后续级的离子出生位置只能视为电子束路径范围的近似。
因此它是电离产额可行性模型，不是完整EI离子源或已闭合的oa-TOF上游接口。

## 已知程序问题

- 入口仍硬编码COMSOL安装路径并自行调用`mphstart(2036)`，不符合当前仓库统一R2025b连接入口。
- 几何、气体、截面、粒子源与数值参数仍散落在MATLAB源码，尚无baseline/resolved机器契约。
- 现有结果提取以脚本端统计为主；正式化前必须确认关键结果节点、Study/Solver和判据在GUI中可见。
- 旧模型未按当前运行生命周期生成run config、summary和manifest，不能仅凭文件存在恢复正式资格。

## 下一步

1. 先迁移到统一MATLAB/COMSOL连接入口，并做不求解的加载/构建冒烟。
2. 把物理输入和数值模式拆为机器契约，明确“电离产额可行性”而非重离子生成的验收范围。
3. 用小样本重建候选，完成GUI Compute、结果提取和manifest后，再决定是否建立正式基线。
4. 与Wehnelt电子枪或oa-TOF连接前，单独冻结坐标、时间、粒子出生状态和接受度合同。

## 产物边界

项目产物根为`artifacts/projects/electron_impact_ion_source/`。archive继续保留旧试验；新运行进入
`runs/<run_id>/`；候选模型留在来源run，正式目录只有通过上述门禁后才能建立。
