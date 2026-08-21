# 2026-08-01 活动兼容层退役

DOC_STATUS: ARCHIVED_READ_ONLY

## 范围与授权

本次处置执行已批准的“内部兼容全退役”，目标是在不改变当前family物理输入和既有run证据的前提下，
删除已经被统一workflow取代的活动脚本、重复配置、旧路径和专用测试。删除内容仍可由公开Git历史恢复。
未删除或改写`artifacts/`、项目history、`.tmp/`、`scratch/`、求解器原生资产或既有manifest。

保留的公开兼容边界为`common/verify_lightweight.ps1`和四极杆
`simion/programs/quad_transport.lua`。通用历史reader、canonical粒子状态及标量`cell_mm`读取兼容继续保留。

## 已处置活动面

- 退役旧RF四极杆到oaTOF migration-equivalence公开执行链、两个旧connection profile、专用
  prereg/oracle/runtime binding、两份schema和对应测试；已完成结论只由Git、history与不可变run证据追溯。
- 退役四极杆项目内被当前family integration合同取代的S2/S3配置、validator、diagnostic runner、
  SIMION旧builder和专属测试。
- 将六个仍属当前连接的pulse/analyzer分析脚本及其测试迁入integration，不保留四极杆旧路径wrapper。
- 把三份重复的52项family依赖JSON改为49项公共base和每家2项overlay；删除依赖合同自快照。
  runtime binding schema v2分别冻结base/overlay，并为每次run生成51项`code_inventory.json`。
- 把六份runtime binding重复内嵌的10项implementation集合收敛为一个共享registry，并重建完整SHA链。
- 让六/八极杆L1/L2从current design profile resolver/compiler解析；删除旧顶层baseline、无模式名resolved
  副本、design/runtime alias、明确退役的出口加速evidence和六极杆旧N=100源别名/CSV。保留同名
  solver-numerics `baseline_finite_3d`及current `no_acceleration_full_length` evidence。
- 删除oaTOF handoff旧projection入口、公共零消费者路径字段、四极杆旧cross-solver检查器和粒子源常量别名。

## 验证与结果

未运行COMSOL、SIMION、MATLAB或CAD；本次只改变源码、机器合同、静态发布和无许可证门禁。完成的
求解器无关回归包括：integration 103项、公共multipole 293项、四极杆216项、六极杆76项、八极杆28项、
oaTOF 166项；项目registry freshness、JSON、PowerShell解析、Ruff和开发规范门禁均通过。L1/L2最终状态
以本提交的门禁输出为准。

CLOC使用仓库统一入口和cloc 2.10，口径为源码扩展名白名单；排除`.git/.venv/.tmp/artifacts/generated/
vendor/third_party/run(s)`、任意`docs/history/`及根`scratch/`；测试按活动入口、测试文件名和support角色分类。
基线`516ada149f5ea1fd38faa380f7c485cd1f61c9b3`到`WORKTREE`：

|类别|基线code|结果code|变化|
|---|---:|---:|---:|
|total|149055|136577|-12478|
|production|105964|96688|-9276|
|tests|43091|39889|-3202|
|unclassified|0|0|0|

按语言的total code变化为JSON `-5355`、PowerShell `-792`、Python `-6327`、MATLAB `-4`，其余语言为0；
文件数由912降至859。减少量主要来自关闭的旧执行链与重复机器合同，不来自删除历史或数值证据。
