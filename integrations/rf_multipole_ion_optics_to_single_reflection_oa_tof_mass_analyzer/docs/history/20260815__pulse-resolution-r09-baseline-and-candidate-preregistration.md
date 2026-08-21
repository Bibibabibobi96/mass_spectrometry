# r09 baseline结果与三行candidate预注册

DOC_STATUS: ARCHIVED_READ_ONLY

## baseline正式结果

唯一授权的`pulse_resolution_direct_baseline_v5_r09`使用当前官方零宽透明栅网、真实多极杆束、
`accelerator_real_pa`和真实反射器场完成N=100 SIMION输运。frontend与accelerator overlay分别精确命中
`01c205c64fc144710678bf823e3ed3852c28ea2992c6c14064ca2a53f4515309`和
`f1b4d3fc449c8f350faa9a33615156249f97588f797d9686ff7fce046f92fa40`，`rebuild_effects=[]`，未build/refine。

实际cohort为source/handoff/pre-pulse/eligible/outside/detector=`100/62/52/52/0/52`；eligible到detector为
`1.0`。pulse-effective单峰分辨率`R=4458.13537824347`，direct TOF FWHM=`3.496136958577978 ns`。
计划脉冲时刻为`31.81366987147908 us`，SIMION日志序列化值为`31.8136698715 us`，差值
`2.091837814077735e-11 us`，低于冻结合同容差`1e-9 us`。receipt自哈希核验通过：
`B515E431A076E57E00324B80CC1D3FEF031CD8B882CB3B65C2E48531A7B69E7B`；receipt文件字节SHA-256为
`EA4BB4084A754F5442B016B7D3744141A107C291B8DDABA8CCD9C193D759E37E`。parent/child manifest SHA-256分别为
`06134C747DD095092B8BD053AED7C213A877DA325B34DF0125D13DF156E9B12A`和
`54E67E3DEC5BA4D8B649929A7EB08FC05E668187F485A99EB132A773F54D0AE5`。

该receipt是后续paired candidate唯一baseline权威。旧D469 cohort仍只作历史迁移参考；candidate必须逐组
精确复用r09发布的observed cohort，不允许重选detector survivor。

## 三行candidate冻结设计

新campaign仅登记原控制变量矩阵的sequence 2/3/4：

1. `accelerator_ideal_stage1_real_stage2`：仅Stage1替换为合同理想场；
2. `accelerator_ideal_stage1_stage2_real_reflectron`：Stage1与Stage2替换为合同理想场，反射器保持真实场；
3. `full_domain_piecewise_ideal_field`：使用既有全域分段理想场语义。

三行保持同一源、N=100 ordered prefix、脉冲时钟、几何、反射器合同、数值配置、bootstrap随机性和分析方法；
每行在campaign中冻结独立experiment-row SHA。三行只授权paired screening，不构成Candidate、Formal、数值收敛
或最终物理归因结论。每次SolverAuthorized仍需明确授权；本预注册不自行启动SIMION。
