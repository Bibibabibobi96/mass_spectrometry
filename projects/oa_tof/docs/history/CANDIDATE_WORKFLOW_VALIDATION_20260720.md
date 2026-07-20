# oa-TOF 集成候选工作流真实验证归档（2026-07-20）

> **只读历史档案。** 本文件冻结首次零改动候选端到端运行的失败、修复和成功证据。后续当前状态、
> 开放任务和正式身份只以`../PROJECT.md`、各软件实施文档及新运行manifest为准。
> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 验证范围与边界

目标是用正式参数编译一份物理内容零变化、文件身份隔离的候选合同，按共享N=100粒子表依次真实运行
COMSOL、SIMION和SolidWorks，再完成跨软件结构/合同验收。此次不评价分辨率或优化效果，不修改
`config/baseline.json`，不覆盖`artifacts/projects/oa_tof/formal/`，也不包含晋升步骤。

候选差异报告为`zero_change_reference_reproduction=true`。候选JSON因独立序列化而具有不同文件SHA，
但其解析内容复现正式baseline；运行计划记录的正式baseline SHA
`AE9645CF5C482952A0ED2CEEFE93986485FB37FF76812ED79ED1286ADE8C8731`在运行后保持不变。

## 失败与修复链

|阶段|证据/现象|归因|处置|
|---|---|---|---|
|工具链预检|受限环境内MATLAB报`File system inconsistency`；未创建候选run|商业GUI在沙箱内启动失败|按正式入口在非沙箱重试，MATLAB R2025b与SolidWorks版本门禁PASS|
|首次调用|误传不存在的`candidate_run_plan.json`；未创建run|操作者使用了错误文件名|改用冻结器实际输出`candidate_workflow_plan.json`|
|`20260720_111104__test__cross__zero-change-candidate__n100`|约2秒在COMSOL launcher失败，`ArgumentList`为空|集成runner硬编码Windows PowerShell 5.1，而共享启动器需要PowerShell 7的.NET API|runner固定使用`pwsh.exe`并增加回归测试|
|`20260720_111423__test__cross__zero-change-candidate-retry1__n100`|约124秒后MATLAB报告`OATOF_RUNTIME_DIR is required`|候选计划漏传固定粒子释放证据目录；不是数值求解器故障|计划把`OATOF_RUNTIME_DIR`路由到本次run的`comsol/`并增加隔离断言|
|GitHub lightweight gate|本地PASS，云端连续失败|Windows runner把同一临时目录表示为长路径和`RUNNER~1`短路径，测试错误使用字符串相等|改为现有项目根的文件身份比较，再校验未创建run的语义后缀|
|artifact布局复核|手工输入scratch最初使用非法scope `test`|task_id把activity误当成scope|保留内容并改名为`20260720_111104__cross__zero-change-candidate-input`；全局布局门禁随后PASS|

两份失败run均已由生命周期后端写成完整`failed/candidate_rejected`根summary和manifest，后续阶段为
`blocked`，未被重试覆盖。PowerShell、环境变量和路径别名修复由提交`b91b88b`固化。

## 成功运行

成功证据根为
`artifacts/projects/oa_tof/runs/20260720_111805__test__cross__zero-change-candidate-retry2__n100/`。
集成入口墙钟约1148秒，终态为`success/candidate_accepted_not_promoted`：

- COMSOL 6.4 build 293由MATLAB R2025b构建候选MPH，固定粒子100/100命中；独立回读验证
  `std1/std2`、`sol1/sol2`、335972个四面体、候选参数和结果节点均PASS。
- SIMION候选PA/IOB构建成功，IOB运行时合同PASS；SIMION N=100粒子表与COMSOL输入SHA同为
  `6287A54475008111A7F8AF87329F8AD08911066A564C508CFD424577D693229E`。
- SolidWorks从候选MPH输出25组件装配、零件和STEP，CAD报告PASS。
- 跨软件接受范围严格为`structural_build_and_contract`，`performance_claim_allowed=false`、
  `formal_modified=false`、`promotion_authorized=false`。
- 全局artifact布局门禁为`PASS PROJECTS=4 RUNS=6 ARCHIVES=4`。

## 固化经验

商业入口兼容性、运行证据目录和云端路径别名应由自动测试覆盖，不能依赖“此前单独脚本正常”的经验。
失败run必须保留并使用新run_id重试；结构合同通过不能外推性能达标。当前run已冻结候选baseline、resolved
合同和diff，但设计request/proposal仍位于scratch；若要允许长期清理scratch，应先将二者纳入不可变run
输入和manifest，再绑定通用execution profile。
