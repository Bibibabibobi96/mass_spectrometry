# 2026-10-27 全仓架构与文档迁移验收

DOC_STATUS: ARCHIVED_READ_ONLY

本记录覆盖2026-10-26至27日的项目边界、文档与身份迁移。源实现提交为
[`6edf3028`](https://github.com/Bibibabibobi96/mass_spectrometry/commit/6edf30289efd324c13647fe8a98c9d038930549b)；
后续文档提交保存本记录和索引。当前规范继续从[仓库架构](../REPOSITORY_ARCHITECTURE.md)与[文档任务目录](../README.md)读取。

## 交付与边界

十个设计项目收敛为八个：四／六／八极杆合为[RF多极杆离子光学](../../projects/rf_multipole_ion_optics/README.md)的三个显式结构变体，
其余七个设计所有者保留。共同理论和领域实现随项目保存；通用执行机制留在common，实例与跨器件联合证据归integrations。
三变体各有直接入口，选择、变量范围和资格分别绑定；杆长由`rod_z_max - rod_z_min`派生，不强制不同设计同长。

16份设计profile、64份runtime profile和69行campaign维持各自科学范围；原有无效设计仍拒绝。
11份重复mode副本退出，原始粒子、几何及物理定义通过迁位与投影对照保留，未增加物理功能或资格。
旧活动项目及common/multipole目录退出，历史run继续使用原owner；166项迁位映射绑定原路径、固定Git源及SHA，原有504份冻结载荷保持原字节。
历史索引可维护，冻结正文保留其当时身份和资格；普通编辑通过Git追溯。

根README提供主要入口，docs/README负责完整发现。全仓规范、科学方法、软件经验、参考资料与历史分开；
项目状态、理论、软件操作和研究发表材料按实际所有者存放。可维护Markdown由112页变为119页，新增主要用于导航与历史索引；
最终篇幅、逐文件处置及新增资产另见[文档统计](../../../artifacts/projects/instrument_assembly/runs/20261026_181621__migration__repo__architecture-migration/results/final_document_counts.json)与
[处置清单](../../../artifacts/projects/instrument_assembly/runs/20261026_181621__migration__repo__architecture-migration/results/final_document_inventory.json)。

## 验证

| 层级 | 实际结果 |
|---|---|
| 完整L1 | 默认Git范围1224路径通过，1802.981秒 |
| 完整L2 | 33阶段通过；24份unittest摘要报告5277次，含54次skip，2316.159秒 |
| 暂存与格式 | 完整路径集合和ION Git对象一致；JSON值相等、PowerShell token不变；全部受管文本、文档、注册与派生新鲜度通过 |
| 科学与原生边界 | 保留原科学输入、结果及负结果；未新增PA/Refine/Fly或GUI验收，两项迁位MATLAB原生测试未执行 |

完整门禁使用Python 3.11，主宿主与PATH选择PowerShell 7.6.5／.NET 10.0.11；个别既有fixture固定系统宿主路径，
不把整轮概括为所有子进程同一版本。系统7.6.9下的CLR退出、收尾文件缺失及复制摘要不一致分别保留，未建立统一根因；
一次无终态对照记为中断、原因未定。冻结摘要不一致仍失败关闭，诊断附原实测值，未增加重试或放宽判据。
OA—MR配方／scope输入登记由42项owner回归验证；既有真实恢复证据保留其原范围，不追溯补封旧manifest。

[L1原始日志](../../../artifacts/projects/instrument_assembly/runs/20261026_181621__migration__repo__architecture-migration/logs/l1_final_ps765_before_commit.log)、
[L2汇总](../../../artifacts/projects/instrument_assembly/runs/20261026_181621__migration__repo__architecture-migration/results/l2_full_ps765_terminal_summary.json)
及格式等价性记录保存完整范围；统计为报告执行次数，未将失败诊断尾部重放重复相加。
软件门禁不替代集成项目仍开放的GUI／CAD或数值／物理资格。

## 规模与参考资料

官方CLOC 2.10，`b5cb7418 → 6edf3028`：total 374190→373762（−428），production 240492→238772（−1720），
tests 133698→134990（+1292）；文件1581→1531，实际脚本1208→1204。生产脚本代码增加232行、配置减少1952行，未测量圈复杂度。
原目标基线`3647bcae → 6edf3028`为total +99、production −1619、tests +1718。
完整语言四项指标及过滤口径见[架构净比较](../../../artifacts/projects/instrument_assembly/runs/20261026_181621__migration__repo__architecture-migration/results/committed_cloc/architecture_migration_cloc_committed.architecture_only.md)、
[原目标比较](../../../artifacts/projects/instrument_assembly/runs/20261026_181621__migration__repo__architecture-migration/results/committed_cloc/architecture_migration_cloc_committed.md)；
集成主题`6f37fbdc`累计范围由[最终提交报告](../../../artifacts/projects/instrument_assembly/runs/20261026_181621__migration__repo__architecture-migration/results/cumulative_cloc/final_integration_cloc.md)单列。
固定提交CLOC输入集指纹为`1f9d5a6c77d06f78be6b67d49c6ef6b9303183960f21b98662ef7a8632aced6a`，先前工作树采样按原时间与身份保留。

六份本地PDF共92,677,984字节，已迁入references/literature与references/software并逐份验证SHA；仍被Git忽略，原资料库参考书保留。
理论示意图随正文保存，仿真输出及本次生成报告归受管run。五个退役源目录只剩的342份Python字节码已清理，文件长度合计6,220,831字节，可从原Git源码重建；未删除研究模型或输入。
完整迁位、文件身份与最终39项核对见[受管证据](../../../artifacts/projects/instrument_assembly/runs/20261026_181621__migration__repo__architecture-migration/summary.json)。
