# COMSOL 6.4 + MATLAB LiveLink：通用 API / 调用速查手册

> **适用范围**：所有质谱仪(及同类粒子光学)COMSOL自动化建模项目都会用到的通用知识——
> 怎么建几何、怎么设物理场、怎么追踪粒子、怎么取数据、已经验证过的部件库。
> **不含**特定项目的具体参数/踩坑叙事（那些在项目`docs/PROJECT.md`里），也**不含**通用调试
> 方法论(那些在`COMSOL_DEBUGGING.md`里)。

---

## 0. 技术路线：MATLAB LiveLink/Java API 直连 COMSOL

本手册默认把`common/comsol/run_comsol_r2025b.ps1`驱动的MATLAB LiveLink/Java API作为正式
执行路径。入口负责启动COMSOL/MATLAB、建立唯一连接、注入任务脚本和回收进程；任务脚本只使用
已经建立的连接，不得再次调用`mphstart`。

**正式、复杂或需要精确项目专属后处理的实现都走这条直连路径**：
```matlab
import com.comsol.model.*
import com.comsol.model.util.*
model = ModelUtil.create('Model');
```
- 每个完整任务通过标准PowerShell入口非交互调用；同一任务内连续完成相关阶段，避免为小检查频繁
  重启MATLAB/COMSOL。
- 不跨独立任务长期复用服务端。长期会话会积累模型标签、Java内存和客户端状态；大粒子结果读取
  可单独使用第二个干净任务，避免Compute后立即大传输触发客户端崩溃。
- 标准入口仅在任务报告尚未创建时对启动崩溃自动重试一次；业务脚本开始后的失败不得自动重算。
- 这条路径不依赖 MATLAB 图形界面/许可证之外的东西，比"COMSOL Java 源码 + comsolcompile +
  comsolbatch"更适合迭代调试。
- 项目里的专用后处理必须由正式脚本完成。例如oa-TOF分辨率必须沿用项目脚本的探测器交叉时刻插值
  与`R=mean(t)/(2*std(t))`判据；仅直接读取粗`tlist`网格点会引入时间量化误差。

---

## 1. Java API 建模层的具体坑

### 1.1 组件与几何创建
```matlab
comp1 = model.component.create('comp1', true);      % 2参数 (tag, boolean)，没有维度参数
geom1 = comp1.geom.create('geom1', 3);               % 维度在这里指定
geom1.lengthUnit('mm');                               % 会影响后续插值坐标单位（见§2.6坑A）
```

### 1.2 Fillet / Chamfer 可能受许可证限制
`geom1.feature.create('fil1','Fillet')` / `'Chamfer'` 报错 "The requested geometry
operation is unknown or cannot be created in this context"——即使最简单的单个圆柱体也
失败，是许可证/模块限制（可能需要 Design Module）。**排查方法**：先在空白模型里对最简单
的图元单独测试，如果连这个都失败就直接切换方案。

**替代方案：用 Cone（圆锥台）− Cylinder 布尔差手工构造 45° 倒角**：
- 外圈顶部边缘：`Cylinder(r=R, h=d, pos=z_top-d)` 减去 `Cone(r=R, rtop=R-d, h=d, pos=z_top-d)`
- 外圈底部边缘：`Cylinder(r=R, h=d, pos=z_bot)` 减去 `Cone(r=R-d, rtop=R, h=d, pos=z_bot)`
- 内孔顶部边缘：`Cone(r=r_hole, rtop=r_hole+d, h=d, pos=z_top-d)` 减去 `Cylinder(r=r_hole, h=d, pos=z_top-d)`
- 内孔底部边缘：`Cone(r=r_hole+d, rtop=r_hole, h=d, pos=z_bot)` 减去 `Cylinder(r=r_hole, h=d, pos=z_bot)`
- 最后一次 `Difference` 把所有倒角工具体从母体减掉。

**Cone 图元属性名**（容易搞错）：
```matlab
geom1.feature(coneTag).set('r', baseRadius);          % 底面半径
geom1.feature(coneTag).set('specifytop', 'radius');   % 字符串'radius'，不是boolean
geom1.feature(coneTag).set('rtop', topRadius);         % 顶面绝对半径，不是'r2'/'ratio'
geom1.feature(coneTag).set('h', height);
```

### 1.3 几何信息查询
`geom1.getNEdge(tag)` 这类方法不存在，用：
```matlab
gi = mphgeominfo(model, 'geom1');   % 字段大写开头：Ndomains, Nboundaries, Nedges, Nvertices
```

### 1.4 命名选择集（Selection）的建立方式
- 给几何图元开启自动域选择：`geom1.feature(tag).set('selresult','on')`，之后用固定命名
  规则 `geom1_<featureTag>_dom` 引用。
- 拿"某个域的边界面"，建组件级 `Adjacent` 选择：
  ```matlab
  comp1.selection.create('selb_x', 'Adjacent');
  comp1.selection('selb_x').set('input', {'geom1_xxx_dom'});
  ```
- 在材料/物理场里引用命名选择：`feature.selection.named('selection_tag')`。

### 1.5 材料、静电场物理场、网格、稳态求解 —— 标准套路
```matlab
mat = model.material.create('mat1','Common');
mat.selection.named(sel_tag);
mat.propertyGroup('def').set('relpermittivity', {'1'});

es = comp1.physics.create('es','Electrostatics','geom1');
es.selection.named(sel_vac_tag);
pot = es.create('pot1','ElectricPotential', 2);   % 2 = 边界(面)级别
pot.selection.named(selb_tag);
pot.set('V0','V_value_or_param');

mesh1 = comp1.mesh.create('mesh1');
mesh1.feature('size').set('hauto', 3);  % 1=最细...9=最粗，Finer≈3
mesh1.run;

std1 = model.study.create('std1');
std1.create('stat1','Stationary');
model.sol.create('sol1');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
model.sol('sol1').attach('std1');  % 让 GUI Study Compute 复用该序列，不另生 sol3
model.sol('sol1').runAll;
```

### 1.6 结果绘图常见属性名坑
- `Slice` 图层切面方向属性是 `quickplane`，合法取值 `"xy"|"yz"|"zx"`（**不是** `"xz"`）。
- 默认一个方向会自动铺开好几个切面，只要单张切面需要显式设：
  ```matlab
  sl1.set('quickznumber','1'); sl1.set('quickxnumber','1'); sl1.set('quickynumber','1');
  ```
- 图片导出：`model.result.export.create(tag,'Image')`，设置 `plotgroup`、`pngfilename`、
  `width`、`height`，然后 `.run`。

---

## 2. 带电粒子追踪（CPT）专项坑

### 2.1 物理场与默认特征
```matlab
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
```
自动带有：`wall1`（Wall，默认`WallCondition=Freeze`且`Otherwise=Freeze`，即默认对所有边界
"冻结/吸收"粒子，同时天然充当"末端探测面"）、`pp1`（ParticleProperties，默认已经是电子：
`mp=me_const`, `Z=-1`）、`dpcon1`（PairContinuity，装配体配对用，普通模型忽略即可）。

### 2.2 从边界发射粒子：特征类型叫 `Inlet`，不是 `Release`/`ReleaseFromBoundary`
```matlab
inl1 = cpt.create('inl1', 'Inlet', 2);   % 2 = 边界级别
inl1.selection.named(sel_emit_surface);
% 默认 v0=0，方向默认沿边界法向
```

### 2.3 电场耦合到粒子受力：`ElectricForce` 是 cpt 物理场下的特征，不是顶层 multiphysics 节点
```matlab
% 错误：model.multiphysics.create('epf1','ElectricForce', ...)  -> "Unknown multiphysics coupling"
ef1 = cpt.create('ef1', 'ElectricForce', 3);   % 3 = 域级别
ef1.selection.named(sel_vac_tag);
ef1.set('E_src', 'root.comp1.es.Ex');          % 必须是这个完整限定字符串
```
**技巧**：不确定合法值时，先随便 set 一个错误值，COMSOL 报错信息通常会直接列出所有合法取值。

### 2.4 时间相关粒子追踪 Study：复用已求解的静电场
```matlab
std2 = model.study.create('std2');
tstep = std2.create('time1', 'Transient');
tstep.set('tlist', 'range(0,0.1[ns],40[ns])');
tstep.setEntry('activate','es', false);
tstep.setEntry('activate','cpt', true);

% !!! 高优先级坑：仅 setEntry('activate','es',false) 不会让 cpt 自动复用已解的 es 场！
% createAutoSequence 生成的 Variables 节点(v1)默认 notsolmethod='init'（未求解变量取值
% 落回初始值，对es场约等于全0），导致 ElectricForce 处处为0，粒子以v0=0释放后完全不动，
% 且不报任何错——比图形问题更隐蔽。必须显式指向 Study 1 的解：
model.sol.create('sol2'); model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');  % 'sol'=用存储解
model.sol('sol2').feature('v1').set('notsol', 'sol1');       % 属性名是notsol，不是notsolnum！
model.sol('sol2').attach('std2');                             % 让 GUI Study Compute 实际使用 sol2
model.sol('sol2').runAll;
```
**GUI 对等性补充**：`.study('stdN')`只记录求解器关联，不等同于把该求解器附着到 Desktop
里的 Study。每个自定义序列都要显式`.attach('stdN')`；这不仅适用于`sol2/std2`，也适用于
`sol1/std1`。若缺少附着，GUI或`model.study('stdN').run`可能自动生成`sol3`之类的新默认
Solver，原有数据集仍引用旧解，形成“计算成功但显示旧结果”。验收必须通过Study路径运行，
并断言运行前后`model.sol.tags()`没有新增求解器；需要阻止自动生成时可用`study.runNoGen`。

**排查方法**：怀疑粒子没有真正受力/运动时，直接对比同一坐标下 `es.normE` 在 `dset2`（CPT
study的解）和 `dset1`（纯静电场解）里的取值：
```matlab
mphinterp(model, 'es.normE', 'coord', coords, 'dataset', 'dset2')  % 应与dset1同量级
```
如果 `dset2` 上处处为0而`dset1`不为0，就是这个"未求解变量"配置问题。

时间步长估算：非相对论电子末速度 `v=sqrt(2*E_eV*1.602e-19/9.11e-31)`，除以渡越距离得到
量级，留30-50%余量。

### 2.5 求粒子末态动能：不要迷信 `cpt.Ep`，可能根本不存在
`cpt.Ep`/`Ek`/`KE`/`kin_en`/`Ekin`/`speed`/`U`，以及`comp1.qx`/`cpt.qx`/`cpt.vx`这类"看起
来应该对"的变量名在 `mpheval` 里全部报"Undefined variable"。

**稳健替代方案：用能量守恒代替去猜变量名**——如果粒子从阴极（V=0）附近以≈0eV初速释放，
它在任意后续位置的动能[eV] = 该位置的静电势V：
```matlab
pd = mphparticle(model, 'dataset', 'pdset1');
qx = pd.p(end,:,1).'; qy = pd.p(end,:,2).'; qz = pd.p(end,:,3).';
coords = [qx'; qy'; qz'];
KE_eV = mphinterp(model, 'V', 'coord', coords, 'dataset','dset1');
```
前提：粒子从V≈0处以≈0eV初速释放、纯静电场加速、无磁场/碰撞损耗。

