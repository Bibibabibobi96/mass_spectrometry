# 公共器件连接合同层

本目录实现获批连接架构中的求解器中立公共边界。项目拥有provided/required port；
`integrations/<connection-family>/`拥有具体profile、连接几何、adapter和联合证据；本目录只负责
解析显式五元组、失败关闭兼容性冲突并冻结`resolved connection + composition plan`。

公共Python API为：

- `load_connection_profile_registry(path)`：读取并校验一个integration的profile注册表；
- `resolve_connection_profile(registry, profile_id, repo_root=...)`：按显式profile加载两端port，
  先复核port对项目物理合同的authority SHA与JSON Pointer绑定，再检查身份、状态schema、坐标/法向、
  单位、时钟、间隙、孔径、电位和场责任区；
- `write_resolved_and_plan(...)`：写出包含源SHA-256的resolved connection及引用其SHA-256的plan；
- `verify_composition_plan(...)`：执行前重新计算resolved SHA并核对五元组与耦合模式。

`execute_connection.ps1 -ValidateOnly`保持原公共门禁；`-PrepareOnly -AdapterEntrypoint <path>`可在
同一复核后委托integration-owned adapter检查映射但不启动求解器。真正委托执行还必须同时给出显式
`RunId`和`-SolverAuthorized`，并由adapter串行调用其冻结入口。公共层不会从两个project ID猜测端口、
自动发明连接器、复制物理参数或执行profile中未冻结的命令；缺少adapter、RunId或授权均失败关闭。

`adapter_contract.py`只为执行映射和迁移等价预登记提供窄schema：映射可声明profile ID、adapter路径、
已有stage入口和已有case ID，不允许几何、电压或粒子参数。具体integration负责把映射SHA和路径冻结进
composition plan，并在执行前再次核对。`resolve_integration_engineering_budget(...)`复核integration、
profile、同源粒子身份和compact留存后，只返回该次profile的三个stage硬帽；它复用公共进程树监控器，
不建立integration私有资源门禁。

port是项目物理合同的发布视图，不是第二权威。每个port必须通过`authority.source_contract`和
`source_sha256`锁定仓库内来源，并用`bindings`逐项声明port JSON Pointer与source JSON Pointer；
解析和执行复核时任何来源过期、pointer缺失或绑定值漂移都会失败关闭。

零长度直连允许空场责任段；正长度连接必须由无重叠、无空洞的连续segments覆盖。`field_overlap`
必须包含integration拥有的场区。所有数值均在profile读取前由JSON Schema限制，旋转正交性、法向
相对关系和覆盖连续性由解析器进行语义校验。
