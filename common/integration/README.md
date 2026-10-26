# 公共器件连接合同层

本目录实现[连接架构](../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md)中的求解器中立公共边界。项目拥有provided/required port；
`integrations/`拥有具体装配和物理工作流；本目录只负责
解析显式五元组、失败关闭兼容性冲突并冻结`resolved connection + composition plan`。

已批准的多组件目标见[统一组装规范](../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#统一组装目标)。
本目录已增加[多实例配方布局编译](../../integrations/README.md#配方解析)，校验提供者机械接口和直接位姿，
由同一CLI接受`--recipe`与`--components`并输出composition plan v3。当前仅为`layout_only`，不执行物理工作流；
局部裸导引、冷却前端、多极杆→IP、IP→MR准备及单反射整机已由直属工作流消费完整父plan并派生实际范围；
各执行器的组件支持集和原生验证边界见[集成状态](../../integrations/docs/INTEGRATION.md)，不由布局编译能力推断。

## Python API

公共 Python API 为：

- `compile_assembly_layout(recipe, components, *, local_scope=None)`：校验完整父配方的直接位姿、真实端面、法向和间隙，并派生实际范围；
- `derive_assembly_scope(parent_plan, *, local_scope=None)`：核对完整父plan的内嵌配方与接口，再派生默认full或显式local范围；不重新读取来源路径；
- `resolve_assembly_recipe(recipe_path, components_path, repo_root=..., local_scope_path=None)`：读取显式来源并冻结其身份；
- `load_connection_profile_registry(path)`：读取并校验一个integration的profile注册表；
- `resolve_connection_profile(registry, profile_id, repo_root=...)`：按显式profile加载两端port，
  先复核port对项目物理合同的authority SHA与JSON Pointer绑定，再检查身份、状态schema、坐标/法向、
  单位、时钟、间隙、孔径、电位和场责任区；
- `write_resolved_and_plan(...)`：写出包含源SHA-256的resolved connection及引用其SHA-256的plan；
- `verify_composition_plan(...)`：执行前重新计算resolved SHA并核对五元组与耦合模式。

两个公开注册表入口各自递归校验完整 profile schema；同次解析不再逐 profile 重复校验。
port 来源身份和物理兼容性仍在解析边界检查。

## 完整与局部范围 API

不传 `local_scope` 时，`scope.kind=full`，范围就是此次 recipe 的全部实例与连接；不发现其他组件，
也不硬编码最大整机。新增拓扑由实验显式切换到新配方，新的 plan 使用所选配方全部实例；旧 plan 仍相对其
冻结配方完整，不回写历史。作者演进与运行失效的完整规则见[连接标准](../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#演进时的稳定性与失效边界)。

局部声明只包含 `instance_ids`（非空、唯一、已知实例 ID 列表）、`research_scope` 与
`boundary_assumptions`（均为非空说明）。Python 使用可选 `local_scope`，原 CLI 使用
`--recipe ... --components ... --local-scope <声明.json> --plan-output ...`；声明也冻结到 `input_files`。
显式选择全部父实例仍保留 `kind=local` 和作者研究范围，不擅自改写成完整范围。

v3 plan 保留完整父 `recipe`、`components` 和全部端面 `connection_checks`；`scope.instance_ids`
明确实际选中实例，`scope.connection_ids` 是两端都选中的内部连接，`scope.boundary_connection_ids`
是仅一端选中的边界连接，均从同一父连接表派生。`local_scope` 保存作者原声明，重验时重新派生并比较；
消费者按实际范围选择同一父对象，不能生成另一套位姿或把边界说明冒充已实现的场边界条件。
本解析器不接收粒子源，不按源位置裁剪装配，也不修改源；源与实际范围的匹配由消费工作流负责。
v2 不再作为活动输入格式；v1 成对连接的实际执行合同保持原职责，冻结历史不修改。

## 执行边界

[`execute_connection.ps1`](execute_connection.ps1) 的 `-ValidateOnly` 执行公共校验；`-PrepareOnly -AdapterEntrypoint <path>`可在
同一复核后委托integration-owned adapter检查映射但不启动求解器。真正委托执行还必须同时给出显式
`RunId`和`-SolverAuthorized`，并由adapter串行调用其冻结入口。公共层不会从两个project ID猜测端口、
自动发明连接器、复制物理参数或执行profile中未冻结的命令；缺少adapter、RunId或授权均失败关闭。


## 身份与兼容性

port 是项目物理合同的发布视图，不是第二权威。每个port必须通过`authority.source_contract`和
`source_sha256`锁定仓库内来源，并用`bindings`逐项声明port JSON Pointer与source JSON Pointer；
解析和执行复核时任何来源过期、pointer缺失或绑定值漂移都会失败关闭。

零长度直连允许空场责任段；正长度连接必须由无重叠、无空洞的连续segments覆盖。`field_overlap`
必须包含integration拥有的场区。所有数值均在profile读取前由JSON Schema限制，旋转正交性、法向
相对关系和覆盖连续性由解析器进行语义校验。
