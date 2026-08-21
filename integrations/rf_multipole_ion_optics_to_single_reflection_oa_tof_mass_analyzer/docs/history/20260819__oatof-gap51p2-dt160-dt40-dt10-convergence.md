# oaTOF 51.2 mm连接器dt160/dt40/dt10全流程对照（2026-08-19）

DOC_STATUS: ARCHIVED_READ_ONLY

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 文档职责

本文冻结51.2 mm连接器、三区真实PA加速器、N=1000连续full-flight在`dt160`、`dt40`和
`dt10`三档时间积分profile下的完整诊断结论。它记录已发布manifest事实和当前默认选择依据，不把
本次单一gap、layout和field身份外推为全部结构的数值收敛资格，也不修改solver、PA或pulse authority。

三档共同使用已验证pulse时刻`58.7322729797 us`，均从同一完整N=1000母群连续飞行；共同census为
`launched=1000`、`pre_pulse_state=82`、`pulse eligible=77`、`detector crossing=77`，规范主峰均使用
72个完整pulse-eligible detector cohort粒子。唯一科学变化轴是`rf_steps_per_period=160/40/10`；
batch count均为2，只属于执行设置。

## 冻结运行身份

| profile | `rf_steps_per_period` | 成功child run | manifest SHA-256 |
|---|---:|---|---|
|`dt160`|160|`20260819_031000__sim__simion__rf-oatof-single-flight-gap51p2__n1000`|`E30A65DFDF0081226325A672487FA9BF275999311AA0820325FBF3D15E98D562`|
|`dt40`|40|`20260819_050000__sim__simion__rf-oatof-single-flight-gap51p2__n1000`|`E72279D8E87215BC7EEDCD412C9DC372436226A266D24D143E28F4A020A39F6F`|
|`dt10`|10|`20260819_050100__sim__simion__rf-oatof-single-flight-gap51p2__n1000`|`F7AE4A0D43A091118B7840EE1A555904AF9FE3EEED0CB4B5149387F4D5C64ED6`|

`043000`、`044000`和`045000`的dt160尝试分别因进程清理、可用内存门和SIMION batch失败而终止；
它们不是数值结果。成功dt160权威只认上表`031000`，不得把失败run的空summary混入三档比较。

## 规范主峰与条件区域峰

| profile | 主峰N | TOF sigma (ns) | direct FWHM (ns) | R | KDE modes |
|---|---:|---:|---:|---:|---:|
|`dt160`|72|0.9393023189|3.0667657332|5108.203061|2|
|`dt40`|72|0.9392740339|3.0669824113|5107.842111|2|
|`dt10`|72|0.9387572455|3.0611704299|5117.538818|2|

相对dt160，dt40的主峰FWHM只变化约`+0.0071%`，R只变化约`-0.0071%`；census、主峰粒子ID
数量和双模态判断不变。dt10相对dt40的FWHM变化约`-0.1895%`、R变化约`+0.1898%`。因此在本次
冻结身份和当前分辨率尺度下，dt40已复现dt160主结论；dt10也没有揭示足以推翻该结论的时间步长效应，
但它相对dt40的偏移更大，不能仅因结果相近而升级为默认。

默认source-region诊断固定为`x/y=2 mm`、`z=2.2 mm`，三档均为eligible 77、selected 8、detected 4：

| profile | 条件峰N | TOF sigma (ns) | direct FWHM (ns) | R |
|---|---:|---:|---:|---:|
|`dt160`|4|0.4890027592|1.5019397092|10430.199832|
|`dt40`|4|0.4873314295|1.4969784503|10464.767547|
|`dt10`|4|0.4903760836|1.5105110802|10371.012658|

该条件峰只有4个detected粒子，仍是`PROVISIONAL_DIAGNOSTIC_ONLY`。它可用于确认三档选择了同一
detector-blind源区域，但不能作为默认profile的主要判据，也不能代表完整束分辨率。

## 资源证据与默认决策

两批并行时，冻结resource-usage的单批wall clock分别为：dt160 `1412.010/1418.454 s`，dt40
`913.379/916.248 s`，dt10 `950.685/961.610 s`；三档峰值process-tree working set均约`9.963 GiB`。
dt40相对dt160把并行wave的最长单批时间降低约35%，同时保持规范主峰不变；dt10没有比dt40更快，
且主峰偏移略大。

因此，当前51.2 mm三区real-PA continuous full-flight的默认时间积分profile冻结为`dt40`：

1. 常规同身份run显式选择`dt40`，不得依赖runner内隐fallback；resolved/run_config/manifest继续冻结
   完整profile ID和`rf_steps_per_period=40`。
2. `dt160`保留为已验证参考档，用于实现变更或新物理身份的数值回归，不作为常规默认。
3. `dt10`保留为粗时间步长stress/诊断档，不作为默认，也不得据本次单点结果授予普适收敛资格。
4. layout、gap、RF clock、field、PA、source或pulse policy改变后，必须显式声明数值profile；本结论不
   自动替代新身份所需的配对收敛检查。

本结论是数值实现选择，不改变科学主结论：51.2 mm筛选后完整real-field主峰仍约`R=5.1k`，低R不能
归因于dt160时间步长；后续理想场因果反事实应以dt40为默认consumer步长，并保持同一已验证pulse和母群身份。
