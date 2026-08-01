# oaTOF 旧身份产物迁移与减容审计（2026-08-01）

## 目标与判据

把行政改名前的`artifacts/projects/oa_tof/`无兼容分支地迁入当前正式项目根，同时保持旧run manifest
字节、recorded project identity和原声明边界。迁移闭合要求全树SHA-256一致、旧顶层根消失、SIMION
与SolidWorks从新位置真实加载；减容另行按manifest裁剪可重建重型载荷，不以文件大小单独授权删除。

## 身份与迁移结果

- 旧身份：`oa_tof`；当前身份：`single_reflection_oa_tof_mass_analyzer`；
- archive ID：`20260801_130003__migration-snapshot__repo__oa-tof`；
- 唯一载荷：
  `artifacts/projects/single_reflection_oa_tof_mass_analyzer/archive/20260801_130003__migration-snapshot__repo__oa-tof/legacy-project-root/`；
- 迁移前盘点：6,920个文件、49,605,635,380字节；目的端全量SHA-256复核通过；
- 旧顶层`artifacts/projects/oa_tof/`已不存在；descriptor为`archived_verified`，没有旧路径fallback；
- 16条旧manifest身份异常保持原样并强制保留，涉及历史Formal输入版本差异、缺失的早期装配引用、
  PA9输出哈希差异及早期scratch模板缺失；本次没有改写旧manifest或据此提升资格。

## 嵌入引用实证

- SIMION：迁移后IOB从新archive加载`flight_tube_ground.pa0`、`reflectron.pa0`、`accelerator.pa0`和
  `detector_ground.pa0`四个实例，实例顺序正确，trajectory quality为8，状态`PASS`；IOB只保存相对
  PA名，没有旧artifact绝对路径。
- SolidWorks 2022：迁移后`oa_tof__model_physical_components.SLDASM`以revision `30.5.0`打开，
  errors=0、warnings=0；25/25个组件全部解析到新archive的`formal/cad/oa_tof__model_parts/`，缺失引用0。
  旧PowerShell PIA验证器在COM类型库调用处失败，已由仓库既有pywin32自动化路径的单一Python验证器
  取代，不保留双实现。

## 独立大文件清理

迁移完成后重新冻结全树并生成独立裁剪计划。规则只允许删除`runs/<run_id>/`非冻结容器中的可重建
COMSOL/SIMION/CAD原生二进制，以及旧根`scratch`文件；`formal/`、旧`archive/`、冻结/input/snapshot
容器、v2已选择输出、manifest身份异常、数值结果、canonical states、报告、图和日志均保留。

|处置|文件数|字节数|
|---|---:|---:|
|run内可重建求解器/CAD二进制|973|43,802,116,138|
|非权威scratch文件|1,217|10,500,273|
|合计删除|2,190|43,812,616,411|
|保留|4,730|5,793,018,969|

实际释放43,812,616,411字节（40.804 GiB），迁移载荷减少约88.3%。事务先逐文件复核SHA并移入同卷
`.prune-quarantine`，完成日志后才删除；`pruning_manifest.json`终态为`complete`，quarantine已清空，
archive manifest发布`deletion_performed=true`。裁剪后的保留清单及哈希复核为`PASS`。部分旧scratch
空目录因Windows ACL拒绝删除而仍可见，但其中没有文件、没有保留字节，也不构成旧定位fallback。

## 边界与后续

本审计不删除当前oaTOF Formal或旧Formal快照，不重新评价任何历史结果。仓库级artifact布局检查仍会
报告本任务之外的当前树问题：六极杆根的`analysis/`、`comparisons/`顶层目录，以及oaTOF当前
`20260729_112000__sim__cross__vnext-n1000`运行缺三件套；后者在其运行/恢复状态明确前不得清理。
