# 三区真实PA observed纵向束与横向六维敏感性

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 结论

2026-08-17在冻结三区四平面、1+4整形环、真实SIMION PA和同一N=100粒子ID集合下，完成了两个
描述性源臂：

- `transverse_collapsed`：保留observed经验`z-vz`、逐粒子总能量、clock和ID；把`x/y`置于共同中心，
  令`vy=0`并用正向`vx=hypot(vx,vy)`保持横向速率与总能量。
- `full_observed_6d`：保留同一observed经验`x/y/z/vx/vy/vz`，对位置只施加共同中心平移，并使用
  当前pulse epoch；能量由六维速度重算。

两臂均100/100穿过I1、I2、exit和反射器并到达探测器，且均为单峰。恢复完整横向状态相对横向
塌缩只使TOF sigma增加`4.2174%`、直接FWHM增加`4.5120%`、质量分辨率降低`4.3171%`。
相反，两条observed纵向束臂相对此前affine理想源的峰宽恶化大约一个数量级。因此当前证据把主要损失
定位到经验纵向源bundle（经验z分布、非线性z-vz和逐粒子能谱）与真实场的组合；横向位置和方向是
较小但可测的增量，不是当前主导项。

v1—v3 campaign文件名中的`cd`只作为已被失败/成功manifest冻结的历史短名保留，不能在不破坏证据
哈希的情况下改名；当前报告、JSON字段和后续入口只使用上述两个描述性名称。

## 冻结源与变换

observed pulse-state authority来自成功run
`20260811_003000__sim__simion__rf-oatof-exact-formal-field-bridge__n1000`，状态表有996行，缺母ID
`10,290,298,701`；本轮冻结的100个全宽分层ID全部存在。旧中心与当前三区中心的`x/y`相同，只对
全部位置共同施加`z=-43.06505301729918 mm`平移。旧、当前pulse clock属于不同campaign，故没有把
clock差当作真实飞行时间做弹道推进。

该变换是`paired transverse-state transplant`，不是从旧装置连续运输到新三区加速器的真实六维轨迹。
两臂逐ID共享相同`z/vz`、能量、质量、电荷和clock，只有声明的横向状态不同。机器合同、投影receipt
及其schema由`runtime/observed_pre_pulse_projection.py`发布并失败关闭地绑定原始manifest、状态表、
旧几何、当前目标和ordered-subset receipt。

## 执行链与结果

v1和v2的`transverse_collapsed` N=1 SIMION child都完成1/1探测，但父级publication分别暴露了adapter
和runner的source-identity传播缺口；失败证据保留且未作为N=100授权。v3令runner直接消费prepare
冻结的完整budget identity，随后两个描述性臂各自完成N=1授权和N=100运行：

| 源状态 | detector | sigma / ns | direct FWHM / ns | mass R | modes |
|---|---:|---:|---:|---:|---:|
| affine理想源真实PA基准 | 100/100 | `0.2035735674` | `0.2338558848` | `66988.23` | 1 |
| `transverse_collapsed` | 100/100 | `0.8197190662` | `2.4714356728` | `6338.67` | 1 |
| `full_observed_6d` | 100/100 | `0.8542897552` | `2.5829468539` | `6065.03` | 1 |

严格逐粒子detector配对的`full_observed_6d - transverse_collapsed`时间差为：mean
`-0.0086067780 ns`、sample sigma `0.2298684134 ns`、RMS `0.2288780663 ns`，范围
`[-1.6089363000, 0.4996093000] ns`。detector checkpoint没有速度分量，因此比较artifact明确发布
速度可用数为0和`null`统计量，不从位置或时间反推速度。

机器证据：

- 横向塌缩N=1父run：`20260817_235954__sim__cross__three-zone-real-pa-observed-c-n1__n1`
- 完整六维N=1父run：`20260817_235955__sim__cross__three-zone-real-pa-observed-d-n1__n1`
- 横向塌缩N=100父run：`20260817_235956__sim__cross__three-zone-real-pa-observed-c-n100__n100`
- 完整六维N=100父run：`20260817_235957__sim__cross__three-zone-real-pa-observed-d-n100__n100`
- 描述性配对结果：`20260817_235959__analysis__python__three-zone-observed-transverse-sensitivity__n100`

全部父/child和最终比较manifest均经`common.contracts.verify_run_manifest`验证。frontend、accelerator
overlay和flight-tube均为cache hit，本轮没有重建PA。

## 声明边界

结果仅为100 Th、N=100、post-hoc描述性`FUNCTIONAL_ONLY`源敏感性证据；没有阈值判定、优化、统计
重复、N=1000、网格收敛、连续真实handoff、COMSOL/CAD或工程资格。它不改变oaTOF 524 Da Formal、
现有baseline或资产身份。