### 2.6 取粒子坐标绝对不要用 mpheval，要用专用的 mphparticle
`mpheval(...,'dataset','dset2','edim',0)`（`dset2`=CPT study原始Solution数据集）**不会
报错，但取到的根本不是粒子位置**——安静退化成对底层FEM网格的0维几何顶点求值，坐标范围
正好等于真空域边界，且不随`t`变化。这曾直接导致误判"电子不运动"。

**正确写法**：
```matlab
pd = mphparticle(model, 'dataset', 'pdset1');   % pdset1 = Particle类型数据集(见2.9)
% pd.p, pd.v 都是 [nTimes x nParticles x 3] 的 double 数组（不是cell！）
% pd.t 是 1 x nTimes 的时间向量
z_all_particles_at_tk = pd.p(k, :, 3);        % 第k个时间步，所有粒子的z
z_of_particle_j_over_time = pd.p(:, j, 3);    % 第j个粒子，随时间变化的z
```
另外，`mpheval(...,'dataset','pdset1','edim',0)`（用对了数据集，但还留着`edim`参数）会
**卡死**（8分钟无响应，见`COMSOL_DEBUGGING.md`§卡死恢复）——`Particle`数据集不接受
`edim`，不要对它用`mpheval`，只用`mphparticle`。

### 2.7 mpheval/mphinterp 的两个隐蔽单位/维度坑
**坑A：坐标单位跟随模型的`geom.lengthUnit`，不一定是米。** 如果`geom1.lengthUnit('mm')`，
`mphinterp`的`coords`也必须用mm——用米传入不会报错，只会安静返回全0（坐标落在网格范围
外，插值默认给0，无异常提示）。

**坑B：`'outersolnum','end'`对"时间相关/粒子追踪"数据集不代表"最后一个时间步"。** 96个
粒子×301个时间输出点的CPT解用`'outersolnum','end'`取回28896个点（=所有粒子×所有时间步
混在一起），不是末态快照。**正确做法：显式指定具体时间值** `'t', tend`。

### 2.8 粒子轨迹图需要专门的 Particle 数据集
```matlab
% 错误：pg.set('data','dset2') -> "Operation cannot be performed on dataset dset2 (Solution)"
pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.set('solution', 'sol2');     % 属性名是solution，不是data！
pg3 = model.result.create('pg_traj','PlotGroup3D');
pg3.set('data', 'pdset1');
tr1 = pg3.create('traj1', 'ParticleTrajectories');
```

### 2.9 NaN 处理与统计陷阱
粒子中途被吸收后，`pd.p`/`pd.v`里后续时刻的值：有的场景冻结在最后有效坐标，有的场景
（大量粒子在第一个输出步之前就被吸收）直接是NaN，且从第一个记录点起就已经是NaN——不要
假设"被吸收=冻结在小z值"，两种表现都要处理，用`isnan(...)`单独统计。

**MATLAB陷阱**：`min`/`max`默认自动忽略NaN，但`mean`/`median`**不会**，数组里有一个NaN，
`mean`/`median`就返回NaN。统计前先用`isnan`过滤，或用`mean(x,'omitnan')`。

---

## 3. 会话/服务端/幂等性 相关运维事实

### 3.1 脚本可重复运行性（幂等性）：不要把中间产物存回自己读取的源文件
如果脚本一开始 `ModelUtil.load('Model', A.mph)`，跑完在末尾 `model.save(A.mph)`，下次再跑
会往一个已"被污染"的文件里重新创建同名节点，报"An object with the given name already
exists"。**约定：每个阶段脚本只从上一阶段产出、不会被本阶段覆盖的文件里读，本阶段新增
内容另存为新文件名，保证阶段脚本可以反复重跑。**

### 3.2 同一任务内的`ModelUtil`模型标签必须显式回收
标准入口不跨任务长期复用服务端，但同一任务内的多个阶段仍共享服务端内存。之前阶段创建的模型
标签会一直存在，直到显式`ModelUtil.remove(...)`。**每次载入模型前先检查并清理同名标签**：
```matlab
if any(strcmp(cell(ModelUtil.tags()), 'Model'))
    ModelUtil.remove('Model');
end
model = ModelUtil.load('Model', modelPath);
```
调试阶段容易积累一堆用完即弃的临时标签，建议定期批量清理：
```matlab
tags = cell(ModelUtil.tags());
for i=1:numel(tags), try, ModelUtil.remove(tags{i}); catch, end, end
```

---

## 4. GPU 求解器（cuDSS）实测结论

COMSOL 6.4 的 Direct 求解器特征暴露了 NVIDIA cuDSS GPU 直接求解器支持，属性名带`cudss`
前缀。启用方法：
```matlab
dDef.set('linsolver','cudss');
s1.feature('fc1').set('linsolver','dDef');   % 默认fc1.linsolver通常是'i1'(CPU迭代法)
```
**实测（几万自由度静电场模型，RTX 2060）：GPU 14.16s，反而比默认CPU迭代法(8.98s)慢
58%。** 小规模问题下GPU的上下文初始化/数据搬运开销超过并行收益。**GPU cuDSS只在自由度
规模远大于本例（经验百万级以上）时才可能有优势，小模型不要默认开GPU。**

同样的切换方法在时间相关(Transient)求解器上完全类比：
```matlab
t1 = model.sol('sol2').feature('t1');
t1.feature('dDef').set('linsolver','cudss');
t1.feature('fc1').set('linsolver','dDef');
```
**实测（碰撞池模型，32粒子×201时间步CPT）：CPU 0.982s，GPU 1.672s，GPU反而慢70%。**
物理结果完全一致（最大差异3.75e-12mm，纯浮点噪声），确认纯粹是性能层面的切换。

**后续oa-TOF项目的多次独立复测**（几万自由度静电场、以及CPT主直接求解器）**结论完全
一致**：CPU (pardiso) 稳定持平或快于 GPU (cudss)，本项目规模下不要默认开GPU。

---

## 5. 工程/物理层面的通用检查习惯

建好静电场之后、正式做粒子追踪之前，**先花一分钟沿粒子实际飞行路径算一遍电位分布**
（`mphinterp`在几个关键位置取V值），检查有没有电位"先降后升"形成的势垒——如果控制电极
负偏压相对目标能量偏大，会在发射点附近形成粒子翻不过去的势垒，届时粒子追踪会出现"大部分
粒子在发射点附近就被吸收"的结果。这个检查几乎不花时间，但能在正式跑粒子追踪（通常耗时
更长、调试成本更高）之前提前发现"参数设置在物理上是否自洽"的问题。

---

## 6. API / 函数 / 属性调用速查表（持续更新）

> **维护约定**：每次新发现一个可靠用法或一个无效/错误用法，都直接追加到下面对应的小节里
> （新增一行/一条即可）；确实找不到合适分类再新开一个小节，追加到末尾，编号只递增
> （旧编号`§7.x`保留作为本文件内部小节号延续，避免破坏其他文档里`见§7.x`的交叉引用）。
> 每条尽量只留"怎么写是对的"+一句话背景，详细项目过程见项目文档，通用排错见`COMSOL_DEBUGGING.md`。
> **新增一个完整的部件（几何+物理场组合、有验证脚本）时，除了新开小节写细节，还要在§7.0的
> 部件库表格里加一行**。

### 7.0 已验证质谱仪/粒子光学部件库速查表

> **用途**：新任务第一步先扫一眼这张表——如果要建的部件已经在这里，直接复用/改造对应
> 脚本，不要从零重新摸索。

| 部件 | 核心物理机制 | 关键验证结果 | 参考脚本 | 详见 |
|---|---|---|---|---|
| 电子枪（横置螺旋灯丝+Wehnelt） | 热发射(`Thermal`)+Wehnelt偏压聚焦 | 横置线圈收集效率34.18% > 轴向线圈27.71%；旧Wehnelt非单调扫描属于轴向谱系，横置参数待重扫 | `phase1_geometry_coil_transverse.m` / `phase2_electrostatics_coil_transverse.m` / `phase4_thermal_emission_coil_transverse.m` | `项目_螺旋灯丝Wehnelt电子枪.md` |
| 螺线管线圈 | `InductionCurrents`+`Coil`(Numeric) | 中心磁场/无限长理论值比值0.85 | `test_magnetic_coil.m` | §7.14, §8 |
| 均匀磁场回旋运动(裸测试) | 均匀Bz+`MagneticForce` | 回旋半径0.58mm vs理论0.57mm(2%误差)，轨迹为正圆 | `test_cpt_magnetic_force.m` | §7.15, §8.5 |
| 四极/六极/八极杆 | RF交替电位；仅四极有严格马蒂厄稳定性 | on-axis电位幂律`r^(N/2)`吻合4位有效数字；四极q=0.5稳定/q=1.2发散；六极/八极是"离子导管"而非质量滤波器 | `test_multipole_geometry.m` / `test_multipole_es.m` / `test_quadrupole_stability.m` | §7.16 |
| 爱因茨尔透镜(Einzel Lens) | 静电透镜聚焦 | 聚焦强度只取决于`KE_beam/|V_lens|`比值(标度律) | `test_einzel_lens.m` / `test_einzel_cpt.m` | §7.17 |
| 线性离子阱(LIT) | RF四极径向约束+DC端盖轴向约束 | 轴向束缚呈平滑抛物线往返运动，全程未接近电极 | `test_lit_geometry_es.m` / `test_lit_cpt.m` | §7.18 |
| TOF飞行时间分析器+反射器(基础版) | 加速→漂移→反射镜减速反弹 | `t∝sqrt(m)`吻合(误差0.5%)；漂移管必须接地侧壁 | 已被oa-TOF环栈反射镜取代 | §7.19 |
| ESA静电扇形场能量分析器 | 同轴柱形电容器径向场`E=V0/(r·ln(R2/R1))` | FEM与解析解吻合4位有效数字 | `test_esa.m` | §7.20 |
| 磁扇形场质谱仪 | 均匀B场回旋运动，固定KE下按质量分离 | `r∝sqrt(mass)`吻合5位有效数字 | `test_magnetic_sector.m` | §7.21 |
| 碰撞池/CID(背景气体碰撞) | `Collisions`+`Elastic`子特征(必须加子特征才生效) | 损失率随`Nd`单调变化 | `test_collision_cell.m` | §7.22 |
| 共振电荷交换碰撞 | `Collisions`+`ResonantChargeExchange`子特征 | 25%粒子出现单步>90%速度骤降 | `test_resonant_charge_exchange.m` | §7.25 |
| Wien滤波器(交叉E×B) | `v=E/B`只筛速度、与质量电荷无关 | 共振速度偏转≈0；质量无关性验证 | `test_wien_filter.m` | §7.23 |
| 空间电荷/库仑排斥 | `ParticleParticleInteraction`(`InteractionForce='Coulomb'`) | 有vs无相互作用，径向扩散标准差相差33倍 | `test_space_charge.m` | §7.24 |
| FTICR/ICR离子回旋共振池 | 均匀B场回旋+DC端盖组合捕集 | 出现真实磁控漂移(magnetron drift)现象 | `test_icr_cell.m` | §7.26 |
| 简单质谱仪整机(EI源→引出→多极杆→TOF→反射器→检测器) | 电子撞击电离+引出加速+RF多极杆+TOF | 电离产率与理论吻合 | `ms_stage1_ei_source.m` | §7.27 |
| oa-TOF双级环栈反射镜分析器（正交加速+双级Mamyrin反射镜） | 见项目文件 | 见项目文件 | `ms_oaTOF_two_stage_ringstack_reflectron.m` | `projects/oa_tof/docs/PROJECT.md` |

