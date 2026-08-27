# Paper 1 C4_J3：锁定三维预测合同

> `STATUS: BLOCKED_BY_C3_J3`

C4_J3只检验已冻结的三区 `improve / zero / worsen` 预测能否在**未参与模型、方向或候选选择**的三维锁定源粒子上复现。它不能恢复已暂停的J2主张，也不闭合公平二区/三区比较或投稿资格。

## 进入条件

1. 先发布C3_J3五件套，其中`stage_report.json`必须是`C3_J3 / PASS_CONTINUE`；没有该文件，分析入口必须在读取任何探测器结果前失败关闭。
2. 每个C4 case在启动前冻结`case_id`、source condition、三区身份、cohort salt、完整母cohort计数、最小检测计数，以及严格的预测分数`improve < zero < worsen`。
3. 三个真实SIMION run只释放同一批由该salt哈希得到的`locked_test`粒子ID；完整母cohort分母、pulse-eligible 完整覆盖、逐事件census、共同有效脉冲和直接峰形receipt必须保留。

## 唯一分析入口

`python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_c4_locked_prediction --c3-stage-report <C3/stage_report.json> --case <frozen-case.json> --output <result.json>`

入口只读取已完成run的`summary.json`和`run_manifest.json`，核验锁定ID、母cohort、有效脉冲、检测数、canonical direct-FWHM、尾部/模态、bootstrap区间和完整母cohort检测率。若“improve”靠降低母cohort检测率得到更窄峰，结果是`INCONCLUSIVE_REVISE`，不是PASS。

## 阶段结论

该入口的`PASS_CONTINUE`仅表示一个C3_J3方向族在一项冻结source condition的锁定三维cohort上通过方向、分母和传输防御。仍必须在两种source condition和预注册的结构/目标因子矩阵完成后，才能进入C5或主张任何结构优越性。每次结论仍须通过`record_paper1_stage_evidence.py`发布五件套。

禁止声明：J2恢复、三区一般优越性、source-weighted优越性、多质量、Candidate、Formal或JASMS-ready。
