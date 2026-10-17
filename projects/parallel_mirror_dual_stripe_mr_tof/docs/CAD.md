# MR-TOF CAD 实施说明

本页提供当前工程交换的操作入口与验收边界；参数、有效证据和开放任务以
[PROJECT](PROJECT.md)为准，不维护第二份电压或坐标表。
旧平行镜53件交付、审批及失败处理全过程保存在[只读交付里程碑](history/20261015__cad-exchange-delivery-milestone.md)。

## 当前交付与适用范围

当前交付为[163154发布恢复][delivery]：40个独立命名电极STEP、6个可选C0参考面及一个装配总览，
不是旧平行镜53件包。该恢复仅逐字节再发布已完成的倾镜CAD，不是一次新的商业冷读或几何计算。
实际文件、电位、坐标、部件映射和验收记录以包内索引及来源manifest为准。

- 镜保持冻结的对称会聚位姿；正负镜不因同电压合并，空间不连续部件保持独立。
- 只对已验证的同电势局部接触组做精确union，避免跨独立STEP的未解决接触；不同电位不能接触或合并。
- Stripe沿用原始准确B-spline实体及完整装配变换，不用模拟采样折线或重新拟合代替。
  模拟外发版省略全部安装圆孔，保留束槽及端部；原始CAD归档不写回。
- 所有STEP使用共同世界坐标。装配总览用于一次查看空间关系，不替代单件电位索引，也不授予SolidWorks参数化mate。
- C0为零厚边界参考面，不是带壁厚、开孔的制造外壳；开放BEM省略C0属于另一边界模型，
  不能仅因它远离束路就宣称等价。OA理想网格保持零厚透明sheet，不封堵束流孔。
- 5 μm是用户批准的STEP有限工程交换验收精度，不是仿真场、制造精度或全曲面的严格误差上界；
  体积偏差单列。原native/Parasolid严格验收口径未因此改变。

第三方BEM消费尚未验收；mixed-dimensional的网格sheet与实体框需由消费端正确支持。
当前倾镜版[英文模拟交接包][pulsar-handoff]已精简为2页并完成渲染检查，包含逐积分步真实轨迹与40电极STEP边线叠图、完整电压及离子初态；
STEP复用163154封存字节，未新增商业CAD冷读或第三方消费资格。邮件草稿未发送；旧平行镜说明不作为配套文档。
交付不包括自行补造的MCP内部、绝缘件、紧固件、材料、公差或加工图，不授予制造或数值Formal资格。

## 资产与坐标权威

| 对象 | 入口与边界 |
|---|---|
| 原始用户CAD | [项目描述符](../config/project.json)的legacy artifact位置；保留原身份和引用，只读使用 |
| CAD—项目坐标 | [坐标合同](../config/cad_to_theory_frame.json)；位置用完整变换，方向只应用旋转 |
| 当前物理几何 | 成功场run冻结的resolved几何与完整电压authority，而非当前可变配置或旧CAD推断 |
| 曲线恢复与被否定构造 | [原始审计](CAD_AUDIT_20260902.md)及[交付里程碑](history/20261015__cad-exchange-delivery-milestone.md)，不授当前资格 |

原始ion foil零件名、电极编号或同为接地都不能替代物理部件身份。
五个曲线实例须按namespace及完整父子变换映射；mirror shield不因ID相同就成为central foil。
SolidWorks API使用米，项目使用毫米，转换只在边界施加一次；冷读按实际实例矩阵验收。

## 唯一活动生成入口

