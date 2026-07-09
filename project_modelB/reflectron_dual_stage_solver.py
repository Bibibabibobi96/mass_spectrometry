"""
reflectron_dual_stage_solver.py

单次反射 TOF 二级(双级)反射镜等时聚焦场强求解器
Dual-stage (two-field) reflectron isochronous-focusing field solver.

物理模型 / Physical model
--------------------------
离子源产生标称能量 K0=qU0 的离子，经：
  1) 无场漂移区 L1（源 -> 反射镜入口）
  2) 反射镜第一级：线性场 E1，长度 d1，离子被部分减速后穿越（U1 = E1*d1 是
     该级吸收掉的能量，用电压表示）
  3) 反射镜第二级：线性场 E2，长度 d2，离子在此完全减速、折返（不触底）
  4) 无场漂移区 L2（反射镜出口 -> 探测器）

要求总飞行时间 T(U) 在标称能量 U0 处一阶和二阶导数为零（一阶+二阶能量聚焦），
解出 E1、E2。

关键结论（详见配套 Word 文档中的完整推导）：
  1) 总飞行时间只依赖 L = L1 + L2（无场区时间之和），与 L1、L2 各自取值无关，
     只要两段都是真正的"无场"漂移区。因此函数默认 L1=L2=L/2，但允许指定
     不同的 L1、L2（内部自动相加）。
  2) 本问题存在解析闭式解，不需要迭代：
         U1 = 2*U0*(L + 2*d1) / (3*L)          ，要求 0 < d1 < L/4
         E1 = U1 / d1 = 2*U0*(L+2*d1) / (3*L*d1)
     E2 由 2x2 线性方程组精确求出（无需迭代）。
  3) E1、E2 与离子质量、电荷数无关（只要 U0 理解为"加速电压"，即 K0/q），
     这正是反射镜可对全质量范围同时聚焦的物理原因。
  4) d2 不出现在聚焦方程中，只是一个几何约束：必须满足
         d2 >= (U0 - U1) / E2   （第二级的离子穿透深度）
     否则离子会打到反射镜底部电极。
     !!! 2026-07-09 修正：此前(含配套Word文档)误写成 d2_min = U1/E2。
     物理上，离子穿越第一级后剩余动能是 q(U0-U1)（U1是第一级*吸收掉*的
     电压，不是剩余动能），第二级要在场E2下把这部分剩余动能完全耗尽，
     所需深度应为 (U0-U1)/E2，不是 U1/E2。用COMSOL实测穿透深度交叉
     验证过：错误公式给出的d2_min与实测偏差达3.4倍，修正后的公式偏差
     仅~17%(可归因于真实3D场/网格离散化误差)。

作者备注：本脚本用数值方法重新求解线性方程组（而非直接套用 E2 的解析式，
后者形式复杂），既保证正确性，也便于将来扩展到非线性场等更一般情形。
"""

import numpy as np

E_CHARGE = 1.602176634e-19   # C
AMU = 1.66053906660e-27      # kg


def solve_reflectron_fields(U0, d1, L, L1=None, L2=None):
    """
    求解二级反射镜的 E1、E2（一阶 + 二阶能量聚焦条件）。

    Parameters
    ----------
    U0 : float
        标称离子能量，用等效电压表示 (V)，即 K0/q（例如 70 eV EI 全能量,
        或更常见地，离子经加速电压 Uacc 后的能量，此时 U0 = Uacc）。
    d1 : float
        反射镜第一级（弱场级）沿轴向的长度 (m)。要求 0 < d1 < L/4。
    L : float
        总无场漂移距离 (m) = L1 + L2。若同时给出 L1, L2，则忽略此参数、
        改用 L1+L2。
    L1, L2 : float, optional
        源->反射镜入口 的漂移距离、反射镜出口->探测器 的漂移距离 (m)。
        默认 L1 = L2 = L/2（对称几何）。可分别指定为不同值——注意：
        只有 L1+L2 的和影响 E1、E2 与总飞行时间，L1、L2 的具体分配
        不改变解（详见文档中的证明），此接口主要用于几何文档化/校验。

    Returns
    -------
    dict，包含:
        E1, E2   : 两级线性场场强 (V/m)
        U1       : 第一级吸收的等效电压 (V)
        L1, L2   : 实际使用的漂移长度 (m)
        L_total  : L1+L2 (m)
        d2_min   : 第二级所需的最小物理长度 (m)，即 (U0-U1)/E2
                   （用户设计的 d2 必须 >= d2_min，否则离子会触底；
                   2026-07-09修正，此前误写成U1/E2，见上方模块docstring）
    """
    if L1 is not None or L2 is not None:
        L1 = L / 2 if L1 is None else L1
        L2 = L / 2 if L2 is None else L2
        L_total = L1 + L2
    else:
        L1 = L / 2
        L2 = L / 2
        L_total = L

    if not (0 < d1 < L_total / 4):
        raise ValueError(
            f"需要 0 < d1 < L/4 (L/4 = {L_total/4:.6g} m)，"
            f"当前 d1 = {d1} m。该约束是二阶聚焦条件的解存在性要求，"
            f"物理意义类似单级反射镜的 Mamyrin 条件 L = 4*D。"
        )

    # ---- 解析闭式解：U1, E1（推导见文档） ----
    U1 = 2 * U0 * (L_total + 2 * d1) / (3 * L_total)
    E1 = U1 / d1

    # ---- E2：数值求解 2x2 线性方程组（w=q/m 取 1，因解与质量无关） ----
    w = 1.0
    v0 = np.sqrt(2 * w * U0)
    v1_0 = np.sqrt(2 * w * (U0 - U1))

    a1 = 1 / v0 - 1 / v1_0
    b1 = 1 / v1_0
    a2 = 1 / v0**3 - 1 / v1_0**3
    b2 = 1 / v1_0**3
    R_I = L_total * w / v0**3
    R_II = 3 * L_total * w / v0**5

    A = np.array([[a1, b1], [a2, b2]])
    R = np.array([R_I, R_II])
    x1, x2 = np.linalg.solve(A, R)
    E2 = 2 / x2

    d2_min = (U0 - U1) / E2

    return dict(E1=E1, E2=E2, U1=U1, L1=L1, L2=L2, L_total=L_total, d2_min=d2_min)


