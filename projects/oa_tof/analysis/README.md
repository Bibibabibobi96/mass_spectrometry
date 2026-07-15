# oa-TOF统一分析入口

本目录只负责与求解器无关的指标、统计和图形。COMSOL模型树仍由MATLAB维护，SIMION运行时仍由
GEM/Lua/Fly2维护；Python不直接解析MPH或PA。

## 正式环境

- Python：3.11（MATLAB R2025b支持；本项目不使用默认Python 3.14或旧Python 3.8）。
- 依赖声明：仓库根`pyproject.toml`。
- 已验证锁定版本：仓库根`requirements-lock.txt`。
- 本机隔离环境：仓库根`.venv/`，不进入Git。

首次建立或完全重建环境：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements-lock.txt
```

## 权威边界

- 机器数据定义：`../config/analysis_contract.json`。
- 迁移基准身份与旧MATLAB参考：`../config/analysis_baselines.json`。
- 数值算法：`peak_metrics.py`。
- CSV/XLSX导入、出图和CLI：`reference_analysis.py`。
- 回归门禁：`verify_reference_analysis.ps1`。

正式机器输入优先使用CSV/JSON。XLSX只用于接收SIMION GUI人工导出；读取后立即输出
`particles_normalized.csv`，Excel本身不是指标真值。

## 一键验证

在仓库根运行：

```powershell
.\projects\oa_tof\analysis\verify_reference_analysis.ps1
```

默认验证四个冻结数据集的文件大小、行数和SHA-256，然后生成统一指标、谱图、落点图和固定粒子
COMSOL/SIMION峰形对比。结果写入仓库外
`artifacts/projects/oa_tof/results/reference_analysis/baseline/`。

分析单个CSV或GUI导出的XLSX：

```powershell
.\.venv\Scripts\python.exe `
  .\projects\oa_tof\analysis\reference_analysis.py single `
  <input.csv-or-xlsx> --mass 524 --output <artifact-output-directory>
```

## 维护规则

1. `R=m/FWHM_m`和直接半高宽只在`peak_metrics.py`维护一份。
2. 修改KDE带宽、网格点数或半高交点算法时，先提升契约版本，再更新基准；不得只调图形使结果接近。
3. MATLAB中为COMSOL/SIMION GUI保留的结果是软件内展示层，必须用冻结数据与本参考实现核对。
4. 本目录的通用代码只有在第二个项目实际复用后才能上移`common/`。