使用[run_resolved_cad_export](../analysis/run_resolved_cad_export.ps1)，其
[生成器](../analysis/export_resolved_cad.py)调用共享SolidWorks桥接。运行环境与工作副本规则见
[操作指南](../../../docs/OPERATIONS.md)，几何同步验收见[仓库架构](../../../docs/REPOSITORY_ARCHITECTURE.md#gui-与-cad-门禁)。

从仓库根执行以下模板；尖括号为需替换的已封存来源，不是可直接执行的路径。
先计划检查，再用相同输入及新run身份授权生成：

```powershell
$cadArguments = @{
    FieldRunPath = '<成功场run>'
    AssemblyRunPath = '<对应实际飞行run>'
    RunId = '<新的build/cad运行标识>'
    ReuseCadRunPath = '<已验收原生CAD run>'
    OriginalStripeRunPath = '<原始准确曲线证据run>'
    StripePoseRunPath = '<对应完整位姿证据run>'
    OmitMountingHoles = $true
    MachiningHoleAuditRunPath = '<成功原孔审查run>'
}
& .\projects\parallel_mirror_dual_stripe_mr_tof\analysis\run_resolved_cad_export.ps1 @cadArguments -CheckOnly
# 检查通过并获准商业执行后：
& .\projects\parallel_mirror_dual_stripe_mr_tof\analysis\run_resolved_cad_export.ps1 @cadArguments -Approved
```

FieldRunPath提供冻结resolved_geometry与frozen_input；AssemblyRunPath提供实际assembly materialization。
原曲线与位姿证据必须成对。Reuse仅复用受管来源，仍对新输出真实验收，不继承整包PASS。
单件Smoke仅验证指定件，不能冒充全部交付。输出统一归新build/cad run，不在原始档案目录操作。

上述模板仅用于无孔原生重建。倾镜独立STEP为互斥分支，不能在该splat上叠加选项；
新建参数对象仅保留以下输入，不携带Reuse、OriginalStripe、StripePose、Omit或MachiningHoleAudit：

```powershell
$stepArguments = @{
    FieldRunPath = '<当前倾镜成功场run>'
    AssemblyRunPath = '<对应实际飞行run>'
    RunId = '<新的build/cad运行标识>'
    ElectricalStepCadRunPath = '<已验收无孔原生CAD run>'
    IndividualStepDeliveryRunPath = '<已封存独立STEP run>'
    ConnectedStepContacts = $true
    FrozenMirrorPose = $true
}
& .\projects\parallel_mirror_dual_stripe_mr_tof\analysis\run_resolved_cad_export.ps1 @stepArguments -CheckOnly
# 计划通过且获准后，同一参数对象加-Approved执行。
```

此分支的显式输入职责如下：

| 选项 | 用途及前提 |
|---|---|
| ElectricalStepCadRunPath | 已验收无孔原生来源，冻结电位及世界变换 |
| IndividualStepDeliveryRunPath | 已封存独立STEP来源；不连续件、正负镜及C0分别命名 |
| ConnectedStepContacts | 仅处理已验证同电势局部连通组，保留OA零厚sheet |
| FrozenMirrorPose | 将原平行镜实体按新冻结几何施加完整14镜刚体变换；新镜STEP重新冷读，不复用旧world曲线样本 |

倾镜分支保持非镜几何及槽不变，完整电压从新authority读取，不被旧几何记录覆盖。
其余未变STEP可复用封存字节。准确曲线原件保持不动，不用刀具包围盒或无关去除体积判定槽改变。

## 验收与再发布

每次实际生成须保留独立文件、BOM/电位映射、几何验收与manifest。
尺寸用六轴精确极值而非近似GetBodyBox；曲线比较实际trim边及共同坐标，控制点编码变化不等于形状变化。
检查槽、零安装孔、单位、完整位姿、实体/sheet身份、设置恢复及实际冷重载。
接触检查区分体积交集与共面/共边；只关闭体积干涉选项不能证明没有接触。
包围盒重叠也不能单独证明实体相交。

已成功封存STEP的再发布仍用同入口，另建仅含FieldRunPath、AssemblyRunPath、新RunId与
PublishCadRunPath的参数对象；不携带前述几何创建或STEP修复选项。先CheckOnly，再Approved。
STEP-only不传Word参数，不启动SolidWorks，
不复制原始曲线采样，也不赋予新的冷读资格。ZIP按封存白名单保持字节，不包含内部launcher或供应商临时文件。
若原商业计算成功而发布失败，原摘要和manifest不改写；经公共封存恢复后引用其明确的发布身份，
不能把failed摘要直接改称success。

需要更新英文说明时，只有已渲染验收的DOCX及其成功document manifest才可作为输入，
不得夹带待验收Word。该文档必须匹配倾镜几何与完整电压；旧53件native＋Word分支不是当前STEP交付。
文档结构检查仅证明链接与归档结构，不代替CAD冷读、第三方消费或制造资格。

[delivery]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_163154__build__cad__mrtof-tilted-step-publication-recovery/delivery_publication.json
[pulsar-handoff]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261016_140921__build__python__pulsar-trajectory-handoff/summary.json
