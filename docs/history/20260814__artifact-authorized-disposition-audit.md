# 2026-08-14 artifact 授权处置审计

> 状态：已完成的只读追溯记录。本文记录一次经用户明确授权的本机 artifact 处置；不改变项目当前资格，不能替代各 run 的 manifest。

## 授权与边界

用户授权删除当前用不到且不符合仓库产物规范的文件，同时明确要求保留本轮后续实验仍会复用的理想源/真实束源、真实加速场/理想加速场及相应 PA。处置因此只覆盖已识别的顶层或项目 scratch，以及中断、失败、缺少完整身份或仅用于早期锁死排查的 run；未把“可重建”本身当作删除授权。

本次未删除当前实验使用的 SIMION PA/cache、成功的场与源比较 run、正式或归档证据、canonical particle states、summary、metrics，也未删除被当前 history 引用且仍承担科学结论或后续复现实验输入的产物。尤其保留了短焦/长焦、理想源/真实多极杆束、真实场/理想场比较会复用的 PA 家族和缓存。

## 已处置目标

下列 17 个目标删除前的逻辑大小合计为 `96,387,644,931 bytes`（`89.768 GiB`）。这里的逻辑大小按路径汇总，会重复计算硬链接指向的同一物理内容，不能解释为预期磁盘释放量。

### Scratch（5项）

|目标|删除前逻辑大小（bytes）|
|---|---:|
|`artifacts/scratch`|224,587|
|`single_reflection_oa_tof_mass_analyzer/scratch/20260811_161000__repo__incomplete-run-migration`|1,318,790,126|
|`rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/20260811_160500__repo__artifact-layout-migration`|1,307,513,084|
|`rf_octupole_ion_optics/scratch/20260811_160700__repo__prepared-layout-migration`|1,304,667,680|
|`rf_octupole_ion_optics/scratch/20260804_120000__simion__single-flight-gui-review`|320,839,297|

本节共计5个路径目标；`artifacts/scratch`是仓库顶层布局违规目录，不属于项目 scratch。

### 集成失败或中断run（8项）

以下路径均位于 `rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/`：

|run ID|删除前逻辑大小（bytes）|
|---|---:|
|`20260813_184500__sim__simion__arm8-center-smoke`|8,594,110,539|
|`20260813_190000__sim__simion__arm8-center-smoke-r02`|8,594,057,719|
|`20260813_193000__sim__simion__arm8-center-smoke-r03`|8,594,179,180|
|`20260813_200000__sim__simion__arm8-center-q16-r04`|8,594,021,966|
|`20260813_203000__sim__simion__arm8-center-focus-tstep-r05`|8,594,022,765|
|`20260813_210000__sim__simion__arm8-solver-closure-n101`|8,594,146,011|
|`20260813_213000__sim__simion__arm8-solver-closure-n101-clock-r02`|8,594,363,292|
|`20260813_220000__sim__simion__arm8-solver-closure-n101-log-r03`|8,594,673,026|

### 八极杆失败、无效或锁死排查run（4项）

以下路径均位于 `rf_octupole_ion_optics/runs/`：

|run ID|删除前逻辑大小（bytes）|
|---|---:|
|`20260813_210000__sim__simion__rf-oatof-single-flight-gap0__n1`|7,892,455,395|
|`20260812_000500__sim__simion__rf-oatof-linear-coupled__n1000__r01`|5,199,102,572|
|`20260813_191100__sim__simion__rf-oatof-single-flight-gap0__n1000`|5,149,152,902|
|`20260813_204000__sim__simion__rf-oatof-single-flight-gap0__n1000__r02`|5,141,324,790|

执行清单按删除操作统计为 17 个目标：顶层 scratch、3个迁移 scratch、1个GUI review scratch、8个集成 run 和4个八极杆 run。上面的逐路径表完整列出实际对象；逻辑大小也按同一顺序逐项记录。

## 结果与限制

处置后文件系统报告实际释放 `16,044,445,696 bytes`（`14.943 GiB`）。实际释放显著小于逻辑路径总量，是因为被删 run 内的 PA 与保留 cache 或其他 run 之间存在硬链接；仍有链接的物理数据不会随单一路径删除。

本次直接删除的是不再保留的目录，没有改写历史 manifest，也没有补造 `retention_actions`。因此本文记录授权、路径边界和容量结果，但不把旧 manifest 表述为事后已经合规。没有生成或保存逐文件 SHA-256 清单；本文不声明删除载荷已具备文件级 SHA 可验证性。

本次也没有继续处置约 66.9 GiB 的旧版 radial-compaction 成功 run，没有批量清空约 204 GiB 的可重建 cache。前者仍需独立核对引用和保留价值，后者包含当前实验会复用的 PA，且直接清空会触发重新 refine。任何后续删除仍需新的明确目标核验和用户授权。

## 删除后验收

删除后重新检查了本轮实验的五个关键 cache key：两个官方原生透明栅 frontend、长短焦 `dz=0.05 mm`
overlay 和短焦 `dz=0.025 mm` overlay 均存在，并通过 cache 结构校验。`simion_oatof_downstream_pa`
保留27个key，PA family结构完整；当前COMSOL预脉冲根因scratch以及关键 `183000`、`183100`、
`223000` 实验run也都存在，后三者三件套完整且manifest为schema v2 `success`。因此本次处置没有误删指定的
理想源/真实束源、真实场/理想场实验PA或其主要复用缓存。

全仓artifact布局门禁仍为FAIL：集成项目顶层已有 `analysis/` 目录不在当前白名单内；本轮 `003500`
comparison run也原已缺少 `summary.json`。两项均在本次清理前存在，其中 `analysis/` 和comparison属于
当前实验结果，按用户的复用保留要求未删除。仓库根 `scratch/` 仍保存当前whole-stage工作目录，因而
文档门禁的仓库卫生前置检查也仍失败；这些保留项不能被本次14.943 GiB清理表述为已经合规。