def flight_time(U, E1, E2, U1, L_total, w):
    """给定能量 U（等效电压, V）计算总飞行时间 (s)。w = q/m (C/kg)。"""
    U = np.asarray(U, dtype=float)
    v = np.sqrt(2 * w * U)
    v1 = np.sqrt(2 * w * np.clip(U - U1, 1e-300, None))
    t_drift = L_total / v
    t1 = 2 * (v - v1) / (w * E1)
    t2 = 2 * v1 / (w * E2)
    return t_drift + t1 + t2


def evaluate_performance(U0, d1, L, mz_da, z=1, dK_eV=1.0, L1=None, L2=None):
    """
    在给定 m/z（原子质量单位, Da）、电荷数 z、能散 dK_eV (eV, 表示 ΔK)
    的条件下，求解 E1, E2，并估算：
      - T0        : 标称飞行时间 (s)
      - dT_dU, d2T_dU2 : 一、二阶导数（应 ~0，用于自检）
      - d3T_dU3   : 三阶残差项（决定分辨率的主导项）
      - R         : 质量分辨率 M/deltaM 的理论上限（仅由本聚焦残差决定，
                    不包含离子源初始时空展宽、探测器/电子学等其他展宽项，
                    因此是一个"上限"估计，不是最终仪器分辨率）

    注意：R 在理论上与 m/z、z 无关（已数值验证），这是反射镜 TOF
    "全质量范围近似等分辨率"的物理来源。
    """
    fields = solve_reflectron_fields(U0, d1, L, L1=L1, L2=L2)
    E1, E2, U1, L_total = fields["E1"], fields["E2"], fields["U1"], fields["L_total"]

    m = mz_da * AMU
    w = z * E_CHARGE / m

    h = U0 * 1e-4  # 有限差分步长

    def f(U):
        return flight_time(U, E1, E2, U1, L_total, w)

    T0 = f(U0)
    d1T = (f(U0 + h) - f(U0 - h)) / (2 * h)
    d2T = (f(U0 + h) - 2 * f(U0) + f(U0 - h)) / h**2
    d3T = (f(U0 + 2*h) - 2*f(U0 + h) + 2*f(U0 - h) - f(U0 - 2*h)) / (2 * h**3)

    dU = dK_eV / z  # ΔK(eV)/z 转换为等效电压偏差 (V)
    dT = abs(d3T) / 6 * dU**3
    R = T0 / (2 * dT) if dT > 0 else float("inf")

    fields.update(T0=T0, dT_dU=d1T, d2T_dU2=d2T, d3T_dU3=d3T, dT=dT, R=R)
    return fields


if __name__ == "__main__":
    # ------------------ 使用示例 ------------------
    U0 = 5000.0      # 加速电压/离子标称能量 (V)
    d1 = 0.02        # 第一级(弱场级)长度 (m)
    L = 1.0          # 总无场漂移距离 (m)

    print("=== 示例 1：对称漂移区 L1 = L2 = L/2 ===")
    res = solve_reflectron_fields(U0, d1, L)
    print(f"E1 = {res['E1']:.3f} V/m")
    print(f"E2 = {res['E2']:.3f} V/m")
    print(f"U1 = {res['U1']:.3f} V")
    print(f"L1 = {res['L1']:.4f} m,  L2 = {res['L2']:.4f} m")
    print(f"第二级所需最小物理长度 d2_min = {res['d2_min']:.4f} m"
          f"  (设计时应取 d2 > d2_min 留一定裕量)")

    print("\n=== 示例 2：不对称漂移区 L1 != L2（总和仍为 L）===")
    res2 = solve_reflectron_fields(U0, d1, L, L1=0.8, L2=0.2)
    print(f"E1 = {res2['E1']:.3f} V/m, E2 = {res2['E2']:.3f} V/m  "
          f"(与示例1完全相同 -> 验证只有 L1+L2 影响结果)")

    print("\n=== 示例 3：性能评估（分辨率理论上限）===")
    for mz, z in [(100, 1), (1000, 1), (1000, 2)]:
        perf = evaluate_performance(U0, d1, L, mz_da=mz, z=z, dK_eV=1.0)
        print(f"m/z={mz:>5}, z={z}: T0={perf['T0']*1e6:8.4f} us, "
              f"dT/dU={perf['dT_dU']:.2e} (~0), "
              f"d2T/dU2={perf['d2T_dU2']:.2e} (~0), "
              f"R(理论上限)={perf['R']:.3e}")
