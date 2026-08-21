# oaTOF有限区间聚焦与一级局部PA里程碑（2026-08-12）

DOC_STATUS: ARCHIVED_READ_ONLY

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 范围

本快照冻结2.2 mm有限源区、线性z–vz匹配、理想场oracle、一级场归因和局部细PA完成后的必要追溯。
归档时的活动状态入口是
[`INTEGRATION.md`](../INTEGRATION.md)；
粒子级输出和完整配置以各run manifest为准。

## 已关闭的诊断链

1. 理论解在`d1=3.0 mm`、`d2=16.8 mm`和5环下可覆盖2.2 mm源区；一级压降约316.25 V、二级均匀
   场约109.71 V/mm，派生焦距约45.36 mm。只在旧PA更换电压使分辨率下降，证实几何必须随焦距重构。
2. 完整重构后，屏蔽罩旧绝对坐标曾造成失配；修复为只消费加速器外包络端点。真实连续注入传输提高，
   但出现双峰且`R≈8494`，因此理论可容纳不等于真实三维场已聚焦。
3. 分段理想场oracle曾允许一步跨越grid1/grid2场强突变面，多获得约9.11 eV。把时间步精确截断到
   两个栅面和焦面后，严格线性人造源焦面σ降至约0.02 ns，闭合解析理论。
4. 同几何分段隔离得到：真实场焦面σ约2.308 ns；仅一级理想0.334 ns；仅二级理想1.324 ns。
   对真实多极杆队列，仅一级理想约`R=21792`，确认一级场为主要限制。
5. 基函数诊断把粗网格误差定位到透明栅网附近的数值边界层。0.2 mm整体PA叠加六面边界耦合的
   0.05 mm局部加速器PA后，同一808粒子从`R=8427`提高到`R=20883`，焦面σ从4.431降至1.472 ns。

## 代表证据

- 旧PA只换电压：`20260812_130000__sim__simion__rf-oatof-finite-interval-limit__n1000__r01`
- 理论几何重构：`20260812_140000__sim__cross__oct-finite-interval-theory__n1000__r03`
- 理想场边界步修复：`20260812_210000__sim__simion__rf-oatof-terminal-analytic-ideal-boundary-step__n1000__r01`
- 最新人造源对照：`20260812_213000__sim__simion__rf-oatof-terminal-analytic-ideal-boundary-step__n1000__r01`
- 局部PA自然注入：`20260813_060000__sim__simion__rf-oatof-stage1-overlay-z005__n1000__r01`
- 局部PA配对A/B：`20260813_080000__sim__simion__rf-oatof-stage1-overlay-ab__n1000__r01`

## 结论边界

理想场闭合证明一维公式、焦面和源映射实现一致；局部PA结果证明粗网格一级数值边界层是可修复的主要
误差。两者都没有建立局部PA网格收敛、理想源单峰性、跨求解器等价或整机Formal资格。
