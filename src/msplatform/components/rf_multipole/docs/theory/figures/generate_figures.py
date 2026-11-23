"""Regenerate reviewed figures used by the multipole theory documents."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from scipy.optimize import brentq
from scipy.special import mathieu_a, mathieu_b


OUTPUT_DIR = Path(__file__).resolve().parent


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Microsoft YaHei",
                "SimHei",
                "Noto Sans CJK SC",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "axes.facecolor": "#fbfcfe",
            "axes.edgecolor": "#4b5563",
            "axes.grid": True,
            "grid.alpha": 0.22,
        }
    )


def save(fig: plt.Figure, filename: str) -> None:
    fig.savefig(OUTPUT_DIR / filename, dpi=220, bbox_inches="tight")
    plt.close(fig)


def generate_pseudopotential_scaling() -> None:
    rho = np.linspace(0.0, 1.0, 600)
    fig, ax = plt.subplots(figsize=(8.4, 5.3))
    curves = [
        (2, "四极杆 n=2", "#2563eb"),
        (3, "六极杆 n=3", "#0f9d76"),
        (4, "八极杆 n=4", "#d97706"),
    ]
    for n, label, color in curves:
        ax.plot(rho, rho ** (2 * n - 2), lw=2.6, color=color, label=label)

    ax.set(
        xlabel=r"归一化半径 $r/r_0$",
        ylabel=r"归一化 RF 伪势 $\Psi(r)/\Psi(r_0)$",
        xlim=(0, 1),
        ylim=(0, 1.03),
        title="理想多极杆 RF 伪势的径向尺度",
    )
    ax.legend(loc="upper left", frameon=True)
    ax.text(
        0.04,
        0.59,
        "高阶多极杆具有更宽的低场核心；\n"
        "实际接受度仍须由有限长度、入口相空间和轨迹统计验证。",
        transform=ax.transAxes,
        fontsize=10.5,
        va="top",
        bbox={"boxstyle": "round,pad=0.45", "fc": "white", "ec": "#94a3b8", "alpha": 0.95},
    )
    fig.tight_layout()
    save(fig, "multipole-pseudopotential-scaling.png")


def generate_scanline_passband() -> None:
    ratio = 0.1665830308
    slope = 2.0 * ratio

    def x_boundary(q: np.ndarray | float) -> np.ndarray | float:
        return mathieu_b(1, q)

    def y_boundary(q: np.ndarray | float) -> np.ndarray | float:
        return -mathieu_a(0, q)

    q_in = brentq(lambda q: slope * q - y_boundary(q), 0.60, 0.705)
    q_out = brentq(lambda q: slope * q - x_boundary(q), 0.705, 0.73)
    q = np.linspace(0.61, 0.728, 800)
    bx = x_boundary(q)
    by = y_boundary(q)
    upper = np.minimum(bx, by)
    scanline = slope * q

    fig, ax = plt.subplots(figsize=(9.2, 5.7))
    ax.fill_between(q, 0, upper, color="#dbeafe", alpha=0.72, label="第一联合稳定区（a ≥ 0）")
    ax.plot(q, bx, color="#0f9d9a", lw=2.5, label=r"x 方向稳定边界 $a=b_1(q)$")
    ax.plot(q, by, color="#e07a1f", lw=2.5, label=r"y 方向稳定边界 $a=-a_0(q)$")
    ax.plot(q, scanline, color="#111827", lw=2.3, label=rf"扫描线 $a=2(U/V)q$，$U/V={ratio:.6f}$")
    ax.axvline(q_in, color="#475569", lw=1.7, ls="--")
    ax.axvline(q_out, color="#475569", lw=1.7, ls="--")
    ax.scatter([q_in, q_out], [slope * q_in, slope * q_out], color="#7c3aed", s=48, zorder=6)
    ax.annotate(
        rf"$q_{{in}}={q_in:.6f}$",
        (q_in, slope * q_in),
        xytext=(-64, -39),
        textcoords="offset points",
        arrowprops={"arrowstyle": "->", "color": "#475569"},
    )
    ax.annotate(
        rf"$q_{{out}}={q_out:.6f}$",
        (q_out, slope * q_out),
        xytext=(18, -38),
        textcoords="offset points",
        arrowprops={"arrowstyle": "->", "color": "#475569"},
    )
    dashed = Line2D([0], [0], color="#475569", lw=1.7, ls="--", label="通带入口/出口 q 位置")
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles + [dashed], labels + [dashed.get_label()], loc="lower left", fontsize=9, framealpha=0.96)
    ax.set(
        xlabel="Mathieu 参数 q",
        ylabel="Mathieu 参数 a",
        xlim=(q.min(), q.max()),
        ylim=(0.198, 0.248),
        title="固定 U/V 扫描线与四极杆第一联合稳定区通带",
    )
    fig.tight_layout()
    save(fig, "quadrupole-scanline-passband.png")


def _box(ax: plt.Axes, xy: tuple[float, float], text: str, color: str) -> None:
    x, y = xy
    patch = FancyBboxPatch(
        (x - 0.105, y - 0.055),
        0.21,
        0.11,
        boxstyle="round,pad=0.012,rounding_size=0.02",
        facecolor=color,
        edgecolor="#334155",
        linewidth=1.25,
    )
    ax.add_patch(patch)
    ax.text(x, y, text, ha="center", va="center", fontsize=10.5, weight="bold")


def _arrow(ax: plt.Axes, start: tuple[float, float], end: tuple[float, float], **kwargs: object) -> None:
    options = {"arrowstyle": "-|>", "mutation_scale": 14, "lw": 1.6, "color": "#475569"}
    options.update(kwargs)
    ax.add_patch(FancyArrowPatch(start, end, **options))


def generate_engineering_loop() -> None:
    fig, ax = plt.subplots(figsize=(11.3, 6.1))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    positions = {
        "需求": (0.14, 0.78),
        "规格编译": (0.38, 0.78),
        "候选生成": (0.62, 0.78),
        "独立场求解": (0.86, 0.78),
        "轨迹与碰撞": (0.86, 0.47),
        "诊断归因": (0.62, 0.47),
        "参数优化": (0.38, 0.47),
        "验收门禁": (0.14, 0.47),
        "正式发布": (0.14, 0.17),
    }
    colors = {
        "需求": "#e0f2fe",
        "规格编译": "#e0f2fe",
        "候选生成": "#ede9fe",
        "独立场求解": "#dcfce7",
        "轨迹与碰撞": "#dcfce7",
        "诊断归因": "#fef3c7",
        "参数优化": "#fef3c7",
        "验收门禁": "#fee2e2",
        "正式发布": "#d1fae5",
    }
    for name, position in positions.items():
        _box(ax, position, name, colors[name])

    chain = ["需求", "规格编译", "候选生成", "独立场求解"]
    for left, right in zip(chain, chain[1:]):
        _arrow(ax, (positions[left][0] + 0.11, positions[left][1]), (positions[right][0] - 0.11, positions[right][1]))
    _arrow(ax, (0.86, 0.72), (0.86, 0.53))
    for right, left in [("轨迹与碰撞", "诊断归因"), ("诊断归因", "参数优化"), ("参数优化", "验收门禁")]:
        _arrow(ax, (positions[right][0] - 0.11, positions[right][1]), (positions[left][0] + 0.11, positions[left][1]))
    _arrow(ax, (0.14, 0.41), (0.14, 0.23), color="#15803d")
    ax.text(0.16, 0.33, "通过", color="#15803d", fontsize=10, va="center")

    _arrow(
        ax,
        (0.245, 0.47),
        (0.62, 0.71),
        connectionstyle="arc3,rad=-0.36",
        color="#b91c1c",
    )
    ax.text(0.43, 0.63, "失败：返回诊断/候选", color="#b91c1c", fontsize=10, ha="center", rotation=15)
    ax.set_title("自然语言驱动的多级杆设计—验证—发布闭环", fontsize=15, weight="bold", pad=12)
    ax.text(
        0.98,
        0.04,
        "只有验收通过的候选才能形成正式产物",
        ha="right",
        va="bottom",
        fontsize=10,
        color="#475569",
    )
    save(fig, "generative-engineering-loop.png")


def main() -> None:
    configure_style()
    generate_pseudopotential_scaling()
    generate_scanline_passband()
    generate_engineering_loop()


if __name__ == "__main__":
    main()