### 7内容分类索引
- **环境/会话管理**：§7.1, §7.13
- **几何/材料/网格/静态求解通用套路**：§7.2, §7.3, §7.4, §7.5, §7.6
- **CPT粒子追踪核心机制**：§7.7, §7.8, §7.9, §7.10
- **磁场物理场**：§7.14（`InductionCurrents`/`Coil`特征，完整调试叙事见§8）
- **CPT里的力/碰撞/多体效应**：§7.15, §7.22, §7.24, §7.25
- **GPU求解器**：§7.11（结论：本项目规模下比CPU慢，不要默认开）
- **已验证的部件（几何+物理组合实例，对应§7.0表格）**：§7.16-§7.27
- **理想细网格栅网(内部边界技术) + Release分布/随机化API**：§7.29
- **黑名单**：§7.12（已确认无效的调用，不要重试）

### 7.1 会话 / 模型管理
| 调用 | 说明 |
|---|---|
| `mphstart(2036)` | 仅供人工诊断手动启动的服务端；标准任务脚本禁止调用，连接由`run_comsol_r2025b.ps1`建立。 |
| `ModelUtil.create('Model')` | 新建空模型，tag='Model'。 |
| `ModelUtil.load('Model', path)` | 从.mph文件加载模型到tag='Model'。 |
| `ModelUtil.remove('Model')` | 删除服务端内存里的模型tag。载入前先检查并清理同名tag（见§3.2）。 |
| `cell(ModelUtil.tags())` | 列出服务端当前所有模型tag。 |
| `model.save(path)` | 保存为.mph。注意幂等性（见§3.1）。 |
| `model.label('xxx')` | 给模型设标签。 |

### 7.2 几何建模
| 调用 | 说明 |
|---|---|
| `comp1 = model.component.create('comp1', true)` | 2参数(tag, boolean)，无维度参数。 |
| `geom1 = comp1.geom.create('geom1', 3)` | 维度在这里指定。 |
| `geom1.lengthUnit('mm')` | 影响后续坐标单位。 |
| `geom1.feature.create(tag,'Cylinder')` + `.set('r',...)/.set('h',...)/.set('pos',{'x','y','z'})/.set('axis',[0 0 1])` | 圆柱体图元。 |
| `geom1.feature.create(tag,'Cone')` + `.set('r',...)/.set('specifytop','radius')/.set('rtop',...)/.set('h',...)/.set('pos',...)` | 圆锥台图元（见§1.2）。 |
| `geom1.feature.create(tag,'Difference')` + `.selection('input').set({...})` + `.selection('input2').set({...})` | 布尔差；`input`=被减，`input2`=减去的。 |
| **Fillet / Chamfer** | 许可证不支持，改用Cone−Cylinder手工倒角（见§1.2）。 |
| `geom1.feature(tag).set('selresult','on')` | 开启自动域选择，之后用`geom1_<tag>_dom`引用。**警告**：如果该图元与其他图元大范围空间重叠（如包住所有电极的外层"真空域"圆柱体），生成的选择可能不"纯净"（解析出全部域）。**正确修复**：不要用外层大圆柱的selresult当真空域，改用`comp1.selection.create('sel_vac','Complement')`+`.set('input',{电极域1,电极域2,...})`对"真正独立不重叠"的电极域取补集。用之前先`entities()`打印检查实际解析到的域编号。 |
| `geom1.run` | 构建几何。 |
| `mphgeominfo(model,'geom1')` | 返回`Ndomains/Nboundaries/Nedges/Nvertices`（见§1.3）。 |
| `geom1.feature.create(tag,'Helix')` + `.set('rmaj',...)/.set('rmin',...)/.set('axialpitch',...)/.set('turns',...)/.set('pos',{'0' '0' 'z0'})` | 原生螺旋线圈实体图元，不需要额外Sweep。`type`默认`'solid'`，`rmaj`=线圈半径，`rmin`=线材截面半径，`axialpitch`=每匝轴向间距，`turns`=匝数。 |
| `hel1.set('axistype','x')`（或`'y'`/`'z'`/`'cartesian'`/`'spherical'`） | 螺旋轴朝向；默认`'z'`。改成`'x'`后`pos`是螺旋沿x轴的起点。 |
| `mphgeom(model,'geom1', 'facealpha',0.5)` + MATLAB `print(fig,'file.png','-dpng')` | 验证复杂几何最可靠的可视化方式：MATLAB自己的图形引擎（`figure('Visible','off')`），完全不经过comsolmphserver图形导出管线，不受渲染卡死风险影响。 |
| **同一个部件尽量一次布尔运算成型，不要拼多个独立特征** | 一个大外形减一个小外形（`Difference`）做出"侧壁+端盖"这类一体结构，比"侧壁特征+端盖特征"分开搭建更好：后者两个特征的z范围/半径容易在边界处产生真实几何重叠或缝隙（例如曾经的`endcap`+`flighttubewall`各自独立时，两者在同一半径段有重叠的z范围），前者从构造上就不可能重叠。副作用：COMSOL里选中一个部件只需点一个特征，代码更短，三维图里辨认这个部件也更直接。 |
| **不同图元类型的`pos`锚点约定不同，混用时会产生系统性偏移** | `Block`的`pos`是角点；`Cylinder`/`Cone`的`pos`是**底面**中心，不是几何中心（几何中心在`pos.z+h/2`）。如果某个电压表达式是按"几何中心"的z值算出来的，建几何时却直接把`pos.z`设成那个z值，会产生固定`h/2`的系统性错位。**每次新建部件前，先确认这个图元类型的锚点约定和自己后续公式的假设是否一致**，加厚某个部件的厚度参数时尤其要重新检查这个偏移量是否需要同步更新（如`pos.z`里的`-thickness/2`修正项）。 |

### 7.3 选择集 (Selection)
| 调用 | 说明 |
|---|---|
| `comp1.selection.create(tag,'Adjacent')` + `.set('input',{'geom1_xxx_dom'})` | 组件级"相邻边界"选择，从域选择拿到该域的边界面。 |
| `feature.selection.named('tag')` | 材料/物理场特征引用命名选择的标准写法。 |
| `sel.entities()` | 返回该选择实际解析到的实体编号数组，排查选择是否解析对了的关键手段，不要只看名字。**任何"应该恰好是一个面"的选择集，建完立刻打印`numel(entities())`跟预期值比对**，不要等到结果异常才回头查——本项目多次靠这一步在几秒内定位选择框跟相邻边界意外重叠的问题。 |
| **⚠️陷阱：基于绝对坐标的`Box`选择集不会跟着几何体移动自动更新** | 如果部件位置由参数表达式定义，Box边界也必须写成同一参数的表达式，例如`.set('xmin','x_center-half_width')`/`.set('xmax','x_center+half_width')`；更优先使用几何派生的`Adjacent`/`Complement`/`geom1_<feature>_dom`。几何完成后必须用`entities(dim)`断言域/边界数量。oa-TOF曾把加速器移到`x=-48.8mm`却保留`x=[-50,50]mm`网格Box，静默从6域退化为1域；参数联动和域数断言可在迁移当场拦截。 |

### 7.4 材料
| 调用 | 说明 |
|---|---|
| `model.material.create(tag,'Common')` + `.selection.named(...)` + `.propertyGroup('def').set('relpermittivity',{'1'})` | 标准写法（见§1.5）。 |

### 7.5 静电场 (Electrostatics)
| 调用 | 说明 |
|---|---|
| `es = comp1.physics.create('es','Electrostatics','geom1')` + `.selection.named(sel_vac)` | 限定物理场作用域。 |
| `es.create('pot1','ElectricPotential', 2)` + `.selection.named(...)` + `.set('V0', 'V_expr_or_param')` | 电位边界条件，2=边界级别。 |

### 7.6 网格 / 稳态求解
| 调用 | 说明 |
|---|---|
| `mesh1 = comp1.mesh.create('mesh1')` + `.feature('size').set('hauto', N)` + `.run` | N: 1=最细...9=最粗，"Finer"≈3。**警告**：不保证真的生成域网格！见下面FreeTet那一行。 |
| `mesh1.feature.create('sz1','Size')` + `.selection.geom('geom1',2)` + `.selection.named(边界选择)` + `.set('custom','on')` + `.set('hmaxactive',true)` + `.set('hmax',...)` | 对特定边界显式指定局部网格尺寸。 |
| **`mesh1.feature.create('ftet1','FreeTet')`（域填充网格特征）** | **【高优先级坑】必须显式加**，不要假设`mesh.create()+size+run()`会自动补域填充网格！否则可能静默生成空网格，`mesh1.run()`不报错，后续求解也"成功"跑完但结果毫无意义（域级`mpheval`查询返回0个点，`mphinterp`对任意坐标都报"Cannot evaluate expression"）。**这是判断"网格其实是空的"的关键信号**：连远离精细几何的普通坐标点插值都失败，先怀疑网格没建好。 |
| `meshinfo = mphmeshstats(model,'mesh1')` + 检查 `meshinfo.isempty`/`.hasproblems`/`.iscomplete` | 网格建完后必须显式检查这三个字段再往下走，不要只看`mesh1.run`有没有抛异常。 |
| `model.study.create('std1')` + `.create('stat1','Stationary')` | 稳态study。 |
| `model.sol.create('sol1')` + `.study('std1')` + `.createAutoSequence('std1')` + `.attach('std1')` + `.runAll` | 标准求解五步；自定义序列必须附着到Study，保证GUI Compute不另生求解器。 |

### 7.7 带电粒子追踪 (CPT) 物理场
| 调用 | 说明 |
|---|---|
| `cpt = comp1.physics.create('cpt','ChargedParticleTracing','geom1')` | 自动带`wall1`(默认Freeze)、`pp1`(默认电子)、`dpcon1`（见§2.1）。 |
| `cpt.create('inl1','Inlet', 2)` + `.selection.named(...)` + `.set('N',1)` | 从边界发射粒子；默认`v0=0`、方向=边界法向。**不是**`Release`/`ReleaseFromBoundary`。 |
| `inl1.set('VelocitySpecification','Thermal')` + `.set('T_src','userdef')` + `.set('T','2700[K]')` | 内置热发射（Maxwell-Boltzmann通量加权分布）release模式。合法取值：`VelocitySpecification`∈`"SpecifyVelocity"`(默认)/`"SpecifyMomentum"`/`"SpecifyKineticEnergy"`/`"Thermal"`；`InitialVelocity`(另一个属性)∈`"Expression"`/`"ConstantSpeedHemisphere"`/`"ConstantSpeedCone"`/`"ConstantSpeedLambertian"`。`T`默认`293.15[K]`。 |
| `cpt.create('ef1','ElectricForce', 3)` + `.selection.named(sel_vac)` + `.set('E_src','root.comp1.es.Ex')` | 把es物理场的电场耦合进粒子受力（见§2.3）。**不是**`model.multiphysics.create(...)`。 |

