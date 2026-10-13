# MR-TOF CAD 实施说明

本页说明原始 CAD 如何作为机械证据进入参数化模型。当前模型状态、有效结论和开放任务只查
[PROJECT](PROJECT.md)，本页不维护第二份电压、坐标或几何参数表。

## 资产与坐标入口

| 对象 | 唯一定位方式 | 使用边界 |
|---|---|---|
| 原始用户 CAD | [项目描述符](../config/project.json)的 `legacy_identities[].artifact_location` | 保留迁移前 `mr_tof` 身份、文件名及相对引用，只读使用 |
| CAD—项目坐标 | [坐标合同](../config/cad_to_theory_frame.json) | 位置使用完整变换，方向/速度只应用旋转；不能从历史包围盒猜坐标 |
| 活动几何 | [候选几何合同](../config/simion_candidate_two_zone.json)及其 resolved 派生 | 审计过的机械约束参与派生，不由 CAD 反求电压或聚焦条件 |
| 曲线与原生特征恢复过程 | [日期化审计](CAD_AUDIT_20260902.md) | 解释来源和已否定构造，不能替代当前资格 |

原始 `ion foil 1/2/3` 等零件名不决定独立电势、面对面配对或电极 ID。组别与装配关系必须由机器合同
显式映射；局部零件坐标、子装配坐标和最终项目坐标必须通过完整父子变换链区分。

## 审计与修改步骤

### 当前冻结几何的工程外发

对外部求解器需要的同电压STEP集合，可在同一受管入口增加
`-ElectricalStepCadRunPath <已成功无孔CAD run>`，保留其原冻结`FieldRunPath`和`AssemblyRunPath`。
该分支只读已验收原生零件，复用逐件世界变换，将相同电压的部件放入同一全局坐标STEP；
C0六参考面独立为可选组，不与实际接地电极、罩和屏蔽件合并。
先`-Smoke -SmokePart potential_s1_electrode_11`完成曲面组验收。STEP包保持原冻结几何和电压，
随包提供文件/电压索引、坐标及C0简述，不重复制作或携带原已交付英文Word；
可选原文档身份输入仍须成对校验，不含专有文件。
原严格AP214 S1比较曾在质量体积偏差约3.770 mm³处停止；三个官方积分准确度及禁用导入
healing/analytic conversion均未消除该差异，不能据此判定曲线变化或自动放宽。
COMSOL独立CAD导入只证实格式可读，`mphmeasure`的体积是渲染网格近似，
且Parasolid原件局部坐标以米保存，不能与STEP毫米值未经单位映射直接比较。
原生/Parasolid已验收包不改；当前STEP转换必须继续区分导出几何、冷读转换与测量误差。
用户随后授权COMSOL官方CAD Export的单件转换例外：原已验收S1 Parasolid按原局部米坐标
导入并输出带单位的STEP，未建网或求场。该单件冷SW得到1实体、0薄面、0圆柱孔，
装配映射后的极值偏差约0.000426 mm、体积偏差约2.814 mm³；仍未通过原严格几何验收，
不得直接推广为全局装配或批量交付。新增STEP的米单位不能与外发说明的毫米隐式混用。
实际曲线诊断已修复native边参数与Curve参数不一致的问题：用官方
`ICurve.GetClosestPointOn`把实际edge端点映射到同一Curve的ParamU，并独立核Evaluate2端点，
逐body原子保存local米/world毫米采样，再纯分析比较，不因后续匹配失败丢失原始点。
S1四条有效B-spline按同空间坐标比较，最大有限采样偏差约0.0012794 mm；
1001/2001支持点的结果接近，但不是全曲面严格误差界，也不满足原10nm判据。
官方CAD Import的`importtol`为导入后geometry单位下的绝对长度，不是relative tolerance。
只将它从m单位下默认1e−5显式改1e−8的对照，STEP完整DATA段40118B逐字节未变；
继承已有实际冷读和有效曲线证据，不重复商业读入。不能把该参数量级当实际误差界或据此自动放宽。
用户于2026-10-13明确批准外发模拟STEP按5µm逐件有限工程交换精度验收、体积偏差单列。
该例外仅适用于STEP交换：原native/Parasolid的10nm及仿真精度判据不改。
原AP214入口先复验世界S1组，通过后才批量；逐件核实体/薄面、全局极值和实际trim边，
曲线使用2001点及1001支持点对照，不比较编码数组，不把有限采样最大值称严格全曲面误差界。
全部原生精确曲线与无孔源保持不动，不拟合、加厚理想网格或改变几何。
完整世界坐标AP214交付现已按该口径实际冷读53件：45实体、8薄面，26电压组及独立C0参考。
最大有限采样trim偏差约0.01404µm、精确极值偏差约3.70e−9mm；最大体积偏差
3.770093mm³（约13.1167ppm）单列，不能把边界采样解释为严格全域surface界。
原电压与原Word不变，STEP-only包附最小英文索引、坐标/C0说明及逐件验收CSV，不重复Word。
发布175输出的原绝对参数串达39008字符，超长Windows启动失败仅影响终态发布；
经原公共Python writer/full verifier零商业恢复，完整小证据与curve samples按公共
seal-stopped-payload保持success、具名pin/ready，不删除或改写已封存证据。
后续同规模自动发布仍须关闭公共writer的长参数传递及原始证据pin接线；
project-root相对声明虽保持authority，但本批仍约33221字符，不授自动恢复资格，
不能使用run相对裸路径或漏列原始输出来缩短参数。
用户后续要求所有不连续物理件独立STEP，包括同电压正负镜、所有接地件和六个C0面；
在同一入口配对`-ElectricalStepCadRunPath <原native源>`和
`-IndividualStepDeliveryRunPath <已封存电压组STEP源>`执行这一格式变体。
每行必须只有一个solid或sheet，否则停止并明确进一步拆分，不静默合并。
输出53独立STEP及额外`assembly/mrtof_electrode_assembly.step`（47实际组件，不含C0）供一次查看；
整体overview不能替代单件CSV电位赋值，不授SolidWorks参数化mate。
原world/native实际trim样本只在identity、pose一致时复用；新STEP仍实际冷读并采集曲线，
不以WantCubic=True的近似编码signature继承新导出资格，旧run和ZIP不改写。
该独立格式交付已真实完成：54STEP（53单件及整体overview），ZIP57英文ASCII成员，
逐件索引53行，不再包含任何接地/同电压合并STEP。整体在SW2022实际冷读为
document_type=2、assembly_leaves，47独立product leaf（45solid+2透明OA sheet）；
可以一次查看完整位置，但无SolidWorks参数化mate。所有新STEP实际trim采样均验收，
最大有限偏差仍约0.01404µm，体积偏差单列。公共发布因49089字符参数串恢复，
success/full229输出通过，原始证据具名pin/ready；不重复商业计算，不改旧包或Word。

