# RF多极杆到单次反射oaTOF集成

本目录承载四、六、八极杆到单次反射oaTOF的连接profile、运行编排、联合分析和集成证据。它不是第三份
器件模型；两端项目继续拥有自己的物理设计与资格。

## 阅读顺序

1. 仓库根[`README.md`](../../README.md)。
2. [当前集成状态](docs/INTEGRATION.md)。
3. 上游目标项目与[oaTOF项目](../../projects/single_reflection_oa_tof_mass_analyzer/README.md)的
   `README.md → docs/PROJECT.md`。
4. 仅在追溯旧结果时读取仓库根[`docs/history/`](../../docs/history/)。

## 入口

- 连接profile：[`config/connection_profiles.json`](config/connection_profiles.json)
- 实验campaign：[`config/experiment_campaign.json`](config/experiment_campaign.json)
- 单流程布局：[`config/single_flight_layout_profiles.json`](config/single_flight_layout_profiles.json)
- 唯一公开执行入口：
  [`workflows/family_source_closure/execute.ps1`](workflows/family_source_closure/execute.ps1)
- 静态门禁：[`verify_integration.ps1`](verify_integration.ps1)

## 目录职责

```text
config/      # connection、campaign、layout和runtime机器合同
runtime/     # 解析、冻结、单流程布局和求解器编排
stages/      # 受公开workflow调用的内部阶段
workflows/   # 用户可执行入口
analysis/    # 集成级求解器无关分析
tests/       # 静态回归
docs/        # 当前集成状态
```

当前支持分阶段三段链与连续SIMION单次飞行；准确流程、电极映射、参数分类和资格边界只查
[`docs/INTEGRATION.md`](docs/INTEGRATION.md)。