### 7.8 时间相关粒子追踪 Study（含"复用已存 ES 场"的关键设置）
| 调用 | 说明 |
|---|---|
| `std2.create('time1','Transient')` + `.set('tlist','range(0,dt,tmax)')` + `.setEntry('activate','es',false)` + `.setEntry('activate','cpt',true)` | 只重新求解cpt，跳过重解es。 |
| `model.sol('sol2').feature('v1').set('notsolmethod','sol')` + `.set('notsol','sol1')` | 必须显式加这两行，否则粒子受力为0（见§2.4）。属性名是`notsol`，**不是**`notsolnum`。 |
| 排查手段 | `mphinterp(model,'es.normE','coord',coords,'dataset','dset2')`对比`'dataset','dset1'`，处处为0说明踩了这个坑。 |

### 7.9 结果绘图 / 导出
| 调用 | 说明 |
|---|---|
| `pg = model.result.create(tag,'PlotGroup3D')` | 三维绘图组。 |
| `pg.create('slice1','Slice')` + `.set('quickplane','xy'/'yz'/'zx')` + `.set('quickznumber','1')` + `.set('expr','V'/'es.normE')` | 切面图。 |
| `pdset1 = model.result.dataset.create('pdset1','Particle')` + `.set('solution','sol2')` | 粒子轨迹图必须用专门的Particle数据集，属性名是`solution`不是`data`（见§2.8）。 |
| `pg3.create('traj1','ParticleTrajectories')` | 轨迹图层，`data`指向`pdset1`。 |
| `model.result.export.create(tag,'Image')` + `.set('plotgroup',...)` + `.set('pngfilename',...)` + `.run` | 图片导出。**批处理模式下`ParticleTrajectories`导出有已知稳定性风险，见`COMSOL_DEBUGGING.md`**；普通Slice/Surface图没有这个问题。 |
| `.label('自定义字符串')` | 几乎所有Java API对象（geometry feature、selection、material、physics接口及子特征、mesh、study、solver、result dataset、plot group）都支持，跟tag完全独立，且会持久化进.mph文件。**应该在写`create(tag,type)`之后顺手加一行，成本几乎为零**——否则COMSOL Desktop的Model Builder树里全是"Cylinder 1"这类无信息量的默认名。 |
| `pg1.set('titletype','manual')` + `pg1.set('title', '<自定义字符串>')` | 原生COMSOL结果图默认标题是"Particle trajectories"这种通用文本，必须显式设`titletype='manual'`才能覆盖成有信息量的标题（`titletype`合法值`auto`(默认)/`manual`）。MATLAB端`title`/`sgtitle`支持cell数组传入实现多行标题，如`title({'第一行','第二行'})`。 |

> **画图的"应该长什么样"规范（标题必须含哪些信息、颜色约定等）不在这里**——那是为了
> 防止review结果时被小样本噪声/图与图之间颜色语义不一致误导，属于调试严谨性问题，见
> `COMSOL_DEBUGGING.md`。这里只收录"怎么调用API让标题长成想要的样子"这类机械调用事实。

### 7.10 数值提取函数：mpheval / mphinterp / mphparticle 该怎么选
| 需求 | 用哪个 | 关键点 |
|---|---|---|
| 任意坐标处插值某个场量 | `mphinterp(model, 'expr', 'coord', coords, 'dataset', tag)` | 坐标单位=`geom.lengthUnit`（见§2.7坑A）；粒子study的`dataset`要配合`'t', t值`才能拿到某一时刻切片，`'outersolnum','end'`不代表最后一步（见§2.7坑B）。 |
| 取粒子在某时刻的坐标/其他量 | ~~`mpheval(...,'dataset','dset2','edim',0)`~~不要用（见§2.6） | 正确：`mphparticle(model,'dataset','pdset1')`。 |
| 取粒子末态动能 | 能量守恒法（见§2.5） | 前提：粒子从V≈0处以≈0eV初速释放、纯静电场加速。 |
| ~~`cpt.Ep`/`Ek`/`KE`/`kin_en`/`Ekin`/`speed`/`U`/`qx`/`vx`~~ | 不存在，不要试 | 用能量守恒法代替。 |
| 对`Particle`类型数据集用`mpheval`并传`'edim'`参数 | 不要用，会卡死 | 用`mphparticle`，不要传`edim`。 |
| 碰撞计数变量(`cpt.coll1.elastic1.Nc`等) | `mphparticle(model,'dataset','pdset1','expr',{'cpt.coll1.elastic1.Nc'})` | `mphinterp`完全不支持粒子数据集；`mpheval`报"Undefined variable"即使表达式正确。返回结构体多出`d1`字段（`[nTimes x nParticles]`）。`Nc`在粒子被吸收后保持不变（冻结值），不是持续累加到`t_end`。 |
| `mphparticle`的`'expr'`选项是否能减少传输数据量 | **不能**，实测即使只请求`{'qz'}`，`pd.p`依然是`[ntime x nP x 3]` | 真正有效的内存控制手段只有减少N或减少存储的时间步数。 |

### 7.11 GPU 求解器 (cuDSS)
见本文件§4。

### 7.30 官方PDF文档研究成果（COMSOL 6.4 Programming Reference Manual / Particle Tracing
Module Users Guide / LiveLink for MATLAB Users Guide，本地`official_docs/*.pdf`）

> 以下条目来自官方PDF文本（用`pymupdf`提取全文后按关键词定位，而不是逐页通读——PDF
> 有300~1200页/份，直接读不现实），**未在活体COMSOL上重新实测**，标注来源页码供以后
> 需要时核对。跟本文件其他小节（都是活体实测）的可信度定位不同，引用前如果有实际影响
> （比如要接入生产脚本），建议先用`tmp_*.m`一次性脚本核实一遍。

**A. `tout`属性解释了"Fix B"疑案（tlist收窄为何在`tstepsbdf='free'`下仍拖累精度）**
（Programming Reference Manual §6, "Solvers and Study Steps"原文）：
- `tstepsbdf`（`free`/`intermediate`/`strict`/`manual`，默认`free`）控制的是**求解器内部
  自己怎么选步长**："If set to free, the solver selects the time steps according to its
  own logic, disregarding the intermediate times in the tlist vector."——这跟本项目已经
  确认的认知一致。
- 但**真正决定"输出/存储哪些时刻的解"的是另一个独立属性`tout`**（默认值就是`tlist`！）：
  "If tout=tlist, then the output contains **interpolated solutions** for the times in
  the tlist property." 也就是说：即使内部积分步长已经是free、完全不受tlist稀疏影响，
  **只要`tout`还是默认的`tlist`，最终存下来给你读的解仍然只在tlist那些点上（插值得到），
  跟tlist的疏密直接挂钩**。
- 若想要"内部自由步进 + 输出也用求解器真实步长（不再被tlist插值精度卡住）"，需要显式
  设置：`model.sol('sol2').feature('t1').set('tout','tsteps')`（`tsteps`=每N个求解器
  真实步存一次，N由`tstepsstore`控制，默认1=每步都存；还有`tstepsclosest`=存离tlist
  请求时刻最近的真实步）。这是APG/参考手册里给出的官方例句：
  `model.sol("sol1").feature("t1").set("tout", "tsteps");`
- **推论（尚未在本项目重新实测，仅是文档层面的解释假说）**：上次"Fix B把tlist收窄导致
  分辨率R下降"的现象，很可能不是"缩短tlist真的让内部计算变粗"，而是**tlist收窄直接
  降低了输出解的插值密度，从而降低了下游探测时间(detTime)的插值精度**——因为
  `tstepsbdf=free`只保证内部积分本身准，不保证输出跟着一样密。换句话说，**当初"缩短
  tlist来提速"这个思路本身可能就没有实际提速效果**（内部步进本来就已经是free/自适应，
  不受tlist疏密支配），代价却是白白牺牲了输出精度。如果以后要重新对这个方向下手，
  正确做法应该是保持`tout='tlist'`不变但**不收窄tlist**（收窄tlist对求解速度没什么
  帮助），或者改成`tout='tsteps'`来获取真实自适应步长的输出，两者都不需要以牺牲精度
  为代价。

**B. Nonlocal Coupling（`model.cpl`/`Maximum`/`Average`/`Integration`）的正确创建路径**
（Programming Reference Manual §2, "About General Commands"原文语法块）：
- 正确语法是`model.component(<ctag>).cpl().create(<tag>,type)`——**必须挂在具体的
  component下面**（如`model.component('comp1').cpl.create(...)`），**不是**
  `model.cpl.create(...)`（模型根节点下没有这个東西的正确落点）。上次调试
  `Maximum` component coupling一直卡住（`cop1.set('expr',...)`报"Unknown property"，
  `maxop1(expr)`调用报"不能超过0个参数"），根源大概率就是当时代码写的是
  `model.cpl.create('maxop1','Maximum','geom1')`——**挂错了节点**，不是属性名猜错。
- 官方标准用法确认：**创建对了之后，聚合表达式是作为调用参数传的，不是属性**：
  `oper(e)`（如`maxop1(cpt.vx^2+cpt.vy^2+cpt.vz^2)`），这跟直觉一致，只是必须先在
  正确的`component.cpl()`节点下创建。
- 支持的`type`：`GeneralExtrusion`/`LinearExtrusion`/`BoundarySimilarity`/
  `IdentityMapping`/`GeneralProjection`/`Integration`/`Average`/`Maximum`/`Minimum`。
- **如果以后要重新捡起"用Maximum聚合cpt速度做自动停止条件"这个思路**：先只改这一处
  （`model.cpl`→`model.component('comp1').cpl`），用`tmp_*.m`重新验证一遍，大概率能
  直接解决之前的卡点。

**C. `Particle Counter`官方暴露的全局变量（正是当初找不到的"全部粒子已到达/停止"信号）**
（Particle Tracing Module Users Guide §2, "Particle Counters"原文）：
一个`ParticleCounter`（`cpt.create('pc1','ParticleCounter',<dim>)`）特征，tag设为`<tag>`
时提供以下**官方文档明确列出**的变量（当初逐个猜的`cpt.status`/`cpt.freeze`/`cpt.dead`
等全部是瞎猜，官方正确名字是这些）：
- `<tag>.Nsel`——**到达该counter的粒子数（累计传输数）**。这正是当初想找的"多少粒子已
  经到达/停止"的信号，可以用`pc1.Nsel>=N_total`作为"全部粒子已到达"的判据。
