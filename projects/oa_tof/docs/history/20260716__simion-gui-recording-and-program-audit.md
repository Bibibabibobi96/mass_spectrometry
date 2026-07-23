# oa-TOF SIMION GUI Recording 与 Program 审计归档（2026-07-15—16）

> **只读历史档案。** 本文件保存GUI Data Recording、轨迹质量和Program On/Off调查的关闭证据。
> 文中的“正式”和路径均按归档时点解释；当前入口、资产身份和性能只以项目README、
> `../PROJECT.md`及机器合同为准。`DOC_STATUS: ARCHIVED_READ_ONLY`

## Data Recording积分精度

早期同名工作簿`simion_524amu_intensity_time_spectrum.xlsx`包含5000个连续离子，记录均来自
PA实例4和当时的检测面。统一分析得到平均TOF `72.00529112 us`、TOF标准差`7.24070347 ns`、
直接TOF FWHM `22.05991476 ns`，对应`R=1632.01`。

用同一IOB/Fly2进行命令行配对后，差异定位到轨迹积分档位：

|运行|N|平均TOF (us)|标准差 (ns)|直接TOF FWHM (ns)|直接质量R|
|---|---:|---:|---:|---:|---:|
|GUI工作簿|5000|72.005291|7.240703|22.059915|1632.01|
|命令行quality=3|5000|72.004126|7.053347|19.925180|1806.97|
|命令行quality=8|5000|71.990291|0.815089|1.408880|25549.58|

GUI宽峰由低轨迹质量造成，不是检测器厚度、Program日志、Excel直方图或样本数造成。Data Recording
本身不保存T.Qual，不能仅凭工作簿证明quality。随后正式Program增加可调
`trajectory_quality=8`，在`segment.load()`和`segment.initialize_run()`中写入，并由
`tests/simion/verify_iob_runtime_contract.ps1`实际加载IOB验证。

## 同名工作簿覆盖

同名桌面工作簿后来被覆盖为仅含TOF和人工统计列的版本，文件大小56059字节，SHA-256为
`57EEC5E6EC6275C8DC79C3F9A2EC4E4D336DB772FD9E753127F718643DCC4FC4`。统一算法得到平均TOF
`71.99026824 us`、标准差`0.81232215 ns`、直接质量FWHM`0.0187909682 Da`和`R=27885.74`；
表内人工`R1/R2`不符合项目定义。

该文件缺少真实Ion Number、PA instance、X/Y/Z和Event，不能证明检测实例、检测面、quality或
跨求解器逐粒子配对。由此固化：可覆盖文件名不能充当证据身份，至少绑定列结构、行数和SHA-256；
正式比较必须使用真实粒子ID及完整检测事件字段。

## Program On/Off配对

后续5000行并排工作簿冻结在当时运行证据中，大小462631字节，SHA-256为
`132640A666B5C861D3DA9B0834B2C300DD2C61478331206B1079A2017692A988`。两组均记录PA实例4；
On组检测器Recording审计通过。统一结果为：

|组别|平均TOF (us)|标准差 (ns)|直接TOF FWHM (ns)|直接质量FWHM (Da)|R|
|---|---:|---:|---:|---:|---:|
|Program On|71.99028682|0.806483|1.526591|0.02222238|23579.83|
|Program Off（诊断）|71.98789634|0.697827|0.723979|0.01053960|49717.24|

工作簿TOF仅保留到`0.1 ns`，可用于GUI同精度配对审计，不能替代高精度TRACE/CSV。两组使用同一
确定性粒子；关闭Program后平均TOF变化`-2.39048 ns`，逐粒子排序几乎被重排。差异主因是透明栅网
跨越逻辑：每个粒子经过grid1、grid2各一次，entgrid、midgrid各往返两次，固定距离跨越的累计时间
与实测均值差同量级，并改变边界处场积分。

Program Off只能证明禁用Program会破坏数值合同，不能作为更高分辨率基线。GUI复现必须保持Program
On；运行时门禁必须实际加载IOB并读取本次唯一报告，不能只检查Lua文本或沿用旧报告。
