# 2026-08-17 三区加速器外部文档审阅

> `DOC_STATUS: ARCHIVED_READ_ONLY`

本记录冻结对用户提供的三份2026-08-16外部文档的审阅和项目处置。它不复制外部文件、不修改
Nutstore内容，也不取代当前
[`三区理想理论`](../theory/three_zone_accelerator_ideal_theory.md)、
[`PROJECT.md`](../PROJECT.md)或机器合同。

## 1. 输入身份和版本关系

| 文件 | 身份 | SHA-256 | 页面/行数 |
|---|---|---|---:|
| `20260816__oatof-three-zone-accelerator-analysis-rendered.pdf` | 较早渲染版 | `4AEE1E5D0DCAC41D034175A6F44C37D43374258430E7565862F3BC7B88C05250` | 21页 |
| `20260816__oatof-three-zone-accelerator-third-order-analysis-and-solution-rendered.pdf` | 较新渲染版 | `5C784B315AE8F7A775AC8C83E49E3FA39F94D9D2F102156F0B861D89CAEF27B1` | 24页 |
| `20260816__oatof-three-zone-accelerator-third-order-analysis-and-solution-fixed-math.md` | 最新可审阅源文 | `211123E546595BF9B7295F9DEF83A177A62DC20E00C66949E4EEF8092F64E18A` | 1416行 |

两份PDF的正文与公式token归一化相似度为98.6%；可观察差异来自标题、目录、分页、断词和公式布局，
未发现实质不同的推导版本。逐页对象边界检查未发现被裁出页面的公式。较新24页PDF第23页的
$\Gamma_3\approx0$ 把 $\approx$ 渲染成缺字，而较早21页PDF第21页显示正常；Markdown源式正确。
因此主审版本是 `fixed-math.md`，PDF只用于渲染核对，不能凭PDF缺字改写公式。

## 2. 可保留的理论内容

下列内容经独立代数和量纲核查可保留：

- 第3.3节三区精确归一化时间，及第3.4节固定 $\chi$ 的 $B_1$—$B_4$；
- 第3.5节逆场强跃迁表达与 $E_2=E_3$ 的严格二区退化；
- 第3.6节 $\ell_{23}$、$\lambda$、$\gamma_0=1-\lambda$ 和 $g=\gamma-\gamma_0$ 连续参数化；
- 第4.1节 affine $\chi(\mathcal W)$ 链，特别是
  $A_3=B_3-24\beta^5/(E_1p^5)$ 和
  $A_4=B_4+240\beta^7/(E_1p^7)$；
- 第2.2—2.3节 $T_u$—$T_{uuuu}$ 链及均匀 $u\in[-1,1]$ 时三阶、四阶population sigma系数
  $1/(6\sqrt7)$ 与 $1/90$；
- 第5.3—5.4节联合Jacobian、尺度化条件数和
  $\Gamma_3=\partial_gD_3-\mathbf j_{3R}J_R^{-1}\mathbf j_g$；
- “$D_3=0$ 不是有限2.2 mm全宽充分条件”、必须继续检查 $D_4$、混合项、峰模态和精确cohort的
  结论强度是合适的。

文档没有给出可审的具体三区数值解、电压根或长度代入，因此不存在可确认的“三区性能已验证”数值
结论；其建议仍是待检验假说。

## 3. 确定错误和遗漏

### 高优先级

1. **SI时间换算漏项。** 第3.2节式 `t=sqrt(m/(2q))*tau` 在长度为mm、场强为V/mm时缺少
   `1e-3`。当前项目正确换算是
   $t_{\rm s}=10^{-3}\sqrt{m/(2q_e)}\tau$；漏项使绝对时间放大 $10^3$。
2. **焦面和 $L_{\rm up}$ 约束与当前项目坐标不符。** 第4.2节把“加速器出口到反射器入口的机械
   距离”冻结，再令 $L_{\rm up}=L_{A\to R}^{\rm geom}-D_A$；当前项目固定全局一阶焦面
   $z_{A,f}=0$，应由 $A_1=0$ 派生 $D_A$ 后把加速器出口平移到 $z=-D_A$。反射器入口不动时，
   固定的是焦面到反射器入口的 $L_{\rm up}$，变化的是出口到反射器入口的机械距离。固定焦面不等于
   强制 $D_A=D_A^{\rm old}$，也不会自动消耗 $g$。