官方支持依据（2026-10-13）：SolidWorks安装2022 `swconst.chm/FileSaveAsSTEPOptions.htm`
的AP214、`FileOpenOptionsSTEPIGESACIS.htm`的Import Diagnostics与analytic conversion，
`sldworksapi.chm`的`IMassProperty2.AccuracyLevel/CreateMassProperty2/Recalculate`及
`ICurve.GetBCurveParams3`。后者请求cubic参数时可能改变曲线编码表达，控制点数组不同
不能单独证明物理曲线不同；该转换精度受`IModeler.SetToleranceValue`控制。
COMSOL 6.4官方[CAD Import](https://doc.comsol.com/6.4/doc/com.comsol.help.design/design_ug_ref.6.40.html)
支持STEP/Parasolid；[几何测量](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.047.html)
明确体积、长度及面积由三角/多边形近似计算，不能用其替代严格实体等价验证。

唯一生成入口为[受管CAD导出](../analysis/run_resolved_cad_export.ps1)，调用
[项目生成器](../analysis/export_resolved_cad.py)与共享SolidWorks 2022桥接。
`-FieldRunPath`指定成功场的冻结`inputs/resolved_geometry.json`和`frozen_input.json`；
`-AssemblyRunPath`指定实际飞行的`two_prism_trial_materialization.json`。先`-CheckOnly`，
真实生成须`-Approved`，`-Smoke`仅是单件验证，默认mirror，可用`-SmokePart`指定已编译零件名；
不能替代全部零件交付。
输出归属独立`build/cad` run的`cad/`，包含独立交换文件、SLDPRT、全装配及OA、mirror、stripe/central、
prism/shield、detector、reference分组交换文件/SLDASM及BOM、验证记录；
不从当前配置或旧用户CAD反推几何，不合并不同电势的导体。

Stripe外发优先复用原始native实体，保留准确B-spline控制点/节点、束槽及端部，不将模拟采样折线当CAD曲线，
亦不对采样点重新拟合。原件只复制到新自有run；以已封存原件读审与父/子实例完整变换核对冻结曲线合同。
`-OriginalStripeRunPath`与`-StripePoseRunPath`成对指定这些成功证据，配合`-ReuseCadRunPath`只替换五个原件实例，
当前整包交付必须指定这对原件/位姿证据；旧折线件仅保留为历史模拟表示与单件诊断，不外发为曲线CAD。
原件与完整位姿只按上述五个具名物理实例映射，并核其namespace/electrode ID；同接地ID15的mirror shield
不是central foil，OA/detector的同编号也不共享原件。电势编号不能替代物理部件身份。
其余已保存当前部件不重建；原始归档不写或修补。模拟仍使用同一设计函数的多边形离散及非束路细节简化，
模拟外发版按用户要求省略全部安装圆孔；其体积与模拟其他简化的差异须明示，
不能强迫原生体积等于简化仿真或将连续曲线称为新Stripe设计。
CAD API使用米，边界处将项目毫米转换一次；Stripe保留原件局部轴，其余零件局部轴为项目y/z/x，
每实例完整刚体变换恢复项目x/y/z，native冷读按该实例的声明矩阵验收。
C0仅输出镜像后的零厚边界参考面，不能解释成已有壁厚与开孔的制造外壳；OA理想透明网格亦为
零厚参考面。检测器沿用声明包络，未补造MCP、支撑、紧固件、绝缘件、公差、材料与加工图。
工程外发不授仿真数值或制造Formal资格；须以实际全件保存、原生重开及所选交换格式回读记录判断完成。

模拟版生成显式加`-OmitMountingHoles`，在新自有可写副本使用官方`IFeature.SetSuppression2`
抑制圆孔seed及仅以该seed/基准面为父的孔镜像；central另抑制拥有两圆孔的圆形Cut。
原件、历史原孔包及其他48件不建模或写回。孔审查使用同入口`-InspectMachiningHoles`，
只读记录柱面/圆边、钻尖锥面、平面及`GetParents`；`GetTypeName`辨认Instant3D的ICE实际为Cut。
不按圆柱面法向删除外倒圆，不抑制矩形槽或其他切除。抑制后要求圆柱/钻尖面为零、非孔特征抑制状态不变，
仅允许被选圆孔特征独占消费的ProfileFeature父草图随孔自动抑制；共享草图不进入这项闭包。
原4/16/8条实体B-spline全部控制点/节点与封存原件审查一致；保留9条冻结设计曲线及原工程位姿。
新体积独立记录为无孔reference，填充增量须等于原圆柱与完整钻尖的解析体积，不套带孔原体积。
原生保存后冷重开及Parasolid冷读均保持10nm极值/控制点与相对1e−9体积要求，不修补、拟合或放宽。
孔审查确认原4mm束槽壁为x±2mm；M6圆柱止于x±4mm，59°钻尖尚余约0.498mm，
原安装孔未直接穿透束槽，但仍按用户明确要求全部省略；最终无孔判据不以这项原孔余量替代。
这些修改仅是模拟CAD变体，不自动改动原本已省略安装圆孔的冻结求场几何。
完整交付仍须五实例与53件/7装配真实验证，不能继承单件smoke通过。
已保存的无孔副本可由原`-ReuseCadRunPath`薄复用，另以`-MachiningHoleAuditRunPath`冻结成功原孔盘点
及manifest。来源可以是完整CAD失败run中的已封存文件，但不继承其整包通过；新run重新实际冷验
原曲线、零圆孔/钻尖、槽、姿态与相对该原孔盘点的解析填充体积，不重抑制或重建已去孔实体。
未去孔的副本仍按上述明确特征闭包处理。Parasolid路径重新导出/冷读，不要求来源另有STEP。

原始精确Stripe的AP214单件STEP保存成功，但冷`LoadFile4`曾触发供应商进程退出；
这不否定已提取并匹配冻结设计的原始B-spline，也不将未经冷读验收的STEP列为可交付。
当前精确外发使用同一入口的`-ExchangeFormat parasolid`，通过官方`SaveAs`导出`.x_t`；
单件原foil1已在新自有副本上完成严格冷读，六轴精确极值及体积符合原10nm/相对1e−9要求。
整包仍须独立通过全53件及7装配的真实验收，不继承单件或历史折线装配的通过状态。
Parasolid装配按官方选项输出展平的世界坐标实体，逐body核45solid/8sheet、极值、体积与独立部件对应；
电势部件不布尔合并，层级、引用与各实例刚体变换由冷重开的原生SLDASM及BOM保留。

官方路径查阅依据为安装的2022 `api/sldworksapi.chm`与`api/swconst.chm`：
`IFeatureManager.FeatureExtrusion2/FeatureCut3`、`IModelDoc2.InsertPlanarRefSurface`、
`ISldWorks.LoadFile4`、`IModelDocExtension.SaveAs`及`IInterferenceDetectionMgr.GetInterferences`。
另见[2022 STEP保存](https://help.solidworks.com/2022/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IModelDocExtension~SaveAs.html)
及[2022干涉检测示例](https://help.solidworks.com/2022/english/api/sldworksapi/Run_Interference_Detection_Example_CSharp.htm)。
采用官方草图/拉伸/切除/平面及格式导出接口，项目仅负责冻结几何投影与交付验证；模板设置只在
本次导入范围内绑定并恢复，不修改源CAD或供应商安装。
尺寸验收使用`IBody2.GetExtremePoint`六轴精确极值；安装官方说明明确`GetBodyBox`仅为近似包围盒，
不能用于比较或计算，原生与STEP重建后的近似盒差异不据此放宽真实尺寸、孔隙或体积容差。
保存后原生装配须无缺失叶引用并核刚体变换；STEP按逐叶世界极值/体积匹配，不能只用总量授位置一致。
STEP保存采用安装官方`swconst.chm/FileSaveAsSTEPOptions.htm`的`swStepAP=214`，仅在保存范围设置并恢复原值。
实际AP203全装配回读曾将两实体导为曲面，AP214冷读保留53叶精确极值与体积；不放宽容差或自动修补几何。
不使用在本机全装配导入中导致进程退出的直接BREP映射选项；原生和STEP几何仍须各自真实验收。
2026-10-12还只读查阅安装`swconst.chm/FileSaveAsParasolidOptions.htm`及2022 PIA：
`swParasolidOutputVersion`整数89、`swParasolidOutputVersion_latest=0`、`swXTAssemSaveFormat`toggle12。
`IModelDocExtension.SaveAs`原文规定文件扩展名选择转换格式、`ClearSelection2`导出全模型；
`ISldWorks.LoadFile4`原文允许disabled Interconnect、`r`参数将非DXF/ProE交换文件导入新文档。
本机实际2022 SP5输出Parasolid33.1；采用安装版本latest，不能把在线旧版本上限当作本机协议事实。
上述选项只在保存范围设置并逐值恢复，未选择直接BREP映射、重新拟合或几何修补。
去孔官方依据为2026-10-12查阅同安装2022手册的`IFeature.SetSuppression2/GetParents/GetTypeName`、
`ISurface.CylinderParams/ConeParams/PlaneParams`；`swconst.chm`的`swSuppressFeature=0`、
`swThisConfiguration=1`。显式当前configuration且无PropertyManager页；返回成功后回读抑制状态并重建验几何。
启动前已有SolidWorks实例时失败关闭并保留用户会话；本次owned PID记于api_state，
收尾恢复设置且仍有其他文档时保留窗口，不对用户检查原孔历史包执行保存或退出。
在线[Parasolid选项](https://help.solidworks.com/2022/english/api/swconst/FileSaveAsParasolidOptions.htm)
当前仅返回帮助壳，本次依据可访问的安装官方原文而非搜索摘要。
装配预加载已验证零件使用官方`OpenDoc6`的`Silent|ReadOnly`（3），只在新装配设置组件位姿和保存；
原生冷重开前关闭该装配及其全部自有零件窗口并核已关闭，不借缓存冒充保存后复验。
批量预加载采用安装官方`api/sldworksapi.chm`中
`SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~OpenDoc6.html`的TIPS：
以`DocumentVisible(False,swDocPART)`加载引用后恢复True，避免每个零件另建显示SceneGraph；
不改几何、resolved加载或错误判据。代表加载点GUI计数只作诊断，依据
[Microsoft GetGuiResources](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getguiresources)，不构成新资格门槛。
`-ReuseCadRunPath`仅薄复用终态受管run已保存的小CAD：冻结几何/authority/实际装配输入须逐字节一致，
复制零件到新run后逐件重新回读验收，不继承旧装配PASS。已确认的detector非关键自定义属性错误仅在
新自有副本使用官方`IDocumentSpecification.AutoRepair`；不启用破坏性的`CriticalDataRepair`，仍要求几何/STEP一致。
外发ZIP按验证清单选择CAD及必要冻结几何，不含供应商`.err`、临时副本或内部launcher/compiler；这些内部证据留run。

最终英文介绍使用已验收Word DOCX；版本化[正文来源](cad_delivery_overview.txt)仅用于重建，不作为最终介绍外发。
已封存几何的文档更新使用同一入口
`-PublishCadRunPath <成功CAD run>`：仍显式提供对应`FieldRunPath`、`AssemblyRunPath`及新`RunId`，
并指定`-EnglishOverviewPath <已验收DOCX>`、`-OverviewManifestPath <对应成功document run manifest>`，
先`-CheckOnly`，实际发布加`-Approved`。该分支只读取具名成功来源，核DOCX的bytes/SHA、
真实WordprocessingML正文/表格无CJK及53/7名称齐全，再核冻结物理输入与外发白名单、
源ZIP/成员身份及全53件/7装配完整验证，不启动SolidWorks、不复制独立120份CAD、不改变原run。
新ZIP保留源完整白名单项字节并只追加英文`CAD_OVERVIEW.docx`，不新增TXT介绍；原`DELIVERY_README.txt`仅为格式说明。
Word正文读取依据2026-10-12查阅的Microsoft Learn
[WordprocessingML结构](https://learn.microsoft.com/en-us/office/open-xml/word/structure-of-a-wordprocessingml-document)：
读取`word/document.xml`中的`w:body/w:p/w:r/w:t`，合并分段run并覆盖表格段落；二进制DOCX不要求ASCII。
此只读机器检查不代替作者按documents技能的渲染与逐页检查，也不重写Word包。
新run的`delivery_publication.json`明确为
已封存CAD的逐字节再发布，不授新商业冷读、制造或数值资格。零件/装配名称与英文说明不得含中文；
原immutable provenance JSON中的原始源路径保留原样。

1. 按[操作指南](../../../docs/OPERATIONS.md)使用共享 SolidWorks 入口，在独立候选 run 工作副本上操作。
2. 记录顶层及子装配的实际引用、缺失件、抑制/轻化状态、配置、单位和重建/保存警告。
3. 提取原生实体、草图、B-spline 与刚体变换；用共同坐标核对曲线、有限槽口、端部和净空。
4. 由冻结合同生成可检查的简化几何。包围盒重叠不证明实体相交，控制点包围盒不能替代曲面边界。
5. 把源文件和提取物身份写入 run/archive manifest，复核后才引用为发布证据。
6. 涉及正式机械几何时执行[仓库架构](../../../docs/REPOSITORY_ARCHITECTURE.md)规定的 GUI/CAD 同步门禁。

原始档案不作为工作目录。修改或保存前确认目标确为本次工作副本；不能因恢复了引用或提取曲线就把
原装配晋升为正式 CAD。

## 证据限制

已有审计记录覆盖装配恢复、原生曲线、有限槽口和组合位姿，但同时保留了被取代坐标与被拒绝几何。
这些记录不能整体视为当前模型证明；其 scratch JSON/STL 尚需逐项核对是否已有受管替代证据。
文档结构检查或历史审计不能替代实际SolidWorks冷重载、二进制身份及完整交付验收；
外发完成性以具名`cad_validation.json`和封存manifest为准，不由历史记录授予Candidate/Formal资格。
