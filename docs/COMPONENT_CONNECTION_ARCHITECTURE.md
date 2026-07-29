# 器件端口、连接器与跨项目联合模拟架构

## 状态与适用边界

本文冻结跨项目器件连接的目标架构。RF四极杆离子光学→单次反射oa-TOF实例的端口、公共解析器、
composition plan、connection profile和integration adapter已经实现，当前状态为
`migration_implemented_equivalence_pending`。迁移前S2/S3具名合同和输入已经冻结为只读oracle，不再是
活动机器权威；新入口尚未完成同输入、同几何、同事件和同结果的真实等价复验，因此迁移尚未验收，
也不得据此声明阶段或整机资格。
本文定义职责和迁移门禁，不定义某次连接的数值参数、性能阈值或正式资格。

项目改名、单器件求解器资格和artifact保留治理不依赖本架构，可以先行。若要新增第二种
RF多极杆离子光学→单次反射oa-TOF
连接、复制已归档S2/S3语义或重写连接器联合模型，应复用本文架构，避免继续积累项目间特例。

## 决策

跨项目连接采用“项目端口 + 公共编排器 + 连接profile”的混合架构：

- 上游项目拥有provided port及canonical输出生成器；
- 下游项目拥有required port及输入验收条件；
- 公共层拥有端口、连接、坐标、时钟、粒子状态、谱系和组合计划schema，以及兼容性解析和执行编排；
- `integrations/<connection-family>/`拥有具体器件族之间的连接profile、专用连接几何、求解器adapter、
  联合测试、当前状态和集成证据；
- 联合run及其manifest以`integration_id`为主身份，并同时冻结两端`project_id`、port和profile身份；
  它不冒充任一单器件`project_id`。

公共编排器不得只根据两个项目ID猜测物理连接。完整请求至少冻结：

```text
UpstreamProjectId
UpstreamPortId
DownstreamProjectId
DownstreamPortId
ConnectionProfileId
```

若两端只有唯一兼容端口和唯一profile，用户界面可以自动选择，但生成的composition plan仍须显式记录
最终选择、来源路径、版本和SHA-256。

## 职责与目录

目标目录为：

```text
projects/<upstream>/
  config/interfaces/provided/

projects/<downstream>/
  config/interfaces/required/

common/contracts/
  component_port.schema.json
  connection_profile.schema.json
  composition_plan.schema.json

common/integration/
  resolve_connection.py
  execute_connection.ps1

integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/
  config/connection_profiles.json
  geometry/
  adapters/comsol/
  adapters/simion/
  tests/
  docs/INTEGRATION.md
  verify_integration.ps1
```

建立`integrations/`时必须同时建立单一integration registry、changed-scope路由、上述复合artifact身份和文档权威；
不得依靠目录发现或从相邻项目搜索脚本。integration不是第三份器件模型：它消费两端发布合同，只保存
连接本身和联合证据。

RF多极杆provided port至少发布规范交接面、坐标基、法向、孔径、公共电位、场有效区和canonical粒子
状态。单次反射oa-TOF required port至少发布入口面、坐标基、孔径、接受状态、场有效区和验收前提。
端口只定义
mating boundary，不拥有两者之间的连接器实体。

## 连接器代码归属

连接器按物理职责分类：

| 类型 | 代码与参数归属 |
|---|---|
| 零长度、无实体的canonical状态交接 | 只使用公共端口与组合合同，不创建连接器几何 |
| 通用无源圆筒、矩形管、接地孔等参数化primitive | solver-neutral描述与校验在`common/integration/`；具体实例参数在connection profile |
| 只适用于某一连接族的实体或场重叠区 | `integrations/<connection-family>/geometry`及solver adapters |
| 具有独立电极、脉冲、透镜、偏转或可单独验收功能 | 建立独立器件项目并发布自己的输入/输出端口 |