- `<tag>.Nfin`——仅Particle Beam释放特征场景下，末时刻传输的粒子数。
- `<tag>.alpha`——传输概率（`Nsel`/释放总数）。
- `<tag>.rL`——一个逻辑表达式，标记"这个粒子是否属于从某release到这个counter的路径"，
  设计用来喂给Particle Trajectories绘图的Filter节点。
- `<tag>.It`（仅CPT接口且释放方式为Specify current时）——传输到counter的电流。
- 文档特别提示：**Particle Counter只创建变量，不影响求解**，加了之后不需要重新solve，
  在Study节点右键"Update Solution"更新一下变量即可读取——如果以后真的要用，这是个
  比重新跑整个CPT快得多的验证捷径。
- **已实测证伪**：`Nsel`**不能**被`StopCondition`的表达式引用——直接报"Undefined
  variable"。原因是"Particle Counter只创建变量，不影响求解"这句话的准确含义是"它是
  从已经存好的完整轨迹历史事后算出来的，不是求解过程中每一步实时可读的活变量"，
  `StopCondition`每步都要实时求值，天生用不了这类事后变量。
- **进一步实测（另两轮会话）**：理论上的实时替代——`Wall`节点下的`BoundaryAccumulator`
  子特征（`wall_det.create('bacc1','BoundaryAccumulator')`，这是官方文档里"每次粒子
  撞边界就递增"的真ODE自由度）——特征创建和属性设置（`AccumulatorType='Count'`+
  `R='1'`+`StudyStep`）全部正常。第一次读取尝试用裸`rpb`（`cpt.wall_det.bacc1.rpb`）
  全部失败，一度误判为"PDF没记录这条路"——**这个判断后来被证明是错的**：
  `ParticleTracingModuleUsersGuide.pdf`第146页**确实有一张"BUILT-IN GLOBAL
  VARIABLES"表格**（Table 3-4/3-5），只是表格内容本身在`pymupdf`文本提取时被打散成
  乱码（原因是COMSOL PDF把这类表格用特殊排版渲染，纯文本抽取抽不出来），第一轮
  用纯文本Grep检索时因此完全没发现，**这是本次调研方法本身的一个漏洞：文本抽取遇到
  明显乱码/公式碎片时，应该把那一页额外渲染成图片直接读，而不是当作"没有记录"直接
  放弃**。渲染成图后确认：裸`rpb`是**逐边界网格单元、不连续的field变量**（本来就不该
  指望它能被当标量读出来），真正对应的是自动生成的**全局标量**变量，命名规则是
  `<scope>.<name>_sum`（"Sum of accumulated variable over elements"，正是我们要的
  "总撞击数"）——示例`pt.wall1.bacc1.rpb_ave`，其中`_sum`/`_ave`/`_int`/`_max`/`_min`
  是COMSOL自动通过一组"非局部耦合(nonlocal coupling)"生成的现成聚合量，理论上不需要
  自己手工建`Integration`算子。CPT章节（Chapter 4）明确交叉引用了这同一套理论
  （"Specialized Boundary Accumulators"一节直接说"variables...are described in detail
  in Accumulator Theory: Boundaries in Theory for the Mathematical Particle Tracing
  Interface"），确认这套机制对`cpt`接口同样适用，不是"pt"专属。**但即使用文档给的
  精确写法`cpt.wall_det.bacc_det.rpb_sum`在生产物理模型上实测，依然报"Undefined
  variable"（COMSOL自己在"Global scope"这一级都确认找不到这个符号，不是选择集/读取
  方式的问题）**——说明PDF记录的理论机制是真实存在的，但要么触发这些自动生成的
  非局部耦合还需要某个本次没试出来的额外步骤/设置，要么装的COMSOL 6.4版本在这个
  细节上跟PDF描述的版本（封面标注6.3）有出入。**当前判定**：不是"文档没记录"，而是
  "文档记录的机制真实存在但实测复现不了，原因超出了这5份PDF能回答的范围"——下次要
  继续查，优先级应该是先确认COMSOL 6.4桌面版GUI里手动加一个这样的Accumulator后，
  右键Results能不能在Add/Replace Expression菜单里真的看到`rpb_sum`这个建议项（如果
  GUI里都找不到，说明确实是版本行为差异；如果GUI里有但脚本读不到，说明是脚本调用
  方式的问题）。`mphgetexpressions`试过，帮不上忙，它只覆盖`model.param`/
  `model.variable`这类用户自定义节点，不覆盖物理场内部编译的DOF/耦合变量。
  详见oa-TOF历史文档中原§6.13记录；当前结论以`projects/oa_tof/docs/PROJECT.md`为准。

**D. `StopCondition`的官方"多条件"标准写法**
（Programming Reference Manual §6, "StopCondition"原文语法块）：
- 官方给的标准语法是先创建，再用`setIndex`按下标设置每一条：
  ```matlab
  model.sol(sname).feature(fname).feature(pname).create(ocname,"StopCondition");
  model.sol("sol1").feature("t1").feature("st1").setIndex("stopcondarr", "(1/timestep)<200", 1);
  ```
  即真正的官方推荐属性名是**`stopcondarr`**（字符串数组，逐条设置用`setIndex`+下标），
  不一定是直接`.set('stopcond',...)`（后者若能用，大概率是内部/兼容层的简化别名，不是
  文档推荐写法）。另外文档提到一个已废弃的旧属性`stopcondition`（单个字符串，deprecated），
  不要跟`stopcondarr`搞混。
- `stopcondterminateon`：`"true"`表示对应`stopcondarr`条目求值**≥0**时停（不是"变为负数"，
  是"变为非负"！），`"negative"`表示条目求值**<0**时停。要用`t-2[us]`（表达式本身在
  越过2us时刻变为非负）而不是`t>2[us]`（返回布尔0/1，虽然实测中0/1恰好也能落在"非负
  即停"的判定里凑巧工作，但不是文档描述的本意用法，语义上更规范的写法是前者）。

### 7.12 已确认无效/错误的调用（黑名单，不要重试）
- `model.multiphysics.create('epf1','ElectricForce', ...)` → "Unknown multiphysics coupling"（正确见§7.7）。
- `geom1.getNEdge(tag)` → 方法不存在（正确见§7.2 `mphgeominfo`）。
- `geom1.feature.create('fil1','Fillet')` / `'Chamfer'` → 许可证限制（正确见§7.2 Cone−Cylinder手工倒角）。
- `cpt.Ep`/`Ek`/`KE`/`kin_en`/`Ekin`/`speed`/`U`、`comp1.qx`/`cpt.qx` → "Undefined variable"（正确见§7.10能量守恒法）。**勘误**：`cpt.vx`/`cpt.vy`/`cpt.vz`（带`cpt.`前缀）实测通过
  `mphparticle(model,'dataset','pdset1','expr',{'cpt.vx'})`**可以**查到值，跟本条目之前的说法相反；失效的是不带前缀的裸`vx`/`vy`/`vz`。`cpt.`前缀对不同变量名的有效性没有统一规律（`qx`反过来是裸的才有效、带`cpt.`前缀反而失效），每个变量都要单独试，不能类推。
- `mpheval(...,'dataset','dset2','edim',0)`取粒子坐标 → 不报错但语义错误，返回FEM网格顶点数据（正确见§7.10 `mphparticle`）。
- `mpheval(...,'dataset','pdset1','edim',0)` → 卡死（正确见§7.10 `mphparticle`，不要传`edim`）。
- `model.sol('sol2').feature('v1').set('notsolnum', 'sol1')` → 报错（正确属性名见§7.8 `notsol`）。
- `v1.set('notstudy'/'notsollist'/'notsolstudy'/'notsolstudystep', ...)` → "Unknown property"（正确见§7.8 `notsol`+`notsolmethod`）。
- `'outersolnum','end'`用于取时间相关/粒子数据集的"最后一步" → 实际取回所有时间步×所有粒子（正确见§7.10显式传`'t',tend`）。
- `comsolmphserver.exe ... -3drend sw -graphics`（长期运行的共享服务端上使用） → 有实测记录会在后续操作异步崩溃，不推荐。
- `mesh1 = comp1.mesh.create('mesh1'); mesh1.feature('size').set('hauto',N); mesh1.run;`（不显式加`FreeTet`） → 在简单几何上能用，换到更复杂几何上会静默生成空网格（正确见§7.6 `FreeTet`+`mphmeshstats`检查）。
- `comp1.physics.create('mf','MagneticFields',...)` → "Unknown physics interface"（正确tag见§7.14 `InductionCurrents`）。
- `std1.create('cga1','CoilGeometryAnalysis')` → "Operation cannot be created in this context"（正确见§7.14 `CoilCurrentCalculation`）。
- `mphinterp(model,'es_rf.Ex',...)` / `'es_dc.normE'`（自定义物理场tag直接当变量名用） → "Undefined variable"（正确见§7.18变量命名空间说明）。
- `comp1.selection.create(tag,'Union')` / `'Difference'` + `.set('input2',{...})`（组件级别选择组合运算） → 未验证可靠，正确做法见§7.19（`Adjacent`取全部实体ID + MATLAB `setdiff` + `Explicit`选择类型）。
- `p.set('h','10[mm]')`（用`h`作为自定义模型参数名） → "Duplicate parameter/variable name"（`h`是COMSOL保留全局变量名，换成`h_cyl`等）。
- `inl1.set('v0','5[m/s]')`（`Inlet`的`v0`给标量表达式） → "A vector of length 3 expected"（正确见§7.19 `{'0','0','v'}`）。
- 回旋运动类CPT测试，`MeshBased`域内撒点后随手挑一个粒子分析、且圆轨道直径接近或超过域尺寸 → 测得半径可能精确是理论值的整数分之一，是轨道被边界截断，不是物理误差（正确排查见§7.21）。
- `std1.create('sss1','StationarySourceSweep')`用于单线圈 → 求解时报"No sources found."（这是给多线圈互感扫描用的，见§7.14）。
- `cpt.create('lf1','LorentzForce',...)` → 不存在，正确名字是`'MagneticForce'`（见§7.15）。
- `rel1.set('InitialPosition', 'Manual')` 或 `cpt.create('rel1','Release',0)`（点级别） → 前者"Invalid parameter value"（合法值只有MeshBased/Density/RandomPosition），后者"Cannot create feature in the specified element dimension"（`Release`只能在edim=3创建，见§7.15）。
- `ppi1.set('InteractionType'/'ForceType'/'Interaction', ...)` → "Unknown parameter"，正确属性名是`InteractionForce`（见§7.15）。
- `MagneticForce`/`ElectricForce`等力特征忘记`.selection` → 不报错，静默让力处处为零，容易被误判成"物理是对的"（见§7.15/§8.5）。
- 同一component里创建第二个同类型物理场时用自定义tag引用变量（如`'es_rf.Ex'`） → "Undefined variable"，COMSOL变量命名空间不跟着自定义tag走，按类型自动编号`es`/`es2`（见§7.18）。
- 为避免理想化边界跟不同电压实体接触，随手设一个"看起来很小"的间隙（如0.1mm）而不参照局部网格尺寸 → `FreeTet`报"Failed to constrain a mesh vertex to its geometric entity"，网格生成直接失败（正确做法见§7.29，间隙量级要跟`hmax`相当）。

