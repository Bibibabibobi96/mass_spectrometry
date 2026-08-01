# oaTOF空run与六极杆非标准artifact顶层闭合（2026-08-01）

## 判定

根README定义的`00_README.txt/formal/runs/archive/scratch`五类项目根入口足以表达当前职责，不增加
顶层`analysis/`或`comparisons/`。求解器无关分析、收敛比较和跨run比较都是一次运行；新产物必须在
`runs/<run_id>/`内冻结`run_config.json`、`summary.json`和`run_manifest.json`。只有当前正式结果可由
成功run选择到`formal/results/`；没有完整run身份的历史载荷进入具名`archive/`，不得事后补造三件套。

## oaTOF空run

`artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/`
`20260729_112000__sim__cross__vnext-n1000/`只含空`inputs/logs/results`目录，文件数和字节数均为0；
仓库只在前次审计中把它列为待核验问题，没有结果消费者，也没有活动COMSOL、MATLAB或SIMION进程。
该目录不是运行证据或可恢复运行，因此已删除空壳，没有生成或伪造三件套。

全量布局扫描随后发现另一个
`20260729_124516__gate__python__reference-analysis__baselines/`同样为0文件、0字节空壳；它也没有
消费者，按相同规则删除。两者都没有可归档载荷，保留空目录只会制造“曾完成运行”的错误身份。

## 六极杆非标准顶层

原`analysis/`含8个文件、22,828字节，仓库活动消费者为0；原`comparisons/`含3个文件、9,541字节，
三份`config/qualification/`记录直接冻结其路径、字节和SHA。11个文件均未删除，而是原字节迁入：

`artifacts/projects/rf_hexapole_ion_optics/archive/`
`20260801_233056__superseded__repo__hexapole-nonstandard-layout/legacy-layout/`

archive manifest逐项冻结原相对路径、字节和SHA-256，声明不提升原资格。三份活动资格记录只更新到
新archive精确路径，原SHA与字节不变；八份零消费者分析结果只承担历史追溯。项目根的`analysis/`、
`comparisons/`均已消失。

## 全量同类缺陷闭合

首次全量布局检查还发现六极杆`runs/`内一份H15分析目录含6个文件、99,632字节，但缺少
`run_config.json`、`summary.json`和`run_manifest.json`。其计划、四份来源run manifest和比较结果都是真实
历史证据，因此没有删除，也没有事后补造身份，而是逐文件冻结至：

`artifacts/projects/rf_hexapole_ion_optics/archive/`
`20260801_233929__failed-evidence__repo__hexapole-incomplete-analysis/`

`H15_result.json`不再把它表示为有效run，而以
`ARCHIVED_INCOMPLETE_RUN_NO_MANIFEST`、原记录ID和archive精确路径明确其证据边界。工程推进判定和原SHA
仍保留，但该目录不具备run身份，不能提升为数值收敛或正式资格。

集成项目另有14个早期预检、迁移或部分执行目录，共45个文件、124,744字节，均缺至少一项三件套且
没有活动Git消费者。它们原字节统一冻结至：

`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/archive/`
`20260801_233930__failed-evidence__repo__integration-incomplete-runs/`

manifest逐目录记录原ID、文件数、字节数和规范化清单SHA-256；这些材料只供历史诊断，不再冒充活动run。

同一全仓扫描还发现四极杆、八极杆项目根各有一个历史`analysis/`，碰撞冷却项目根有一个历史
`results/`；三者均无活动Git消费者。共21个文件、65,718字节按项目分别原字节冻结到
`quadrupole-nonstandard-layout`、`octupole-nonstandard-layout`和
`collision-cooling-nonstandard-layout`具名archive，逐文件记录字节与SHA-256。由此规则对所有项目
一致生效，不为六极杆保留特例。

布局门禁同时识别出7个历史scratch任务名不符合当前`task_id`合同。它们仍属于临时任务且无Git消费者，
所以只做原目录原字节重命名：补齐时间、受控scope和三段式分隔，不迁入run或archive，也不赋予新的
证据资格。

## 关闭条件

- oaTOF两个空run均不存在；
- 六极杆项目根只含五类规范入口，artifact布局门禁通过；
- 11个archive文件逐项字节/SHA复核通过，三份活动引用解析到新位置；
- 六极杆H15的6文件archive和集成项目14目录archive均通过数量、字节与SHA复核；
- 全仓`runs/`不再存在缺失三件套的目录；
- 全仓项目根不再存在`analysis/`、`comparisons/`、`results/`等非标准入口，scratch任务名全部合规；
- 全量布局结果为`ARTIFACT_LAYOUT=PASS PROJECTS=9 RUNS=522 ARCHIVES=15`；
- 后续分析/比较入口以普通run生命周期写三件套，不为结果类型扩展项目根。
