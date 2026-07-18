# COMSOL 6.4 + MATLAB LiveLink API参考

本文件只保存跨项目成立的COMSOL Model Object API、MATLAB LiveLink调用和GUI对等要求。
通用排错见[`COMSOL_DEBUGGING.md`](COMSOL_DEBUGGING.md)，网格、统计和跨求解器闭合见
[`VALIDATION_METHODS.md`](VALIDATION_METHODS.md)。器件几何、物理组合、具体参数和运行结论
写入对应项目文档。

本文件用于按API名或语义标题搜索，不要求人或AI线性通读。跨文档引用使用标题，不使用章节数字。

## 执行入口与会话生命周期

正式任务使用`common/comsol/run_comsol_r2025b.ps1`驱动`matlab.exe -batch`并建立
MATLAB LiveLink/Java API连接。任务脚本只使用已建立的连接，不再次调用`mphstart`。

```matlab
import com.comsol.model.*
import com.comsol.model.util.*
model = ModelUtil.create('Model');
```

- 同一任务内连续完成建模、求解、保存和验收，避免反复启动服务。
- 不跨独立任务长期复用服务端；长期会话会积累模型标签、Java内存和客户端状态。
- 创建或加载前清理同名模型，任务结束显式`ModelUtil.remove(tag)`或`ModelUtil.clear`。
- 启动器只可在任务报告尚未创建时对连接初始化失败自动重试；业务脚本开始后不得自动重算。
- 首次使用一个直连脚本先做最小连接、创建模型和保存MPH测试。

## GUI对等与节点管理

正式模型的几何、材料、参数、变量、函数、选择集、物理条件、网格、Study、Solver、数据集、
派生值、绘图和导出必须持久化为Desktop Model Builder中可见、可编辑、可保存的节点或属性。
脚本不得把关键物理或数值逻辑只留在MATLAB变量、后处理或Server内存中。

自定义Solver序列要显式附着到Study：

```matlab
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').attach('std1');
```

验收不能只运行`model.sol(...).runAll`。保存并重新打开MPH后，必须确认Study的GUI Compute会
使用预期Solver和物理激活状态并产生等效结果。

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
`StationarySourceSweep`用于多源扫描，不是单线圈的通用替代。CPT磁力特征名是
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

- `hmax`是单元最大尺寸上限，不代表所有单元固定等大。
- 薄层、间隙、强边缘场和释放区使用局部Size，不靠全局无限加密。
- 网格成功后仍要检查单元数、最小质量、目标域覆盖和空网格。
- 理想边界附近的几何间隙与局部`hmax`共同设计；任意极小间隙可能导致顶点约束失败。
- 网格收敛改变受控网格变量，并比较项目规定的场量、轨迹量和统计指标。

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
- 不猜`cpt.Ep`、`cpt.KE`等变量；先查变量表。末态动能可由质量和速度计算并与能量守恒交叉
  检查。

## 已确认无效或危险的调用

|调用或做法|问题|正确方向|
|---|---|---|
|`model.multiphysics.create(...,'ElectricForce',...)`|对象层级错误|在CPT下创建`ElectricForce`|
|`geom.getNEdge(tag)`|方法不存在|使用`mphgeominfo`|
|`comp.physics.create('mf','MagneticFields',...)`|当前环境类型名无效|用GUI录制或已验证类型|
|`cpt.create(...,'LorentzForce',...)`|特征名无效|使用`MagneticForce`|
|`std.create(...,'CoilGeometryAnalysis')`|Study类型错误|使用当前版本支持的Coil步骤|
|`StationarySourceSweep`用于单线圈|无source可扫|使用单线圈Study|
|`cpt.Ep`、`cpt.KE`等猜测变量|可能未定义|检查变量表或由速度计算|
|`mpheval`读取粒子坐标|语义错误|使用`mphparticle`|
|`outersolnum='end'`取末态|可能返回全部时间×粒子|显式时间或事件|
|`notsolnum`、`notstudy`等|Unknown property|使用已验证的`notsolmethod`/`notsol`|
|只设置默认Size后直接网格|复杂几何可能产生空网格|显式FreeTet并检查统计|
|力、材料或边界不设selection|可能静默作用错误或处处为零|显式命名选择并验空|
|`Inlet.v0`给标量|需要三维向量|设置三个分量|
|把自定义物理tag作为变量前缀|Undefined variable|检查自动变量命名空间|

## 官方资料与验证顺序

查证顺序：当前版本GUI Record Code → Programming Reference Manual → 对应Module User’s Guide →
最小脚本 → 生成MPH的GUI Compute验收。

- `COMSOL_ProgrammingReferenceManual.pdf`：Model Object API、feature类型、属性和合法值；
- `LiveLinkForMATLABUsersGuide.pdf`：`mph*`函数和MATLAB连接；
- `ParticleTracingModuleUsersGuide.pdf`：Release、Inlet、Wall、Force和碰撞；
- `ACDCModuleUsersGuide.pdf`：静电、磁场和Coil；
- `ApplicationProgrammingGuide.pdf`：Application Builder，仅在构建Desktop应用时使用。

官方文档证明接口语义，不能替代最小脚本和正式MPH的GUI验收。