### 7.13 服务端启动命令
```powershell
& "D:\COMSOL 6.4\COMSOL64\Multiphysics\bin\win64\comsolmphserver.exe" -port 2036 -multi on -silent
```
默认`-3drend ogl`（不加软件渲染参数）是目前证据下更稳的选择。

### 7.14 磁场物理场 (Magnetic Fields) 与 Coil 特征
| 调用 | 说明 |
|---|---|
| `comp1.physics.create('mf','InductionCurrents','geom1')` | "Magnetic Fields"物理场接口的内部tag是`InductionCurrents`，不是`MagneticFields`。属于AC/DC Module，即使`model_inspect`的`modules`列表没显式列出"AC/DC"也可能可用——不要仅凭modules列表断定不可用，直接试一次更可靠。默认自带`fsp1`/`mi1`/`init1`。 |
| `mf.create('coil1','Coil', 3)` + `.selection.named(域选择)` | 在任意三维实体域上定义"这是一个载流导体"。`CoilType`默认`'Numeric'`（合法值：`"Numeric"/"Circular"/"Linear"/"UserDefined"`），任意真实3D形状用Numeric。`CoilExcitation`合法值`"Voltage"/"Current"/"CircuitVoltage"/"CircuitCurrent"`。`N`(匝数倍率)如果线圈真实绕线已经在几何里画出来，设成`'1'`，不要用默认的`'10'`（默认给"匀质化"简化线圈用）。 |
| `coil1.feature('ccc1').feature('ct1').selection.set(边界编号)` | Numeric类型的Coil会自动带`cg1`/`ccc1`(内含`ct1`)/`cre1`。`ct1`必须显式指定一个边界选择，否则报"No selection specified for the Input subfeature"。 |
| Coil所在域必须有材料的`electricconductivity`(sigma) | 否则报"Undefined material property 'sigma'"。给线圈材料一个真实电导率，周围"空气"域给0。 |
| **`std1.create('ccc_step1','CoilCurrentCalculation')`必须在`std1.create('stat1','Stationary')`之前加进同一个Study** | 极易漏掉：只有Stationary会报错"Numeric coil ... not solved for. Solve it in a Coil Geometry Analysis step."。study-step类型不是`'CoilGeometryAnalysis'`，也不是`'StationarySourceSweep'`（那个是多线圈互感扫描用），是和`ccc1`同名的`'CoilCurrentCalculation'`。 |
| `mphinterp(model,'mf.Bz','coord',...,'dataset','dset1')` | 取磁通密度分量，和es物理场取`V`/`es.normE`写法一致。 |
| 完整可跑通的参考脚本 | `test_magnetic_coil.m`（螺旋线圈通1A电流，中心B场/无限长螺线管估算比值≈0.85）。 |

### 7.15 CPT 中的磁场力 / 点释放 / 发射方向分布 / 壁面条件 / 粒子间相互作用
| 调用 | 说明 |
|---|---|
| `cpt.create('mf1','MagneticForce', 3)` | 洛伦兹力的磁场部分，**不是**`'LorentzForce'`。`B_src`合法值：`"EarthsMagneticField"`/`"userdef"`/`"fromCommonDef"`（如果模型还有已求解的`mf`物理场，还会出现`"root.comp1.mf.Bx"`）。`userdef`模式用`.set('B', {'0','0','0.01[T]'})`。**⚠️必须显式`.selection.all`（或`.selection.named(...)`）指定作用域**——为空时不报错，只让磁场力处处为零，粒子走直线（速度大小仍守恒，容易被误判成"物理是对的"）。排查方法：先画轨迹图看是不是直线，而不是只看有没有报错。 |
| `cpt.create('rel1','Release', 3)` | 域(3维)级别粒子释放特征，"体内释放"。`InitialPosition`合法值只有`"MeshBased"/"Density"/"RandomPosition"`——**没有手动指定单点坐标的选项**。`v0`支持直接设三分量向量。 |
| `inl1.set('InitialVelocity','ConstantSpeedHemisphere'/'ConstantSpeedCone'/'ConstantSpeedLambertian')` | 固定速度大小、方向按分布随机撒开：半球均匀/限定圆锥角内均匀/圆锥角内按余弦定律加权。配套属性`alphac`(圆锥半角，默认`pi/3`)。 |
| `cpt.feature('wall1').set('WallCondition', ...)` | 合法值：`"Bounce"/"Freeze"/"Stick"/"Disappear"/"Pass"/"DiffuseScattering"/"IsotropicScattering"/"MixedDiffuseSpecular"/"GeneralReflection"`。默认`Freeze`。 |
| `cpt.create('ppi1','ParticleParticleInteraction', 3)` | 粒子间相互作用，属性名是`InteractionForce`（不是`InteractionType`/`ForceType`），合法值`"Coulomb"`(默认!)/`"LinearElastic"`/`"LennardJones"`/`"UserDefined"`。配套属性`ks`/`r0`/`rcoff`/`sigma`/`eps`/`Fu`。 |
| 完整可跑通的参考脚本 | `test_cpt_magnetic_force.m`（均匀Bz场电子回旋，实测半径0.58mm vs理论0.57mm，误差2%）。 |

### 7.16 多极杆 (Quadrupole/Hexapole/Octupole)
| 调用 | 说明 |
|---|---|
| N根圆柱杆沿方位角均匀排布 | MATLAB循环算每根杆的`pos`：`x=R_center*cos(theta_k)`, `y=R_center*sin(theta_k)`，`theta_k=(k-1)*360/N`。经典四极杆理想双曲面近似半径比`r_rod=1.1468*r0`。 |
| 相邻杆交替`+V_rf`/`-V_rf` | 偶数N才能严格交替；配合`Complement`选择拿真空域（不要用外层大圆柱的selresult，见§7.2）。 |
| **物理验证**：中心电位/场应为0，偏轴电位应按`r^(N/2)`幂律增长 | 四极(N=4) `V∝r^2`吻合4位有效数字、六极(N=6) `V∝r^3`、八极(N=8) `V∝r^4`——这是检验多极杆几何+交替电位设置对不对的最快方法。 |
| RF时变场加到CPT：方案A(手写表达式) | 静电场只解一次(单位幅值)，CPT的`ElectricForce`用`E_src='userdef'`+表达式`(V_target/V_rf_solve)*es.Ex*cos(2*pi*f_rf*t)`——同一个静电解，换幅值/频率完全不用重新解静电场。 |
| RF时变场加到CPT：方案B(原生振荡模式) | `ef1.set('TimeDependenceOfField','TimeHarmonic')`+`.set('FrequencySpecification','SpecifyFrequency')`+`.set('omega', f_rf)`+`phi0`。`MagneticForce`也有同样一组属性。（本项目未完整验证，只确认属性存在。） |
| `ElectricForce`还有`SpecifyForceUsing`(合法值`"ElectricField"`(默认)/`"ElectricPotential"`) | 除了给电场表达式，也可以直接给电位表达式让特征内部做`-∇V`。 |
| 离子(区别于电子)粒子属性设置 | `cpt.feature('pp1').set('mp', '100*1.66054e-27[kg]')`+`.set('Z','1')`(默认电子`Z=-1`，别忘了改)。 |
| **马蒂厄方程稳定性判据实测验证** | 四极杆(N=4)，q=0.5(理论稳定)时最大偏移中位数仅0.26*r0；q=1.2(超过稳定边界)时100%超过r0，明显发散。 |
| `Release`用`MeshBased`在整个真空域释放时的采样偏差 | 大量释放点会落在靠近杆表面/外边界的网格节点上，做"近轴动力学"这类测试必须在后处理时按初始半径过滤释放点。 |
| 完整可跑通的参考脚本 | `test_multipole_geometry.m`+`test_multipole_es.m`+`test_quadrupole_stability.m`。 |

### 7.17 爱因茨尔透镜 (Einzel Lens)
| 调用/发现 | 说明 |
|---|---|
| 几何 | 3片同轴圆盘(接地-透镜-接地)，每片用"实心圆柱-同轴小圆柱"布尔差挖出中心通孔。 |
| **聚焦强弱只取决于`KE_beam/|V_lens|`这个无量纲比值** | 静电透镜的基本标度律，绝对值不同但比值相同会给出完全相同的聚焦效果。 |
| 反射风险 | `|V_lens|<KE_beam/e`，否则粒子会在到达透镜中心前被反射回去。 |
| 完整可跑通的参考脚本 | `test_einzel_lens.m` + `test_einzel_cpt.m`。 |

### 7.18 线性离子阱 (Linear Ion Trap, LIT)
| 调用/发现 | 说明 |
|---|---|
| 几何 | 四极RF杆(径向约束)+两片端盖孔径电极(轴向约束，挖孔圆盘手法)，共享同一个真空域。 |
| **同一component里两个同类型物理场的坑：自定义tag不是变量命名空间** | 建了`es_rf`/`es_dc`两个`Electrostatics`后，`mphinterp`/CPT表达式里写`'es_rf.Ex'`全部报"Undefined variable"。**COMSOL变量命名空间按物理场类型+创建顺序自动分配默认前缀**：第一个`Electrostatics`永远是`es`(依赖变量`V`)，第二个自动变成`es2`(依赖变量`V2`)，不管Java API tag叫什么。自定义tag只在Java API层有效。**排查方法：依次探测`V`/`V2`/`es.Ex`/`es2.Ex`。** |
| RF+DC合成力表达式 | `ef1.set('E', {'(Vrf/100)*cos(2*pi*f*t)*es.Ex+(Vdc/100)*es2.Ex', ...})`。 |
| 完整可跑通的参考脚本 | `test_lit_geometry_es.m` + `test_lit_cpt.m`。 |

### 7.19 飞行时间分析器 (TOF) + 反射器 (Reflectron) 基础版
| 调用/发现 | 说明 |
|---|---|
| 几何 | 源极盘→挖孔引出栅极(接地)→漂移管(真空)→实心反射镜电极，挖孔圆盘手法。 |
| **⚠️漂移管必须有接地导体壁，否则远端电极的场会"漏"穿整个漂移区** | 光是不设边界条件不够，必须有接地导体真正屏蔽远处电极。 |
| **组件级别的Union/Difference选择类型不可靠，改用MATLAB端`setdiff`** | `Adjacent`选择拿到全部边界的实体ID数组，MATLAB `setdiff`算差集，再用`Explicit`选择类型建立最终选择。 |
| **平板电极的离轴离子径向散焦是真实物理，不是bug** | 有限半径平板电极边缘场散焦——真实反射式TOF仪器常用弯曲反射镜面或多层网格梯度而不是单一平板镜就是为了避免这个问题。 |
| `Inlet`的`v0`哪怕想表示"标量速度"也必须给三分量向量 | `inl1.set('v0','0[m/s]')`报错，必须写`{'0','0','v_extra'}`。 |
| 参考脚本 | 该基础版已被oa-TOF环栈反射镜取代，本节记录的物理教训（接地漂移管壁、平板边缘径向散焦）仍然有效。 |

