# oaTOF 2.2 mm源z接收宽度自动重构诊断

DOC_STATUS: ARCHIVED_READ_ONLY

## 目的与边界

本次只使用SIMION最新连续单次飞行流程，保持八极杆、加速器、无场区和真实N=1000母样本不变，将
oaTOF理论源释放z全宽从1.0 mm改为2.2 mm。它是`INCONCLUSIVE_DIAGNOSTIC_ONLY`，不授予数值收敛、
Candidate、Formal或制造资格。

## 参数合同与自动重构

profile唯一直接输入为`source_release_full_width=2.2 mm`。加速器d1保持3.0 mm，电压保持
2240/1760 V；耦合公式自动得到：

| 量 | 1.0 mm基线 | 2.2 mm候选 |
|---|---:|---:|
| 能量包络 | 1920–2080 eV | 1824–2176 eV |
| 反射器二级长度 | 96.1563 mm | 116.6151 mm |
| 反射器总长度 | 216.1563 mm | 236.6151 mm |
| 中间栅电压 | 1628.8001 V | 1628.8001 V |
| 背板电压 | 2531.1999 V | 2723.1999 V |

重建计划为`frontend_pa=false`、`flight_tube_pa=false`、`reflectron_pa=true`。运行时直接把resolved合同
写入run-local Lua默认值，避免SIMION命令行可调变量名称限制；Formal资产未修改。

## SIMION结果

成功父run为`20260810_145000__sim__cross__oct-source-z22-single-flight__n1000`，子run为
`20260810_145000__sim__simion__rf-oatof-single-flight-gap0__n1000`。基线使用
`20260805_183000__sim__simion__rf-oatof-single-flight-gap0__n1000`。

| 指标 | 1.0 mm基线 | 2.2 mm候选 | 变化 |
|---|---:|---:|---:|
| release→handoff→pre-pulse→grid2→detector | 1000→968→950→948→948 | 1000→968→950→948→948 | 0 |
| 检测传输 | 94.8% | 94.8% | 0 |
| TOF均值 | 76.7308445 µs | 76.7308798 µs | +0.0353 ns |
| TOF样本σ | 0.938189 ns | 0.937039 ns | −0.12% |
| direct-KDE质量分辨率 | 17421.9 | 17369.5 | −0.30% |
| 脉冲前z σ | 0.545826 mm | 0.545826 mm | 0 |
| 加速器出口x/z角σ | 0.098777° | 0.098777° | 0 |
| 加速器出口y/z角σ | 0.133400° | 0.133400° | 0 |
| 最大反射z均值 | 758.6651 mm | 758.6654 mm | +0.0003 mm |

候选反射器PA构建耗时49.009 s，Fly资源日志为330.072 s。运行保持一个整体frontend PA、一个
flight-tube PA、一个run-local候选reflectron PA和一个detector PA；同一次Fly内没有重新释放粒子或
重置时钟。

## 结论

2.2 mm设计包络覆盖范围更大，但当前真实粒子的脉冲前z σ只有0.5458 mm，反射器实际穿透深度也与
基线几乎相同，所以扩大理论包络没有提高传输或分辨率。第一候选的价值是验证了“合同自由变量→理论
派生→选择性PA重建→连续SIMION”的自动链路；它不是当前性能改进方向。

两份未完成诊断包保留失败语义：14:00运行暴露SIMION长可调变量名限制；14:30运行在外层300 s工具
时限处被中断，但已推进到第697个离子。二者均不得作为物理结果。
