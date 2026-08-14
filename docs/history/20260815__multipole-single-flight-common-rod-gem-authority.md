# 多极杆single-flight公共rod GEM权威收口（2026-08-15）

## 结论

RF→oaTOF integration原先在`single_flight_frontend.py`中重新遍历rod并直接生成SIMION `cylinder`，与
`common/multipole/simion_geometry.py`构成第二套rod renderer。本次保留公共Python renderer为唯一权威：
common读取resolved `segmented_rod_array`、验证rod primitive并使用SIMION官方`locate`与`cylinder`；
integration只提供local-z→global-x placement、电极namespace和connector/oaTOF组合。

没有新增GEM include路径。现有三个RF项目已经共同消费Python公共renderer；若为追求include再保留Python
和integration wrapper，反而会形成第三路径，且不能降低当前组合PA的坐标映射与namespace复杂度。

## Characterization

仓库内四/六/八极杆resolved design均为4个轴向segment，radius为2.0 mm，显式rod electrode IDs为
`1..8`；物理rod primitive分别为16、24、32条，横向中心分别为4、6、8个。standalone segmented GEM
canonical SHA-256分别为：

- quadrupole：`427647f0200eda36fad92c40a0c36739ca6d316bcbf7e7e8fc7d5f67dff960f7`；
- hexapole：`be36a3afbd12358358050ec7f738be1b23b11680ad20e95414f398a8d117fb68`；
- octupole：`934f81aff5ac381240a0c353ad0f701083afb9b02c3a13c18fbd39e64d65a087`。

在同一非零translation与90度轴映射下，公共placed renderer的三族golden SHA-256分别为
`c811a0ff39044a3caee40dc3b058cfd7bc77c53edb1045340a304481e15a2b7d`、
`ee39c8445a1c7a090130b37d43e9d71c54db74d30cc0518132386cc8601c3d36`、
`3e80b28238e8e0b39c43a78d829d6c64fb3842666b61ec4b7601ef8cc7a4be45`。

当前octupole joint frontend完整GEM在迁移前后均为
`35d331a4d46e73abbcde140cc9e5a9bee7e10a9a6b2ab099fe1db90ddc376217`，逐字节不变；所以现有PA输入、
场、dt、resource与物理输出均未改变，也未启动SIMION。

## 边界

三族现行四段合同均把`segment × RF group`映射为rod PA basis `1..8`，与物理rod数量无关。integration
namespace继续从common显式mapping读取，不得把rod primitive固定为32条octupole；当前正式basis仍明确
要求4 segments→IDs `1..8`，且single-flight Program和runner发布的总basis仍为`0..19`。因此未来非
`1..8`的rod mapping必须失败关闭，不能只改frontend便宣称任意分段端到端可用；扩展时必须先同步
Program、runner、overlay和真实PA电极数组验证。

当前frontend与Program共同消费`single_flight_electrode_contract.py`这一份basis权威：rod必须恰为
`1..8`、加速器必须恰为5个ring、完整basis必须恰为`0..19`。common placed renderer的当前接口只承担
local-z→global-X placement，并只接受SIMION `locate` rotation selector 1；它不宣称支持任意轴旋转。
坐标、rotation、格式精度及电极ID均拒绝bool、非有限数、分数ID、越界值和不完整namespace。

`family_runtime_dependencies.json`已把`common/multipole/simion_geometry.py`注册为
`single_flight_transport`依赖，并同时注册上述single-flight electrode contract。PowerShell resolver和
publisher直接保持manifest的唯一依赖顺序，不再维护第二份固定ID清单或固定数量；真实resolver→publisher
回归证明resolved与run-local publication逐项等于manifest。repository binding由官方refresh入口重冻结，
实际更新7份派生publication，随后`--check`为PASS。

验证结果：公共rod/轴向加速full suite 325/325 PASS，integration full suite 350/350 PASS；两份活动
schema-v3 successor逐行`ValidateOnly`为5/5与24/24，共29/29 PASS，未启动求解器。CLOC 2.10以
`87acc2dba9c38866b343e3adbc054d49bcf09156`为base、WORKTREE为结果：total code
`172555→176387`（+3832），production `126538→130133`（+3595），tests `45987→46224`
（+237）；其中production JSON +3418主要来自官方repository binding重冻结，production Python +205行，
PowerShell -28行。
过滤口径沿用`common/report_cloc_delta.ps1`的仓库标准扩展名、artifact/generated/vendor/run排除与
production/test分类。
并发验证还发现公共测试曾把临时`.json`写入活动campaign目录，使binding freshness在同一时段把半生命周期
fixture视作publication。测试fixture现使用非publication `.tmp`后缀；公共325项与integration 350项并发
复跑均PASS，未改变生产campaign的`*.json`路径合同。

最终`common/verify_changed.ps1` L1 PASS：公共多极杆325/325、integration 350/350、family foundation、
quadrupole Freshness/Core以及quadrupole/hexapole/octupole静态门禁全部PASS。

本记录只证明代码权威、GEM字节身份与合同边界，不新增物理性能或Formal结论。