### 7.20 静电扇形场能量分析器 (ESA)
| 调用/发现 | 说明 |
|---|---|
| 几何 | 同轴圆柱电容器：内层接地，外层加正电压，中间环形真空隙供离子飞行。**关键坑：内外电极务必被一个更大的"整体真空圆柱"完全包住**。 |
| **设计电压公式（同轴柱形电容器精确解）** | `E(r)=V0/(r*ln(R2/R1))`（不是平行板近似）。 |
| **FEM与解析式验证：4位有效数字吻合** | 比值全部落在0.9998~1.0002之间。 |
| **能量选择性定量验证** | 设计能量离子稳定运行；偏高30%的离子精确撞在外电极半径处——ESA按能量筛选离子、与质量无关。 |
| `'h'`是保留的COMSOL全局变量名 | 自定义参数避开这个名字。 |
| 完整可跑通的参考脚本 | `test_esa.m`。 |

### 7.21 磁扇形场质谱仪 (Magnetic Sector)
| 调用/发现 | 说明 |
|---|---|
| 原理 | 固定加速动能KE，`r=m*v/(qB)=sqrt(2*m*KE)/(qB)`，`r∝sqrt(mass)`。 |
| **⚠️`Release`(MeshBased)测回旋运动时，必须保证"整个圆轨道直径"远小于域尺寸** | 挑到离边界太近的粒子会被边界截断，测出的"直径"可能精确是理论值的整数分之一——比值恰好是"干净的分数"通常意味着轨迹被截断，不是物理误差。 |
| **定量验证** | `r∝sqrt(mass)`吻合5位有效数字。 |
| 完整可跑通的参考脚本 | `test_magnetic_sector.m`。 |
| **本节及§7.16-7.27所有CPT类测试脚本约定：都必须存轨迹图** | `figure('Visible','off')`+`print(...,'-dpng','-r150')`，比单纯看数字更容易发现问题。 |
| **⚠️外部MATLAB画的PNG轨迹图 ≠ .mph文件里能看到轨迹** | 必须显式调用`model.result.create(...,'PlotGroup3D')`建立COMSOL原生结果节点，再`model.save(...)`，否则COMSOL Desktop打开时Results树里看不到粒子轨迹。 |
| **⚠️原生轨迹图太多太杂看不清：正确修复是限制"释放范围"，不是事后过滤** | `Filter`类型的Plot Group/Trajectory子特征、`Filter`数据集接到`ParticleTrajectories`、`Ball`选择限制释放范围——都不work。**真正有效**：在几何里加一个小圆柱体`relvol`专门作为释放子区域，`Release`特征的`.selection`只指向`geom1_relvol_dom`，CPT物理场仍选整个`sel_vac`。 |

### 7.22 CPT 背景气体碰撞 (`Collisions` 特征，适用于碰撞池/CID建模)
| 调用/发现 | 说明 |
|---|---|
| `cpt.create('coll1','Collisions',3)` | 正确名字就是`'Collisions'`（不是`GasCollisions`/`BackgroundGas`等）。 |
| 关键属性 | `Nd`(背景气体数密度，默认`1E20[1/m^3]`) / `mg`(默认`0.04[kg/mol]`，恰好是氩气摩尔质量) / `T`(默认`293.15[K]`)。 |
| **⚠️关键坑：`Collisions`特征本身只是容器，不加子特征(Attribute)碰撞完全不生效** | `Nd`从1e20试到1e28全部零效果。真正定义"发生哪种碰撞、截面多大"的是挂在它下面的Attribute子特征（`Elastic`/`ResonantChargeExchange`等），不加Attribute等于截面隐式为零。 |
| **正确的最小可用配方** | `elastic1 = coll1.create('elastic1','Elastic'); elastic1.set('CountCollisions', true);`——默认自带常数截面`xsec=3E-19[m^2]`。 |
| `StudyStep`属性需要显式绑定到实际求解的时间相关study | 先建了多个study的模型都应显式设置一遍，避免叠加坑。 |
| **⚠️碰撞计数变量的正确取值方式：只有`mphparticle`的`'expr'`选项能用** | `mphparticle(model,'dataset','pdset1','expr',{'cpt.coll1.elastic1.Nc'})`。 |
| 完整可跑通的参考脚本 | `test_collision_cell.m` / `test_collision_cell_gpu_comparison.m`。 |

### 7.23 Wien 滤波器 (交叉 E×B 速度选择器)
| 调用/发现 | 说明 |
|---|---|
| 物理原理 | `qE=qvB`给出`v=E/B`——只和速度有关，和质量、电荷无关。 |
| 建模方式 | `ef1.set('E_src','userdef')`+`ef1.set('E',{E0,'0','0'})`，`mf1.set('B_src','userdef')`+`mf1.set('B',{'0',B0,'0'})`，叠加在同一个`cpt`下即可。 |
| **⚠️坑：偏转量必须相对释放起始位置算，不能直接看终点绝对坐标** | `MeshBased`释放会带来随机初始小偏移，必须算`x_end-x_start`。 |
| 完整可跑通的参考脚本 | `test_wien_filter.m`。 |

### 7.24 ParticleParticleInteraction 库仑排斥/空间电荷效应
| 调用/发现 | 说明 |
|---|---|
| **真实离子间库仑力在常规质谱仪时间尺度/离子间距下极弱** | 需要用极低动能+极紧密初始离子团才能在合理仿真时长内看到效果。 |
| **验证结果** | 加`ppi1`后径向扩散标准差涨到33倍，最大半径涨到28倍。 |
| 完整可跑通的参考脚本 | `test_space_charge.m`。 |

### 7.25 Resonant Charge Exchange (共振电荷交换) 碰撞类型
| 调用/发现 | 说明 |
|---|---|
| 物理原理 | 离子把电荷"转移"给静止的中性背景气体原子，特征信号是速度几乎瞬间掉到接近零（区别于Elastic的渐进式散射）。 |
| 建模方式 | 和`Elastic`同一套模式：`cex1 = coll1.create('cex1','ResonantChargeExchange')`。 |
| 完整可跑通的参考脚本 | `test_resonant_charge_exchange.m`。 |

### 7.26 FTICR/ICR 离子回旋共振池
| 调用/发现 | 说明 |
|---|---|
| 组件构成 | 均匀轴向磁场(回旋，径向约束)+两端DC捕集电极(轴向约束)。 |
| **⚠️关键坑：两个端盖电极给同一个正电压、没有接地参考，导致轴向电位完全没有梯度** | 拉普拉斯方程只有两个"电位相同"的边界条件时解是平凡常数。**修复**：把圆柱侧壁显式接地。 |
| **验证结果：组合运动出现真实的"磁控漂移"(magnetron drift)现象，不是bug** | 回旋频率与轴向捕集频率量级相当时两种运动强耦合，真实FTICR仪器要求回旋频率远高于轴向捕集频率才能让两者干净分离。 |
| 完整可跑通的参考脚本 | `test_icr_cell.m`。 |

### 7.27 简单质谱仪整机集成
| 调用/发现 | 说明 |
|---|---|
| **总体架构：分阶段建模，而非塞进单一网格** | CPT物理场每个接口只允许一个`ParticleProperties`，电子和离子不能共用一个`cpt`接口——电离阶段和"离子旅程"阶段必须是两个独立模型。 |
| `Ionization` Collision Attribute | `ReleaseSecondaryElectron`默认`true`——每次电离碰撞会真的生成新粒子，容易导致粒子数指数增长、内存爆炸，实际EI场景应设`false`。 |
| `Release`的热发射叫`Maxwellian`(不是`Inlet`用的`Thermal`) | `Maxwellian`模式会把速度分布按`Nvel`(默认200)个离散速度档确定性采样，**每个释放点会被复制成约200份**，容易导致内存爆炸。 |
| 正离子受力方向 | `F=qE=-q∇V`，repeller必须在高电位、引出栅在低电位。 |
| RF离子导管约束高速离子束时 | 关键看"离子穿越时间/RF周期"这个比值是否远大于1。 |
| N极杆近轴回复力标度`r^(N-1)` | 离子非常靠近轴线时，四极杆(线性回复力)反而比高阶极杆更稳健。 |
| 小孔透镜散焦效应 | 引出栅孔径相对下游主体半径比值越小，散焦越严重。 |
| 分辨率计算 | `R=t/(2·FWHM)`，`FWHM=2.3548σ`。 |
| 完整可跑通的参考脚本 | `ms_stage1_ei_source.m`。 |

### 7.29 理想细网格栅网(内部边界)技术 + CPT `Release`分布/随机化 API 速查

> 独立于任何具体项目的通用技术：任何需要"电极但离子必须能穿过"的场景都适用。

