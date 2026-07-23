# 电子轰击离子源当前项目状态

本文件是项目当前状态的唯一权威。跨项目规则适用仓库根README；物理输入以
[`../config/baseline.json`](../config/baseline.json)为准，数值与证据语义以
[`../config/numerical_modes.json`](../config/numerical_modes.json)为准，MATLAB只能消费
解析后的[`../config/resolved_model.json`](../config/resolved_model.json)。仓库执行注册使用
统一[`../config/execution_profiles.json`](../config/execution_profiles.json)结构。

## 当前状态

项目目前只有COMSOL实现，尚无正式或可提升候选资产。现存三个MPH与三张结果图等旧模型和结果
已冻结在`archive/20260719_212436__migration-snapshot__repo__pre-v2-layout/legacy-layout/`，
只能作为旧试验证据。新模型与结果必须统一写入`runs/<run_id>/{comsol,results,logs}`；未形成run config、summary和已复核manifest前，
不得从scratch提升或声明正式完成。

## 当前物理边界

当前baseline定义长细开孔电离管、阴极—阳极加速场、中性气体、常数电离截面和固定电子释放状态。
该模型只统计主电子的电离碰撞，关闭二次电子释放，也不追踪独立重离子；后续级的离子出生位置
只能视为电子束路径范围的近似。因此它是电离产额可行性模型，不是完整EI离子源或已闭合的
oa-TOF上游接口。具体数值不在本文复制，避免与机器合同形成第二真值。

## 已知程序问题

- 源码已移除COMSOL安装路径和`mphstart`，只能由仓库统一R2025b连接入口运行。运行
  `20260722_120000__test__comsol__build-only-smoke`已在真实MATLAB R2025b/COMSOL 6.4连接中完成
  几何、网格、静电和CPT Study/Solver树构建并保存隔离MPH，未运行静电或粒子求解器；三件套manifest
  复核PASS。该结果只关闭构建入口风险，不提升候选或Formal资格。
- 已建立`baseline physical inputs + numerical mode -> resolved`单向链；Python解析器拒绝身份、
  单位字段、范围、未知模式和证据粒子数误用，MATLAB入口无旧数值回退。
- 跟踪的resolved为`build_only_smoke`，低N只验证合同读取、几何/网格/物理/Study树构建和GUI参数
  绑定；它明确不具备Candidate证据资格。
- 现有结果提取以脚本端统计为主；正式化前必须确认关键结果节点、Study/Solver和判据在GUI中可见。
- 旧模型未按当前运行生命周期生成run config、summary和manifest，不能仅凭文件存在恢复正式资格。

## 下一步

1. 使用`functional_reference`和最低N=100完成GUI Compute、结果提取与manifest；在此之前不建立
   Candidate或Formal。
2. 复核实际求解输出粒子数与请求证据粒子数的一致性，再允许功能结果进入Candidate评审。
3. 与Wehnelt电子枪或oa-TOF连接前，单独冻结坐标、时间、粒子出生状态和接受度合同。

## 产物边界

项目产物根为`artifacts/projects/electron_impact_ion_source/`。archive继续保留旧试验；新运行进入
`runs/<run_id>/`；候选模型留在来源run，正式目录只有通过上述门禁后才能建立。
