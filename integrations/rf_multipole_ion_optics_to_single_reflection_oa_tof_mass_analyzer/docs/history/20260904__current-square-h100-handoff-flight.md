# 当前自然轨迹矩阵复用与方形1mm飞行

DOC_STATUS: ARCHIVED_READ_ONLY

2026-09-04阶段证据；不是八案例完成或Formal结果。

## 上游可复用矩阵

Agent1核对manifest、小状态SHA、采样与选择合同，找到此前遗漏的恢复运行__r01。
以下均声明相同5000母源（SHA前缀88C5BD19），native RF40、stride1、pulse disabled；
本次没有重新计算上游，也没有重读数GiB轨迹做全量SHA复算。

|形状/孔高mm|producer时间前缀及后缀|物化粒子数|pulse us|
|---|---|---:|---:|
|方形1.0|20260903_031249 / n5000__r01|30|83.9545454545|
|方形1.5|20260903_040547 / n5000__r01|39|83.9545454545|
|方形2.0|20260903_071701 / n5000|49|83.9545454545|
|方形2.5|20260903_075315 / n5000|56|83.9545454545|
|圆形1.0|20260903_082228 / n5000|30|86.3409090909|
|圆形1.5/2.0/2.5|仅找到旧有限窗口结果|未闭合|不适用|

producer主体均为__sim__simion__rf-oatof-single-flight-gap102p4__，完整身份以各物化receipt为准。
四方形resolved geometry同SHA D5117A46F40ABC92B5F188796FDE1B8D47F46AB9E2DFE662FF025C69A4405AF5，
入口域已含新增10mm，不能与9月2日旧N50条件群混为同一配置。

## 发布与真实飞行

既有publisher从成功cross parent的frozen experiment及成功materialization manifest派生新campaign。
本轮未修改源码或机器配置，只发布新的不可变分析/模拟产物及文档。
方形h100新派生run为20260904_124500__analysis__python__square-h100-current-handoff-successor__n30，
其results/derived_post_pulse_campaign.json保留全部30个入选粒子与5000母群分母。
脉冲起点继承83.9545454545us，持续时间由冻结状态派生6.8926090668729385us。

真实run：20260904_124429__sim__simion__rf-oatof-single-flight-gap102p4__n30。
SIMION exit0、analysis与publication PASS。公共批次墙钟105.006s，波次107.096s。

|指标|数量|
|---|---:|
|启动/实际source_release|30/30|
|第一栅/第二中间栅|29/28|
|加速器出口/焦面|25/25|
|反射器入口/转向/返回|25/25/25|
|回程探测命中|6|
|加速器非探测终止|5|
|飞行管非探测终止|19|

6个命中全部属于完整反射路径，source IDs为61/1313/2088/2325/4025/4806。
母群归一化6/5000=0.12%，条件下游6/30=20%；这是全部入选群，不作共同命中筛选。
仅6个命中不支持可靠FWHM、尾部、bootstrap分辨率声明。

主PA key d4b86d5cf1fbc5ea1702720dff55b3526ecb5cd670d75381f15cbc321926df91与
入口局部PA key 787acfede997037684668b83673dacb8d087b0e1adc666aaf012d88c3778a56f均cache_hit。
无refine，未加载多极杆细PA；容量终态496.70GiB，未清理cache，租约已释放。

## 已准备后续与限制

Agent2通过相同publisher发布方形后继（均有success manifest，未启动飞行）：

- 20260904_130000__analysis__python__square-h150-current-handoff-successor__n39
- 20260904_130100__analysis__python__square-h200-current-handoff-successor__n49
- 20260904_130200__analysis__python__square-h250-current-handoff-successor__n56

三个campaign均位于各run的results/derived_post_pulse_campaign.json，孔高与数量已核对，母分母5000，
持续时间policy为frozen_restart_ideal_focus_envelope_v1。旧只有campaign.json且没有manifest的骨架目录
不作为新的执行凭证。本轮不删除既有证据或目录。

下一步依次完成方形1.5/2.0/2.5 post-pulse，再补圆形上游缺口及圆形下游；
至少一条同源连续全程对照、八案例完整指标与几何/场等价证据仍待闭合。
真实成功只代表本case执行链，不是GUI/CAD、Formal或八案例完成。

CLOC_DELTA=N/A (docs-only; 本轮无源码或机器配置修改，新增为受管运行产物)。
文档门禁的仓库卫生检查通过；全仓文档检查仍因其他项目
orthogonal_accelerator/docs/history/20260903__legacy-accelerator-diagnostic.md缺少只读归档标记失败。
未提交混合工作树，未宣称全仓门禁通过。