| 调用/发现 | 说明 |
|---|---|
| **建造理想细网格栅网：`Union`+`intbnd=true`** | ```matlab\nwp = geom1.feature.create('wp_tag', 'WorkPlane');\nwp.set('quickplane', 'xy'); wp.set('quickz', z_expr);\nwp.geom.feature.create('r1', 'Rectangle');\nwp.geom.feature('r1').set('size', [800 800]);\nwp.geom.feature('r1').set('pos', [-400 -400]);\ngeom1.feature.create('uni_grids', 'Union');\ngeom1.feature('uni_grids').selection('input').set({'vacbox','wp_tag'});\ngeom1.feature('uni_grids').set('intbnd', true);\n```。`Ndomains`应该保持不变。因为离子能从整个面任意穿过，**栅网不再需要开孔**，直接做成和真空域截面等大的整块board即可——这比"实心板挖孔"（会有孔径-透镜散焦效应）根本地好。 |
| **给内部边界加电位：用Box+`'allvertices'`选择** | ```matlab\ncomp1.selection.create('selb_grid', 'Box');\ncomp1.selection('selb_grid').set('xmin',-400); ...set('xmax',400);\ncomp1.selection('selb_grid').set('zmin',[z_expr '-1[mm]']); ...set('zmax',[z_expr '+1[mm]']);\ncomp1.selection('selb_grid').set('condition', 'allvertices');\ncomp1.selection('selb_grid').geom('geom1', 2);\n``` |
| **⚠️陷阱：`Box`/`Cylinder`选择用`'intersects'`条件会误抓不相关边界** | 两个电位条件抢同一个边界ID时COMSOL不报错，只是其中一个静默失效。**表现症状**：`selection.entities()`对"选择集本身"查询正常，但对"已经赋给某个物理特征的selection"查询显示0。**修复**：一律换成`Box`+`'allvertices'`，范围完整指定三个维度。 |
| **⚠️陷阱：两个应该衔接的真空域之间留几何缝隙** | 离子精确停在缝隙边缘，且**不随仿真时长增加而改变**——这正是判定"缝隙/边界问题"而非"仿真时间不够"的信号（纯时间不足会让轨迹再往前挪一点）。**修复**：让两个域的z范围有实打实的重叠。 |
| **CPT `Release`：显式指定释放粒子数** | `InitialPosition='Density'` + `N=<count>`，而非依赖网格节点数(`MeshBased`默认)。 |
| **`InitialKineticEnergy`是模式选择器枚举，不是自由表达式字段** | 合法值`"Expression","ConstantSpeedSpherical","ConstantSpeedHemisphere","ConstantSpeedCone","ConstantSpeedLambertian"`。**`v0`才是真正的自由表达式字段**，需要能量分布随机化时把能量公式换算成速度写进`v0`。 |
| **⚠️`randnormal()`不是COMSOL函数——用`random()`(均匀分布)手动Box-Muller构造高斯分布** | `sqrt(2*abs(E_mean_eV+E_std_eV*sqrt(-2*log(random(1)))*cos(2*pi*random(2)))*1.602176e-19[C]/m_kg)`。**单位陷阱**：基本电荷常数必须显式标`[C]`。`SamplingFromDistribution`需设`'Random'`，否则每个粒子拿到同一个值。 |
| **粒子数量大时的内存教训** | 电场求解耗时与粒子数无关，只跟网格规模有关；CPT求解本身可行到数万粒子，但`mphparticle`取回完整轨迹数据在极大N时会"Out of memory on server"。**教训**：只提取需要的统计量，或放宽CPT输出tlist的时间步密度（脉冲/快速动态段保留精细步长，纯漂移段可以粗化），不要囫囵吞枣地拉全部时间步×全部粒子的数据。 |
| **⚠️理想化零厚度边界依然不能跟不同电压的实体接触** | "必须跨越真空域整个截面"（避免留一圈没被电位覆盖的缝隙）和"不能碰不同电压的实体"是两条独立的规则，不要因为满足了前者就忘了后者。如果这个理想化边界恰好跟另一个不同电位的固体导体在同一半径/位置相接（比如它俩恰好共享屏蔽壳内壁的同一个半径值），必须留一个显式小间隙，跟真实固体导体之间"不同电位必须留间隙"是同一条规则，理想化边界并不豁免。**间隙大小要参照局部网格尺寸(`hmax`)来选，不能脱离网格分辨率盲目取"越小越好"**——实测取0.1mm（远小于15mm的局部网格尺寸）直接导致`FreeTet`网格生成失败（"Failed to constrain a mesh vertex to its geometric entity"，网格没法在这么薄的楔形区域收敛），改用量级接近网格尺寸的间隙（如2mm）后网格/求解都正常。 |

### 7.31 官方PDF资料速查索引（本地 `official_docs/*.pdf`，共5份）

> 目录下有5份COMSOL官方PDF手册，单份300~1200页、4.5~13.3MB，**不要试图逐页通读**——
> 用`python`+`pymupdf`把全文抽成纯文本（每份几秒钟）存到临时目录，再用Grep按关键词
> 定位到具体页码，最后按需读那几页原文确认上下文。示例：
> ```python
> import fitz
> d = fitz.open('COMSOL_ProgrammingReferenceManual.pdf')
> with open('out.txt','w',encoding='utf-8') as out:
>     for i, page in enumerate(d):
>         out.write(f'\n===PAGE {i+1}===\n' + page.get_text())
> ```
> 抽出的文本文件本身也很大（参考手册那份抽完约10万行），不要直接整份Read，同样只用
> Grep定位关键词后读命中行附近的片段。这5份是COMSOL 6.3/6.4版本文档，个别措辞可能跟
> 已装的6.4版本有细微出入，但API命令语法基本稳定，可以直接当权威参考。

| 文件名 | 页数 | 章节结构 | 主要内容 / 什么时候查 |
|---|---|---|---|
| `COMSOL_ProgrammingReferenceManual.pdf` | 1234（5份里最厚，最权威） | 1 Introduction / 2 General Commands / 3 Geometry / 4 Mesh / 5 Elements and Shape Function Programming / 6 Solvers and Study Steps / 7 Results / 8 Graphical User Interfaces / 9 The COMSOL File Formats | **最底层、最权威的Java Model Object API参考**——任何`model.xxx().yyy()`调用的精确语法、每个feature类型的合法属性名/取值/默认值表都在这里查（比如`StopCondition`/`cpl`非局部耦合/求解器`tout`/`tstepsbdf`等属性就是从这里查到的，见§7.30）。**遇到"这个属性到底叫什么名字/合法值有哪些"就先查这份**，比瞎猜/逐个试快得多。 |
| `LiveLinkForMATLABUsersGuide.pdf` | 400 | 1 Introduction / 2 Getting Started / 3 Building Models / 4 Working with Models / 5 Calling External Functions / 6 Command Reference | **MATLAB这一侧的脚本手册**——`mphparticle`/`mphglobal`/`mphinterp`/`mpheval`/`mphmax`/`mphmean`等所有`mph*`辅助函数的参数、属性、返回结构体字段说明都在这里（第4章"Working with Models"里的"Extracting Results"一节，第6章是按字母排的完整命令索引）。**遇到"这个mph*函数支持哪些option/返回结构体里有哪些字段"就查这份**，不要跟`ProgrammingReferenceManual`（那份是Java API，不含`mph*`函数）搞混。 |
| `ParticleTracingModuleUsersGuide.pdf` | 414 | 1 Introduction / 2 Particle Tracing Modeling / 3 Mathematical Particle Tracing / 4 Charged Particle Tracing / 5 Particle Tracing for Fluid Flow / 6 Multiphysics Interfaces | **CPT（带电粒子追踪）物理场的官方说明书**——本项目核心物理场。`Release`/`Wall`/`Particle Counter`/`Force`等每个子特征的作用、暴露的变量名（比如`<tag>.Nsel`/`.Nfin`/`.alpha`，见§7.30C）、Formulation选择（Newtonian等）都在第2、3、4章。**遇到"CPT某个子特征到底暴露什么变量/该怎么配置"就查这份**。 |
| `ACDCModuleUsersGuide.pdf` | 540 | 1 Introduction / 2 Theory for the AC/DC Module / 3 Modeling with the AC/DC Module / 4 Electric Field and Current Interfaces / 5 Magnetic Field Interfaces / 6 The Electrical Circuit Interface / 7 Multiphysics Interfaces and Couplings | **静电场/磁场物理场（ES/`mf`磁场/电路）的官方说明书**——本项目加速器/反射镜的`Electrostatics`边界条件类型、磁场`Coil`特征（对应§7.14/§8的磁场调试记录）的理论背景和配置选项在这里查。偏理论+GUI操作说明，Java API精确语法仍以`ProgrammingReferenceManual`为准。 |
| `ApplicationProgrammingGuide.pdf` | 326 | Syntax Primer / Model Object（Java）/ The Application Object（COMSOL Desktop内置的Application Builder：表单、GUI、方法库）/ Programming Examples | **跟本项目关系最弱的一份**——这是COMSOL Desktop内部"Method Editor"/"Application Builder"的编程指南（用于在COMSOL桌面里做交互式GUI应用/自定义方法，不是外部MATLAB LiveLink脚本）。本项目走的是纯MATLAB外部脚本路线，用不上Application Builder那部分；但其中"Model Object"一章（Java API对象结构、`get`/`set`方法约定）跟`ProgrammingReferenceManual`第2章内容有重叠，可以作为补充交叉印证。**除非要在COMSOL Desktop里做GUI插件，否则很少需要查这份**。 |

---

## 8. 磁场建模全流程实测记录（附：完整调试叙事，支撑上面§7.14/§7.15速查表）

> 这是§7.14/§7.15速查表背后的完整调试过程叙事，是本项目第一次接触Magnetic Fields/
> 洛伦兹力，之前全部只涉及Electrostatics+Charged Particle Tracing。

### 8.1 定位正确的物理场 tag：`InductionCurrents`
直接尝试`comp1.physics.create('mf','MagneticFields','geom1')`报"Unknown physics
interface"。没有现成的"列出所有可用物理场"API，只能挨个猜候选tag名：`MagneticFields`
(✗) / `InductionCurrents`(✓) / `MagneticFieldsNoCurrents`(✗) /
`RotatingMachineryMagnetic`(✓，但不是要的) / `ACDC`(✗)。**教训：COMSOL Java API里物理
场的"内部tag"和GUI里显示的名字经常对不上，纯靠试错定位，直接试一次比纠结许可证文档快。**

### 8.2 用已验证的 Helix 几何直接当线圈导体，走通 `Coil` 特征
`mf.create('coil1','Coil',3)`直接选中电子枪项目里已验证的Helix螺旋线圈实体作为域，
`CoilType`默认就是`'Numeric'`，完全不需要额外建模——本来是为电子枪灯丝设计的几何，
直接拿来当电磁铁线圈测试也一次成功。

### 8.3 三层报错，逐层剥开 Numeric Coil 的真实求解要求
依次遇到、依次解决的三个报错（每一个都会掩盖下一层）：
1. `"No selection specified for the Input subfeature under the Geometry Analysis
   subfeature"` → Coil的`ccc1.ct1`(Input终端)需要显式选一个边界。
2. `"Undefined material property 'sigma' required by Domain Coil 1"` → 线圈域必须有
   电导率材料属性。
3. `"Numeric coil Domain Coil 1 (coil1) not solved for. Solve it in a Coil Geometry
   Analysis step"` → **最隐蔽的一步**：`std1.create('stat1','Stationary')`单独存在
   不够，必须在它*之前*额外`std1.create('ccc_step1','CoilCurrentCalculation')`。
   试过`'CoilGeometryAnalysis'`(报"Operation cannot be created in this context")和
   `'StationarySourceSweep'`(能创建+求解，但报"No sources found."，是给多线圈互感扫描
   用的)，最终靠"study-step类型名字可能和物理场自动生成的子特征同名"这个直觉试出
   `'CoilCurrentCalculation'`。

### 8.4 定量验证：有限长螺线管中心磁场
5匝、线圈半径0.3mm、通电1A，解出中心轴向`Bz=5.33e-3 T`，对比无限长螺线管理想公式
`mu0*N*I/L=6.28e-3 T`，比值0.85——完全符合"有限长度、匝数不多的螺线管，中心场应该略
小于无限长理想值"的物理直觉。

### 8.5 CPT 磁场力：一次"没报错但结果全错"的排查
配好`MagneticForce`后模型顺利求解，`|v|`全程精确守恒（磁场力不做功，看似过关的信号），
但轨迹是一条几乎笔直的线，完全没有回旋。**根因：`MagneticForce`特征创建后忘了调用
`.selection`，默认作用域是空**——这和`Release`/`Inlet`没选择时会在编译期直接报错不
同，力类特征选择为空时**不报错，只是让力处处为零**，粒子保持初速直线运动，由于磁场力
不做功，连"能量守恒"这个常规正确性检查都不会揭穿它。补上`mf1.selection.all`后轨迹立刻
变成漂亮的正圆，回旋半径0.58mm对比理论0.57mm，误差2%。**教训：CPT里所有"力"类特征都
要把"有没有设置selection"当成检查清单的第一项。**
