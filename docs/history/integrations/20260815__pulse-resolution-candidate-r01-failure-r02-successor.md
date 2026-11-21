# pulse-resolution candidate r01失败与r02 successor

DOC_STATUS: ARCHIVED_READ_ONLY

`pulse_resolution_direct_candidates_v5_r01`的sequence 2完成N=100 SIMION Fly、分析与parent publication，
实际handoff/detector为`62/52`；随后paired receipt注册失败。失败不是场、缓存或solver问题，而是
`_screening_arm`仍读取已淘汰的`tof_since_pulse_us`列。当前官方checkpoint及r09 baseline receipt内嵌行
统一发布`pulse_effective_elapsed_us`，它已经是canonical pulse-effective elapsed，不需要从绝对仪器时钟
二次派生。seq2 parent manifest SHA-256为
`C7673F492D2B78BCE668A73C99B0BF04522B43CFF71474B58DC5007CC047EA32`。

r01 sequence 3在SIMION前因同campaign已有manifest但缺execution receipt而失败关闭；sequence 4未启动。
r01全部身份停止复用。最小修复只把paired screening arm的TOF字段改为
`pulse_effective_elapsed_us`并用既有真实checkpoint回归；没有增加第二时钟或重新推导。

successor campaign为`pulse_resolution_direct_candidates_v5_r02`。科学源、三种场、几何、反射器、N=100
ordered prefix、r09 baseline evidence、脉冲时钟与数值设置均保持不变；三行run identity统一改为`__r02`，
并重新冻结各experiment-row SHA。每行仍须显式SolverAuthorized，且按执行策略串行运行。
