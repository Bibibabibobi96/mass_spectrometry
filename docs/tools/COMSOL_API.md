# COMSOL 6.4 + MATLAB LiveLink API参考

本文件汇集 COMSOL 6.4 Model Object API 与 MATLAB LiveLink 的调用参考；代码片段展示对象关系，
不是可独立运行的项目脚本。适用范围限于本仓库已记录环境，升级后须重新核验相关调用。
本页只维护调用写法和接口边界；任务分流返回[COMSOL 阅读入口](COMSOL_GUIDE.md)。
器件几何、物理组合、具体参数和运行结论写入对应项目文档。
仓库封装的启动器、几何／网格原语和组件测试 API 由[公共实现](../../common/comsol/README.md)说明，
不在本页复制其参数、重试规则或资源协议。

本文件用于按API名或语义标题搜索，不要求人或AI线性通读。跨文档引用使用标题，不使用章节数字。

## 按专题定位

| 需要的接口 | 章节 |
|---|---|
| 创建连接、Study 关系与活动步策略 | [执行入口](#执行入口与会话生命周期)、[节点管理](#gui对等与节点管理)、[Time 活动键](#time-节点的活动步策略) |
| 几何实体与作用范围 | [参数与单位](#参数表达式与单位)、[几何](#几何)、[选择集](#选择集)、[材料](#材料) |
| 物理场与粒子节点 | [静电](#静电场)、[磁场与线圈](#磁场与线圈)、[粒子追踪](#带电粒子追踪) |
| 网格、局部表达式与稳态求解 | [网格](#网格)、[SizeExpression 单位](#sizeexpression-的显式长度单位)、[初值与场复用](#studysolver与初值复用)、[CG-AMG](#稳态cg-amg与电势阶次) |
| 输出、插值数据与读取 | [数据集](#数据集绘图和导出)、[更新插值数据](#更新已嵌入模型的插值数据)、[数值提取](#数值提取) |
| 错误调用、来源和已验证层级 | [无效调用](#已确认无效或危险的调用)、[官方查证顺序](#官方资料与验证顺序)、[证据范围](#关键能力的证据索引) |

## 执行入口与会话生命周期

正式入口和版本选择见[操作指南](../OPERATIONS.md)，部署参数、启动失败分类与重试行为见
[共享启动器](../../common/comsol/README.md#正式启动入口)。下列片段在入口已建立的连接中执行：

```matlab
import com.comsol.model.*
import com.comsol.model.util.*
model = ModelUtil.create('Model');
```

- 同一任务内连续完成建模、求解、保存和验收，避免反复启动服务。
- 不跨独立任务长期复用服务端；长期会话会积累模型标签、Java内存和客户端状态。
- 创建或加载前清理同名模型，任务结束显式`ModelUtil.remove(tag)`或`ModelUtil.clear`。
- 首次使用一个直连脚本先做最小连接、创建模型和保存MPH测试。

## GUI对等与节点管理

GUI 对等的通用判据见[仓库架构](../REPOSITORY_ARCHITECTURE.md)。本节说明 COMSOL 中如何持久化
Study/Solver 关系；节点存在与脚本调用成功仍须由保存后重开检查确认。

自定义Solver序列要显式附着到Study：

```matlab
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').attach('std1');
```

验收不能只运行`model.sol(...).runAll`。保存并重新打开MPH后，必须确认Study的GUI Compute会
使用预期Solver和物理激活状态并产生等效结果。

### Time 节点的活动步策略

先读取 `odesolvertype`，再读取对应的活动积分器；不能因某个属性存在就认定它生效。
COMSOL 6.4 的 [Time API 表 6-74](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.51.html)
给出的对应关系如下（查阅日期：2026-10-21）：

| 活动配置 | 步策略属性 |
|---|---|
| `implicit`，`timemethod=genalpha` | `tstepsgenalpha` |
| `implicit`，`timemethod=bdf` | `tstepsbdf` |
| `explicit`，`timemethodexp=rk`，`rkmethod=dopri5` | `tstepsdopri5` |

`free` 允许积分器依据误差控制选择内部步；`strict` 要求内部步包含输出时刻，仍可插入其他内部步。
`tout=tlist` 控制在请求时刻插值保存，和活动步策略是两个设置。写入后、保存重开后及 Study Compute 后
都应核对活动键与 `tout`；检查闲置 BDF 键不能证明 GA 或 DP5 的设置正确。未知组合应显式拒绝，
不可依赖闲置属性的默认值。属性保存重开验证本身不证明轨迹收敛或性能收益。

## 参数、表达式与单位

```matlab
p = model.param;
p.set('L', '20[mm]', 'electrode length');
p.set('V0', '100[V]', 'electrode voltage');
```

- 物理量使用带单位表达式；拓扑数量、布尔开关和索引使用无单位值。
- 几何和位置从项目参数契约派生，不在多个脚本中重复硬编码。
- GUI需要调整的量写为Parameter；可复算表达式写为Variable或Function。
- 自定义物理接口tag不决定内置变量命名空间。多个同类接口通常使用`es`、`es2`等自动名称，
  必须由模型检查或官方文档确认。
- `geom.lengthUnit('mm')`后，`mphinterp`坐标也按模型几何单位解释；传入米值可能不报错但落在
  网格外并返回错误结果。

## 几何

```matlab
comp = model.component.create('comp1', true);
geom = comp.geom.create('geom1', 3);
geom.lengthUnit('mm');
blk = geom.feature.create('blk1', 'Block');
blk.set('size', {'10','20','30'});
blk.set('pos', {'0','0','0'});
geom.run;
```

常见特征包括`Block`、`Cylinder`、`Sphere`、`Cone`、`Difference`、`Union`、
`Intersection`、`WorkPlane`和`Extrude`。布尔运算输入使用几何特征tag。

`Fillet`和`Chamfer`可能受CAD Import Module或Design Module许可证限制。正式环境不可用时，
用基础实体与布尔运算构造等价几何，并验证包围盒、实体数、对称和关键尺寸。

`geom.run`后使用`mphgeominfo`查询拓扑；不要猜测不存在的`geom.getNEdge(tag)`：

```matlab
info = mphgeominfo(model, 'geom1');
```

组件的几何表示阶次通过 `comp.sorder('quadratic')` 设置、`comp.sorder()` 回读；它与电势形函数阶次、
单元尺寸及时间容差分别记录。[官方曲面网格说明](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.10.html)
明确粒子碰撞采用边界网格表示，因此曲面命中精度还须独立检查几何表示，不能仅加严时间积分。
高阶值的实际适用性从项目验收读取，不设置全仓默认阶次。

## 选择集

物理场优先引用命名选择，不依赖几何改变后可能漂移的裸实体编号。

```matlab
sel = comp.selection.create('sel_electrode', 'Explicit');
sel.geom('geom1', 2);
sel.set(boundaryIds);
```

- 几何特征可开启`selresult='on'`生成命名选择。
- 使用`Adjacent`从域选择得到相邻边界；复杂集合运算可在MATLAB中显式完成后写入`Explicit`。
- 每次几何重建后检查选择非空、没有错误实体并覆盖所有预期实体。
- 未验证前不要猜组件级`Union`/`Difference`选择的`input2`等属性。

## 材料

```matlab
mat = comp.material.create('mat1', 'Common');
mat.label('Vacuum');
mat.propertyGroup('def').set('relpermittivity', '1');
mat.propertyGroup('def').set('electricconductivity', '0[S/m]');
mat.selection.set(domainIds);
```

材料选择必须显式。几何实体存在不等于材料或物理场会自动覆盖该域。

## 静电场

```matlab
es = comp.physics.create('es', 'Electrostatics', 'geom1');
pot = es.feature.create('pot1', 'ElectricPotential', 2);
pot.selection.set(electrodeBoundaries);
pot.set('V0', 'V0');
gnd = es.feature.create('gnd1', 'Ground', 2);
gnd.selection.set(groundBoundaries);
```

- 电势、接地和电荷条件绑定命名选择并检查选择非空。
- 不同电位导体不得因几何容差意外接触或合并。
- 理想栅网可表达为内部边界，但必须保持真空域连通性，并验证两侧网格和粒子穿越语义。
- 多个Electrostatics接口的变量前缀按接口顺序生成，不能把自定义tag直接当变量前缀。

## 磁场与线圈

物理接口的内部类型名以当前版本Model Object文档和GUI录制为准。当前环境验证的AC/DC磁场
接口类型为`InductionCurrents`；猜测`MagneticFields`会得到Unknown physics interface。

```matlab
mf = comp.physics.create('mf', 'InductionCurrents', 'geom1');
coil = mf.feature.create('coil1', 'Coil', 3);
coil.selection.set(coilDomains);
coil.set('CoilType', 'Numeric');
```

Numeric Coil通常需要正确的线圈材料、端子/方向信息和`CoilCurrentCalculation` Study步骤。
`CoilGeometryAnalysis`不是本环境的有效 Study 类型；`StationarySourceSweep`用于多源扫描，
不是单线圈的通用替代。CPT磁力特征名是
`MagneticForce`，不是`LorentzForce`；力特征必须显式选择粒子域。

## 网格

复杂三维几何显式创建体网格特征并检查统计：

```matlab
mesh = comp.mesh.create('mesh1');
mesh.feature('size').set('hauto', 3);
ftet = mesh.feature.create('ftet1', 'FreeTet');
ftet.selection.geom('geom1', 3);
ftet.selection.set(domainIds);
mesh.run;
stats = mphmeshstats(model, 'mesh1');
```

选择性网格化时，完整性判据必须限定到实际建网域。COMSOL 6.4 Build 293、R2025b 的真实只读复核中，
`mphmeshstats`即使传入域选择仍返回`iscomplete=false`，因为该包装结果不能可靠替代“所选域是否全部有网格”
这一问题；同一模型改用原生`MeshStatistics`选择两个真空域后，`isComplete()`为`true`，
`getNumElem('tet')`返回两域合计的11992696个四面体。最小读取方式是：

```matlab
meshStats = model.component('comp1').mesh('mesh1').stat();
meshStats.selection().geom('geom1', 3).set(int32(domainIds));
selectedComplete = meshStats.isComplete();
selectedTetCount = meshStats.getNumElem('tet');
```

官方[Mesh Statistics](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_mesh.49.026.html)
和[Mesh Status](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_mesh.49.031.html)
说明`stat().selection()`限定统计实体，`isComplete()`检查全部所选实体是否已有网格；
[`model.mesh()` API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.41.html)
给出`selection.geom(dim).set(entities)`的选择语法。该方法只纠正统计作用域：不把未建网的其他几何域
判作所选域失败，也不放宽所选域的空网格、单元数、质量或后续求解门禁。

- `hmax`是单元最大尺寸上限，不代表所有单元固定等大。
- 薄层、间隙、强边缘场和释放区使用局部Size，不靠全局无限加密。
- 网格成功后仍要检查单元数、最小质量、目标域覆盖和空网格。
- 理想边界附近的几何间隙与局部`hmax`共同设计；任意极小间隙可能导致顶点约束失败。
- 网格收敛改变受控网格变量，并比较项目规定的场量、轨迹量和统计指标。

### SizeExpression 的显式长度单位

COMSOL 6.4 Build 293、R2025b 的真实小立方体建网对照确认：毫米几何并不使无单位
`sizeexpr='0.0625'`自动成为0.0625 mm。必须在表达式结果上显式携带长度单位，例如
`'0.0625[mm]'`或`'(无量纲毫米数值表达式)*1[mm]'`；空间条件也显式使用`x/(1[mm])`等。
同一1-mm立方体、0.25-mm全局hmax及0.04-mm hmin下，无单位表达式与基线均为969个四面体；
显式mm后为68645个，单元最长边中位数0.06546 mm，与普通Size同目标的68653个相符。
显式selection.all或importData没有进一步改变该结果；不要靠增加无关API调用修复单位问题。
官方[SizeExpression API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_mesh.49.101.html)
说明默认selection覆盖全部实体，importData用于更新后的重新求值；尺寸表达式还受到实体hmin限制。
2026-10-02的本机对照是接口语义验证，不授予任何仪器网格收敛资格。局部加密须检查实际单元尺寸，
不能只依据表达式文本声明成功。

同时检查最小尺寸：只修改全局hmax不会自动把既有hmin降低到局部表达式以下。
官方[Size Expression说明](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_mesh.24.86.html)
指出实体hmin会截断表达式的局部尺寸。2026-10-04同一20-mm双块的两例mesh-only对照中，
hmax=2.5 mm、局部表达式1.25 mm不变，仅hmin从11.9改为0.25 mm：目标区最长边中位数
2.4604降至1.4594 mm，远区2.6337至2.6374 mm。需要局部加密时显式设置相容的hmin并检查
实际网格；这不要求改变所有既有模型的默认值，也不是仪器电场或轨迹收敛证据。

## 带电粒子追踪

```matlab
cpt = comp.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
ef = cpt.feature.create('ef1', 'ElectricForce', 3);
ef.selection.set(vacuumDomains);
```

`ElectricForce`和`MagneticForce`是CPT接口下的特征，不是顶层multiphysics coupling。

### 粒子释放

- 从边界释放使用`Inlet`，不是`ReleaseFromBoundary`。
- 域内释放使用`Release`并在三维域级创建；点级创建会失败。
- `Inlet.v0`需要长度为3的向量，例如`{'0','0','v0'}`，不能给标量。
- `Release.InitialPosition`合法值依版本和特征而定，使用GUI录制或属性表确认，不猜`Manual`。
- 固定随机研究必须持久化种子、样本量和逐粒子初值，以支持跨求解器配对。

### 壁面、终止和碰撞

`Wall`、Freeze/Disappear等行为必须落为GUI节点并绑定选择。碰撞由`Collisions`父特征加具体
子特征（如`Elastic`或`ResonantChargeExchange`）组成；只创建父节点可能没有实际碰撞。
粒子间库仑作用使用`ParticleParticleInteraction`，当前验证属性为
`InteractionForce='Coulomb'`。

[Particle Counter](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.20.html)
的 `<tag>.rL` 是选中区域的后处理入选逻辑，不是通用的最后停止边界编号。官方允许后加变量并调用
`model.sol('sol1').updateSolution()`，但不重算成功不保证某个采样／读取路径的计数正确；实测范围查
[共享证据索引](../../common/comsol/README.md#关键能力的证据索引)。

## Study、Solver与初值复用

典型流程先求静电/磁场稳态，再用时间相关粒子Study复用已存场：

```matlab
std1 = model.study.create('std1');
stat = std1.create('stat', 'Stationary');
stat.activate('es', true);
stat.activate('cpt', false);

std2 = model.study.create('std2');
time = std2.create('time', 'Transient');
time.activate('es', false);
time.activate('cpt', true);
time.set('tlist', 'range(0,dt,tend)');

model.sol.create('sol2');
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', 'sol1');
model.sol('sol2').attach('std2');
```

仅停用时间Study中的`es`不会自动保证CPT复用静电解；未求解变量可能回落到零初值且不报错。
用同一点在稳态和粒子数据集上的场值交叉检查。`notsolnum`、`notstudy`、`notsollist`等猜测
属性已确认无效。

不要把 `mphxmeshinfo` 的字段／DOF 库存直接当成“本步求解的变量”。官方
[Variables](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.57.html)
会自动维护已求解与未求解变量的 Field；实际是否求解须检查 `Field.solvefor` 及 Study。
[Xmesh](https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_functionality.7.36.html)
的 `dofs.nameinds` 与 `solvectorinds` 均使用零基映射。比较静电场时保留原始全量差异，另外核对
全部电势系数、DOF 坐标／节点映射、网格与有限元阶次，不能以少数场探针相等替代场身份。
坐标单位须独立核对：[XmeshInfoDofs](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/api/com/comsol/model/XmeshInfoDofs.html)
区分模型长度单位 `coords()` 与几何长度单位 `gCoords()`；不能仅凭 `geom.lengthUnit()` 给扩展网格数组标单位。
解析比较应保留原坐标、显式换算，并用带单位的 `x/y/z` 回读核验；网格顶点与扩展网格 DOF 也不可默认同单位。

### 稳态CG-AMG与电势阶次

COMSOL 6.4的自动稳态序列可在`Stationary`下保留默认direct节点，同时把`FullyCoupled`的活动
`linsolver`显式切换到迭代节点；未被引用的默认direct兄弟节点不等于运行时fallback。当前R2025b
LiveLink最小模型已验证：

```matlab
stationary = solution.feature('s1');
advanced = stationary.feature('aDef');
advanced.set('convinfo', 'detailed');
iterative = stationary.feature.create('i1', 'Iterative');
iterative.set('linsolver', 'cg');
iterative.set('maxlinit', 500);
iterative.set('errorchk', 'on');
multigrid = iterative.feature.create('mg1', 'Multigrid');
multigrid.set('prefun', 'amg');
stationary.feature('fc1').set('linsolver', 'i1');
```

稳态容差由`stationary.set('control','user')`和`stationary.set('stol',value)`设置；详细收敛信息属于
`Advanced`子节点，不写到`Stationary`本身。电势单元阶次通过
`es.prop('ShapeProperty').set('order_electricpotential',1|2)`设置。该`PhysicsPropClient`在当前版本
没有MATLAB可调用的`getInt`；应使用`getString`后显式转换并回读核对。

`ModelUtil.showProgress(path)`可保存原生求解日志，完成后用`ModelUtil.showProgress(false)`恢复。
详细日志表头包含`LinIt`和`LinRes`；需要证明实际迭代执行时，应保留原生日志并要求正`LinIt`与有限
`LinRes`，不能用求解器节点存在或Study成功代替。

## GPU求解器

cuDSS不是默认加速开关。是否启用必须用相同模型、网格和容差比较CPU/GPU总耗时、峰值内存和
数值差异。小中型静电/CPT模型可能因初始化和数据传输比CPU更慢；未经项目基准验证不在正式
模式默认开启GPU。

## 数据集、绘图和导出

粒子轨迹使用`Particle`数据集；普通`Solution`数据集不能替代粒子语义。

```matlab
pdset = model.result.dataset.create('pdset1', 'Particle');
pdset.set('solution', 'sol2');
pg = model.result.create('pg_traj', 'PlotGroup3D');
pg.set('data', 'pdset1');
pg.create('traj1', 'ParticleTrajectories');
```

绘图组、派生值和导出必须保存为GUI节点。图片导出使用`Image`导出节点并设置`plotgroup`、
文件名和尺寸。保存MPH后重新检查数据集引用、绘图、派生值Evaluate和导出路径。

### 更新已嵌入模型的插值数据

外部文件插值函数的`importData()`将数据嵌入模型；保存并重载后，不能假定修改filename再调用
importData就会替换旧载荷。本机COMSOL 6.4小函数试验复现了该路径的Unsupported function
operation；先`discardData()`、明确`source=file`、设置新filename再`importData()`，求值由
10变20，随后在既有三维网格的真实静电重解中通过。此经验适用于更新已嵌入数据的函数，
不要求新建函数的正常首次导入额外执行discardData，也不改变物理边界或插值方法。
官方[函数API](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.34.html)
分别定义importData的嵌入、discardData的丢弃及refresh的重新读取语义；按函数当前数据来源选择，
不把三者无条件串联。2026-10-04的独立小函数试验与模型复用验证只证明接口交接，不是场收敛证据。

## 数值提取

`mphinterp`适合指定坐标插值，`mpheval`适合在FEM网格实体上求值：

```matlab
E = mphinterp(model, {'es.Ex','es.Ey','es.Ez'}, ...
    'coord', xyz, 'dataset', 'dset1');
d = mpheval(model, 'es.V', 'dataset', 'dset1', 'edim', 3);
```

检查返回数组维度和单位，不假定单点或单表达式始终保持固定行列方向。

粒子坐标、速度和时间使用`mphparticle`，不用`mpheval(...,'edim',0)`冒充粒子数据；后者可能
静默返回FEM顶点。不要给Particle数据集传`edim`。

```matlab
pd = mphparticle(model, 'dataset', 'pdset1');
```

- 显式指定目标时间或事件，不用`outersolnum='end'`假定只取最后时间步。
- NaN按粒子终止语义单独统计，不能简单删除后宣称全部通过。
- 用粒子ID配对，不依赖返回顺序。
- `mphparticle` 的 `evaluate` 不能当作任意粒子 ID 列表。本机 6.4 小模型中，正整数表示抽取数量，
  `evaluate=1` 返回的并非 ID 1，向量 `[59 1]` 被拒；先回读 `cpt.pidx` 和初值再判断身份。
  [官方 Particle Evaluation 表](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_results.52.119.html)
  同样区分 all／fraction／number，number 为数量；不能据此构造未经验证的逐 ID 分块优化。
- 本机 6.4 的 `solnum='all'` 可以成功返回全部表达式数组，却不带 `t`，显式 `times='on'` 也未补上。
  数值 `solnum=1:n` 的实测表达式与之相同，并返回时间与索引；`n` 必须来自实际解库存。
  保留返回字段、维度和粒子身份，不把包装器访问缺失 `t` 的异常记成求解失败。
- `mphparticle(...,'expr',cell)` 与原生数值节点不是相同的参数合同：本机
  `model.result.numerical.create(tag,'Particle')` 的 `expr` 只接受单字符串，多表达式须逐条读取并核对身份。
- 多个粒子physics的tag、变量identifier、particle geometry与位置DOF不一定同名。本机6.4保存／冷重开探针中，
  physics `cpt/cpt1/cpt2`对应identifier `cpt/cpt2/cpt3`，应绑定实际solution、`pgeom`、`posdof`，不按tag猜变量。
  使用官方`mphparticle(...,'velocities','on')`的`pd.v`，按实际维度解释，并以实际identifier的速度表达式交叉检查；
  `comp1.vx/v2x/v3x`等猜测在该探针全NaN，不能由`omitnan`聚合成零误差。逐ID检查活动掩码、至少一个有效状态、
  活动位置对应的完整有限速度，再计算误差。未出生／已终止状态的NaN保留其生命周期含义。
  官方[Particle Dataset](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_results.52.118.html)
  没有`veldof`属性，不新增猜测设置；本机help `Multiphysics/mli/mphparticle.m`列出`pd.v`与velocities选项。
  2026-10-30的N=3零求解冷读证据及限制见[RF项目状态](../../projects/rf_multipole_ion_optics/docs/PROJECT.md#当前结论)。
- 不猜`cpt.Ep`、`cpt.KE`等变量；先查变量表。末态动能可由质量和速度计算并与能量守恒交叉
  检查。

## 已确认无效或危险的调用

错误调用及其替代写法已放在相应接口旁：对象层级和 Feature 名见物理场章节，空网格与选择见
网格／选择章节，解复用属性见 Study 章节，粒子／FEM 数据语义见数值提取。不要把这些已知负结果
当作新候选在仪器模型中重试。

## 官方资料与验证顺序

查证顺序：当前版本GUI Record Code → Programming Reference Manual → 对应Module User’s Guide →
最小脚本 → 生成MPH的GUI Compute验收。

离线文件与按问题定位见[官方资料索引](../references/software/README.md)。手册索引记录本机版本与问题对应的原始章节。
本页未给出每项调用的独立验证运行，不能把整页视为逐项已认证的 API 清单。
优先按证据索引区分接口语义、真实求解、保存重开和项目验收；没有登记的层级表示本索引未建立证据，
不表示该层级必然失败，也不由源码或 MPH 文件存在推定通过。

### 关键能力的证据索引

关键调用的实测矩阵集中在[共享测试的证据索引](../../common/comsol/README.md#关键能力的证据索引)：
分别列出官方接口语义、真实 Study/Solver 执行、保存重开、GUI Compute 与项目验收的已知范围。
共享测试目录中的源码覆盖不等于已运行结果；接口事实不自动授予仪器收敛或性能资格。

官方文档证明接口语义，不能替代最小脚本和正式MPH的GUI验收。


RF finite 正式已解读取边界为项目 `reextract_finite_3d_transport(request,fid)`：原冻结设计／源／数值投影与实际 source/native-order 映射绑定原两组解，通过 `mphload` 只读加载，再调用正常求解后的同一分窗导出 helper。缺原映射不推断粒子顺序；不存在必要 Particle dataset 时只在内存建立并绑定已解 solution，不调用 Study Compute／runAll，不保存父模型。2026-10-31正常 CLI 的071000→062508冷提取读取43,350,302 B原MPH，七份CSV与原导出逐字节一致，原父manifest不变；这是既有解读取／接口验证，不新增物理、收敛或完整传输资格。后继纯CSV分析及仅收尾恢复不加载模型，精确记录见[RF项目状态](../../projects/rf_multipole_ion_optics/docs/PROJECT.md#当前结论)。
