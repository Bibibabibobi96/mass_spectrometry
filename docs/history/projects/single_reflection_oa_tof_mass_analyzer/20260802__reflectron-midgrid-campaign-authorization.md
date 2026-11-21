# reflectron midgrid声明式campaign授权（2026-08-02）

DOC_STATUS: ARCHIVED_READ_ONLY

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 授权范围

仓库所有者批准首个oaTOF声明式结构Candidate campaign。唯一开放原生轴为
`reflectron_midgrid_voltage`；固定524 Da、+1、N=100、粒子源seed `20260720`及common-random-number
配对。两行分别为理论名义值1628.8001 V和诊断值1600 V。

项目optimization envelope新增1600–1650 V窄范围。该范围覆盖既有1601 V真实COMSOL/SIMION/CAD
结构运行时验证和1628.8001 V耦合理论名义值，并仅保留小幅正侧诊断余量；它窄于catalog的静态安全
范围。campaign与单工况Candidate编译器都会在启动求解器前拒绝越界值。

## 执行与声明边界

活动表`config/experiment_campaign.json`在任何新行启动前设为`preregistered/authorized`，并冻结request、
science profile、solver numerics、变量catalog、optimization envelope、Candidate workflow、Candidate
runtime和execution profile的SHA-256。商业求解器并发固定为1、自动重试为0；全表预检先于首行启动，首个失败后停止，
不复用旧run。

首次v1调度`20260802_122900__sim__cross__midgrid-campaign`在1.8秒内终止，未启动任何子行或
商业求解器。原因是旧`candidate_runtime.json`仍指向清理前scratch模板路径；失败证据按原样保留。
模板从既有成功Candidate冻结输入重新注册为
`20260802_125000__build__simion__candidate-layout-template`。v2不复用v1 campaign或子run ID，新增
运行时权威哈希，并在分配campaign目录前验证SIMION可执行文件、注册四件套、源文件存在性与SHA-256。

v2调度`20260802_125500__sim__cross__midgrid-campaign`完成全表与静态输入预检后，在首行COMSOL
启动器的运行环境写权限检查处终止；这是受限Agent沙箱无法写用户COMSOL配置/日志目录，不是模型或
求解器失败。首行失败三件套与campaign receipt保持终态，第二行未启动。v3再次使用全新campaign与
子run ID，并要求在正常用户执行上下文运行；不把环境失败伪装成retry，也不复用v2子run。

## v3执行结果

v3 campaign `20260802_130000__sim__cross__midgrid-campaign`在4643秒内完成，两行均依次通过真实
COMSOL构建/同步、SIMION N=100传输、SolidWorks 25件零件与总装配以及结构验收。子run为
`20260802_130100__sim__cross__midgrid-reference`和
`20260802_130200__sim__cross__midgrid-diagnostic`；两者均为terminal success、
`candidate_accepted_not_promoted`，100/100粒子到达探测器。campaign manifest和两个子manifest分别
通过完整记录验证，统一status将两行标记为`SUCCESS/ended=true`。

SIMION同源N=100诊断显示：1628.8001 V名义行的平均飞行时间为71.353593 µs、飞行时间标准差
0.234492 ns、FWHM分辨率64610.15、最大命中半径15.709382 mm；1600 V诊断行分别为
71.301278 µs、46.486615 ns、325.67和15.712242 mm。降低28.8001 V几乎不改变该样本的传输或最大
半径，却使飞行时间展宽增加约46.25 ns，说明该轴对时间聚焦高度敏感，理论名义值在本次SIMION结构
样本中明显优于1600 V诊断点。

这只是固定seed、N=100的SIMION Candidate灵敏度证据；COMSOL粒子级横向比较未运行，也没有统计重复、
数值收敛或Formal晋升。因此结果用于否定“1600 V可作为同等基线”的假设，不把64610.15解释为已资格化
的整机分辨率。

本授权只允许N=100结构链执行与两行横向比较。成功不证明1600 V优于名义值，不形成分辨率、优化、
数值收敛或跨求解器等价声明，也不修改baseline、Formal资产或资格；任何晋升仍需独立事务和批准。
