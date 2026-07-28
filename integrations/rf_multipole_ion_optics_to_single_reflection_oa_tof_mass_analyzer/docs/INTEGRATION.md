# RF多极杆离子光学到单次反射oaTOF质量分析器集成

## 当前身份与边界

本目录是四、六、八极杆离子光学到单次反射正交加速TOF质量分析器的唯一连接实例层。项目端口、
公共连接合同和公共解析器的职责由
[`COMPONENT_CONNECTION_ARCHITECTURE.md`](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md)
规定；本文件只记录本连接族的profile、迁移状态和证据边界。

[`connection_profiles.json`](../config/connection_profiles.json)是本连接族的profile机器权威。
[`integrations/registry.json`](../../registry.json)只负责全仓发现，不复制profile参数。公共解析器必须由
显式的上下游项目、端口和profile ID选择连接，禁止从目录或两个项目ID猜测。

## 四极杆迁移oracle

四极杆现有S2/S3链在迁移等价复验完成前仍是活动实现。本目录保存两种冻结拓扑的映射：

- `rf_quadrupole_s2_s3_grounded_connector_gap_1mm`：1 mm接地圆柱真空连接腔，oaTOF端为
  `1.0 mm × 0.9 mm`矩形入口；
- `rf_quadrupole_s2_s3_direct_mating_gap_0mm`：零长度直接对接，不创建连接器实体。

两者都继承同一刚性轴映射、公共0 V参考和`instrument_clock_epoch.v1`，并映射现有S2无脉冲联合场、
S3共享时钟脉冲及下游SIMION延续。profile中的粒子计数只是旧oracle索引，不是本框架产生的新证据；
静态PASS不证明新旧等价、数值收敛、机械可制造、跨求解器连接器对等或Formal资格。

profile中的位置和角度容差只用于复核冻结坐标的数值身份，不是装配公差；`wall_thickness_mm=0`只复刻
旧COMSOL零厚度接地边界。0 mm profile的`inner_radius_mm=0.45`表示下游`1.0 mm × 0.9 mm`矩形孔的
限制半高，不表示存在半径0.45 mm的圆柱连接器。解释权威与旧证据映射见
[`migration_oracles.json`](../config/migration_oracles.json)。

本目录现有一个非空迁移adapter和公开入口
[`execute_integration.ps1`](../execute_integration.ps1)。它先由公共解析器冻结resolved connection与
composition plan，再把两个profile分别映射到既有`nominal_gap_1mm`和
`direct_mating_gap_0mm` case；实际物理执行仍由项目已有S2 field runner和串行S3 cumulative runner
完成。adapter不复制连接几何、电压、粒子源或求解器数值。

`-ValidateOnly`只验证合同；`-PrepareOnly`还验证adapter registry SHA、S2/S3入口和case映射，不启动
商业软件。真正执行必须给出显式`RunId`和`-SolverAuthorized`；adapter只把RunId时间戳映射到旧runner
已有`Stamp`参数并串行调用。旧runner尚不原生接收integration plan SHA，因此本层在plan旁写轻量receipt
绑定RunId、resolved和plan；这只是迁移追溯，不是新求解器实现或等价证据。

[`migration_equivalence_preregistration.json`](../config/migration_equivalence_preregistration.json)
把旧N=100 oracle以路径和SHA只读绑定。两个profile的新入口重跑、同源核对及五项census比较完成前，
状态固定为`BLOCKED/NOT_RUN`，不得宣称等价、晋升资格或归档旧S2/S3实现。

## 六极杆和八极杆边界

本目录的family范围覆盖四、六、八极杆，但当前机器registry只登记已经有可解析S2/S3 oracle的
四极杆profile。六、八极杆不会用四极杆数值或`pending`对象冒充connection profile：

- 它们现有的无加速全尺寸请求和resolved设计继续归各自项目；
- 待各自provided port发布，且连接模式、相对位姿、连接器、公共电位、时钟和场责任区全部明确后，
  才在本family加入具名profile；
- 加入前不引用四极杆run ID，不复制四极杆几何，不声明联合运行或资格。

公共解析器只接受完整resolved profile；不为未知物理提供默认值或pending通过路径。

## 静态门禁

[`verify_integration.ps1`](../verify_integration.ps1)运行纯Python静态测试，检查：

- 全仓registry只引用一个连接族权威；
- 两个四极杆profile身份唯一，且项目配置和oracle来源真实存在；
- 四极杆两个profile逐字段保持1 mm/0 mm S2/S3映射；
- 六、八极杆不存在伪造的pending profile；
- 公共schema和解析器存在，两个resolved四极杆profile均可解析。
- 两个profile都能生成非空composition step并映射到真实S2/S3入口；
- migration preregistration保持`BLOCKED/NOT_RUN`且旧oracle SHA未漂移；
- `ValidateOnly`和`PrepareOnly`不启动商业求解器，execute边界要求显式RunId与授权。

该门禁不启动COMSOL、SIMION、MATLAB或CAD，也不替代新旧链的真实求解器等价复验。