连接profile至少声明mating ports、实体长度、内孔、壁厚、材料、电势、相对位姿、场耦合模式、网格职责
和观察面。公共解析器生成唯一solver-neutral `resolved_connection`，并失败关闭以下冲突：

- 坐标、轴向、法向、单位或时钟不一致；
- 连接长度与端口间隙不符；
- 实体相交、留下未定义真空或孔径不满足合同；
- 电势不连续且未声明物理阶跃；
- 上游场、下游场和联合场责任区重叠或缺失；
- 规范交接面、近接口统计面、物理探测面和数值终止标记语义混同；
- COMSOL与SIMION不能投影同一resolved connection。

## 联合模拟模式

连接profile显式选择下列模式之一：

1. `state_handoff`：上游完成后把canonical粒子状态交给下游；两端独立求场。
2. `field_overlap`：连接区同时受两端场影响；integration拥有连接区联合场模型。
3. `monolithic_joint_solve`：两器件和连接器必须在同一求解模型中联合求场；专用adapter仍由公共编排器调用。

自动化只负责解析、验证、冻结和执行已声明的物理模式，不自动发明连接器或场拼接方法。

COMSOL/SIMION renderer在第二个不同integration真实复用前留在具体integration adapter；达到根README
的跨项目提升条件后，才把稳定投影提升到公共层，避免用尚未验证的抽象制造第二份实现。

## RF多极杆离子光学→单次反射oa-TOF实例

四、六、八极杆共享同一种多极杆家族出口端口，各项目profile提供具体几何和工作点。一个
integration family
`rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer`覆盖三者；当前迁移实例ID为
`rf_quadrupole_ion_optics_to_single_reflection_oa_tof_mass_analyzer`。六、八极杆后续分别建立同family
下的独立实例/profile，不得复制完整S2/S3。真实连接器、压力区、
脉冲机制或耦合模式不同时增加具名connection profile；只有出现新拓扑时才增加geometry和solver
adapter。

已归档的四极杆S2 spatial registration、S3 canonical state/clock和单次反射oa-TOF handoff adapter是
迁移oracle，不是未来公共API。迁移等价完成前不得删除、改写历史证据或把新框架的静态PASS解释为
联合物理资格。

## 迁移顺序与完成门禁

1. 在读取迁移比较结果前，冻结现有1 mm和0 mm S2/S3输入、几何、离散事件、连续比较字段、容差及
   继续调查规则作为oracle。离散身份/事件必须exact；连续量按
   [`VALIDATION_METHODS.md`](VALIDATION_METHODS.md)预登记的功能误差预算判断，禁止事后定阈值。
2. RF四极杆离子光学项目发布provided port；单次反射oa-TOF项目发布required port。
3. 建立公共schema、连接解析器、composition plan和integration artifact身份。
4. 用connection profile逐字段复刻现有连接器、位姿、场责任区和时钟。
5. COMSOL与SIMION从同一resolved connection投影，并完成静态几何/事件合同检查。
6. 新旧链以同一冻结粒子源完成配对等价复验；任何差异须归因，不得放宽阈值制造PASS。
7. 等价复验通过后，先按根README的history规则冻结必要的Markdown、同名载荷和SHA；再经删除授权让
   旧专用编排脚本退出活动源码。活动项目只保留端口发布/消费实现和文档链接。
8. 再增加六、八极杆profile及相称的数值和机械资格。

完成判据是减少重复权威和专用编排代码，同时保持现有负结果、运行身份、GUI可检查几何及商业求解器
证据可追溯；仅创建schema、空目录或自动生成计划不算完成。

截至2026-07-29，上述第1至5步的合同、解析、投影和静态门禁已经完成；旧S2/S3具名活动载荷已按SHA
冻结为history oracle。第6步真实配对等价复验仍为`BLOCKED/NOT_RUN`，第7步只完成了术语和活动权威
退出，历史证据及其原artifact身份继续只读保留。该实现进度不改变第6步对迁移验收的阻断作用。