3. **后向折返门禁缺失。** 第3.1节和第4.3节的 $\mathcal W>V_{G1}$、能量余量及
   $\mathcal W_x$ 单调性不能排除 $\chi<0$ 的粒子先撞排斥极。还必须对完整cohort检查
   $x_{\rm turn}=x-\chi^2/E_1$ 的最小间隙。
4. **全宽能量包络不完整。** $\mathcal W$ 是精确二次式。除两个端点外，若
   $y_*=-p/(2\beta^2)$ 位于区间内，必须纳入极值；线性半宽估计不能替代该门禁。
5. **现有全域理想场身份不能直接三区化。** integration的
   `runtime/resolved_region_field.py` schema v1只声明
   `accelerator_stage1/accelerator_stage2`、`repeller/grid1/grid2`、`accel1/accel2`，Lua也只有两个
   加速场分支；当前 `grid2` 是加速器出口。外部文档把
   `FULL_DOMAIN_PIECEWISE_IDEAL_FIELD` 视作可直接加一段的路线与仓库事实不符。三区需要新拓扑身份、
   schema、解析器、Lua、求解器几何、电极与CAD映射，不能覆盖现有profile语义。

### 中优先级

1. **符号碰撞。** 第2.2节先用 $q$ 表示 $m/q$ 中的电荷，又在式
   $q=\mathcal W''_c=2\beta^2$ 中重定义为能量二阶系数；第3.1节用 $d_1,d_2,d_3$ 表示长度，
   第3.5节又用 $d_1$—$d_4$ 表示导数系数。当前理论分别使用 $q_e$、$w_2$、
   $\ell_i$ 和 $k_n$。
2. **T0身份冻结不足。** 第8.1节列出source/cohort和clock，但没有明确把质量电荷比、离子电荷符号、
   名义能量/参考电势和cohort权重/分布都列为不可变身份。不同身份会改变 $\chi,\beta$、时间换算和
   有效域。
3. **科学证据与工程资格混层。** 文档依据的是100 Th、+1、10 eV集成问题及2.2 mm先导筛选，不是本
   项目524 Da、+1、`5±0.4 eV` Formal。它足以提出三阶假说，不足以晋升当前Formal或宣称真实三区
   性能。
4. **成功阈值只是建议。** 未经机器合同预注册的降幅、非劣或条件数阈值不能作为通过标准；项目已把
   精确阈值、seed和stage前驱收归独立post-pilot campaign。

### 低优先级

- 较新PDF的 $\approx$ 缺字是渲染缺陷，不是源公式差异；引用该PDF时应以Markdown源式为准。
- 两个PDF标题和页数不同，但没有证据支持“存在另一套实质推导”。不应把版式差异当成独立理论版本。

## 4. 长度和 $\lambda$ 的准确澄清

外部Markdown第3.1节只定义三个长度符号，没有指定数值；第3.6节定义
$\ell_{23}=\ell_2+\ell_3$ 和 $\lambda=\ell_2/\ell_{23}$，也没有给出数值。第7.1节的首选方案是保留
Stage1、固定一个预选 $\lambda$，以 $g$ 为唯一新增电学变量；第8.1节T0要求冻结Stage1、原Stage2
总长和 $\lambda$。第5.5节只把可变 $\lambda$ 列为额外第四自由度方案。

因此“文档固定了各区具体长度”是不成立的。当前Formal的 `3.0 mm` 与 `16.8 mm` 可以作为项目继承
基准，但 $\lambda=0.5$ 或 `8.4/8.4 mm` 只是独立试算假设。当前post-pilot隔离campaign进一步扫描
$\ell_1,\ell_{23},\lambda$ 是项目自己的受控试验设计，不是外部文档要求。

## 5. 项目处置

- 公式和假说转入当前
  [`三区理想理论`](../theory/three_zone_accelerator_ideal_theory.md)，修正单位、符号、焦面、精确包络和
  后向折返门禁。
- 采用 `T0,T1,T2,G1,T3,T4a,T4b,(G2→可选T4c→G2),T5` 的单stage、receipt驱动漏斗；没有自动 `--all`，
  不调用商业求解器。
- `32,955` 仅是人工授权后可选T4c的解析外层网格基数，不是默认、不是已运行计数、不是性能指标，也
  不是SIMION/COMSOL运行数。
- 新证据最高为求解器无关 `Functional / PROVISIONAL / POST_PILOT`；当前Formal和工程profile保持
  不变。真实三区拓扑只允许在独立后继Candidate中实施。
