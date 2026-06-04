from __future__ import annotations

from pathlib import Path
from textwrap import wrap

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "qiming-architecture.svg"


mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
        "svg.fonttype": "none",
        "font.size": 8,
        "axes.spines.right": False,
        "axes.spines.top": False,
    }
)


COLORS = {
    "ink": "#17212b",
    "muted": "#5f6f7a",
    "panel": "#ffffff",
    "line": "#7c8a96",
    "okx": "#17212b",
    "market": "#d8edf7",
    "research": "#dff1df",
    "live": "#ffe6d6",
    "operator": "#eadff5",
    "storage": "#f4f7fa",
    "danger": "#cf5d48",
    "safe": "#2d8a62",
}


def add_box(ax, xy, wh, title, body, *, facecolor, edgecolor="#d2dce3", title_color=None):
    x, y = xy
    w, h = wh
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.012,rounding_size=0.025",
        linewidth=1.1,
        edgecolor=edgecolor,
        facecolor=facecolor,
    )
    ax.add_patch(patch)
    ax.text(x + 0.018, y + h - 0.045, title, ha="left", va="top", fontsize=10, weight="bold", color=title_color or COLORS["ink"])
    wrapped = []
    for line in body:
        wrapped.extend(wrap(line, width=34) or [""])
    for idx, line in enumerate(wrapped[:7]):
        ax.text(x + 0.018, y + h - 0.085 - idx * 0.028, line, ha="left", va="top", fontsize=7.2, color=COLORS["muted"])
    return patch


def arrow(ax, start, end, *, color=None, dashed=False, label=None):
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=11,
        linewidth=1.35,
        color=color or COLORS["line"],
        linestyle=(0, (4, 3)) if dashed else "solid",
        shrinkA=5,
        shrinkB=5,
    )
    ax.add_patch(patch)
    if label:
        mx = (start[0] + end[0]) / 2
        my = (start[1] + end[1]) / 2
        ax.text(mx, my + 0.018, label, ha="center", va="bottom", fontsize=6.7, color=color or COLORS["line"])


def main() -> None:
    fig, ax = plt.subplots(figsize=(13.5, 8), dpi=180)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("#fbfcfd")
    ax.set_facecolor("#fbfcfd")

    ax.text(0.04, 0.95, "Qiming Quant Architecture", fontsize=22, weight="bold", color=COLORS["ink"], va="top")
    ax.text(
        0.04,
        0.912,
        "Local-first OKX perpetual system: read-only live state first, fail-closed safety gates before any execution.",
        fontsize=9.5,
        color=COLORS["muted"],
        va="top",
    )

    add_box(
        ax,
        (0.04, 0.60),
        (0.18, 0.22),
        "OKX REST / WebSocket",
        [
            "Historical candles, instruments, funding, mark/index prices.",
            "Private account reads for balances, positions, orders and fills.",
        ],
        facecolor="#eff4f8",
        edgecolor="#b9c7d3",
    )
    add_box(
        ax,
        (0.04, 0.28),
        (0.18, 0.22),
        "Operator Workstation",
        [
            "Modular CLI entrypoint.",
            "No automatic real-money trading command is exposed.",
        ],
        facecolor="#f7f1fb",
        edgecolor="#d7c2e8",
    )

    add_box(
        ax,
        (0.28, 0.68),
        (0.20, 0.16),
        "AppServices",
        [
            "Single service container for command modules.",
            "Gateway, repositories, risk settings, runtime logger.",
        ],
        facecolor=COLORS["storage"],
    )
    add_box(
        ax,
        (0.28, 0.47),
        (0.20, 0.16),
        "Modular CLI",
        [
            "market_data, research, live_ops, operator.",
            "Handlers orchestrate services and preserve stable output.",
        ],
        facecolor="#ffffff",
    )
    add_box(
        ax,
        (0.28, 0.20),
        (0.20, 0.18),
        "Local Audit Layer",
        [
            "SQLite repositories for candles, instruments, live state and simulation journal.",
            "Runtime JSONL event log.",
        ],
        facecolor=COLORS["storage"],
    )

    add_box(
        ax,
        (0.55, 0.70),
        (0.18, 0.17),
        "Market Data",
        [
            "Sync, range repair, aggregation.",
            "Funding, mark and index price snapshots.",
        ],
        facecolor=COLORS["market"],
    )
    add_box(
        ax,
        (0.55, 0.48),
        (0.18, 0.17),
        "Research / Simulation",
        [
            "Data gate, strategy factory, backtest reports.",
            "Simulation journal replaces paper-era naming.",
        ],
        facecolor=COLORS["research"],
    )
    add_box(
        ax,
        (0.55, 0.25),
        (0.18, 0.17),
        "Read-only Live Bot",
        [
            "live-bot-once syncs public/private state.",
            "Persists snapshots and records gate status.",
        ],
        facecolor=COLORS["live"],
    )

    add_box(
        ax,
        (0.79, 0.60),
        (0.17, 0.18),
        "Safety Boundary",
        [
            "Emergency pause, equity risk, mark freshness, reconciliation.",
            "TradingGateService is fail-closed.",
        ],
        facecolor="#fff1ed",
        edgecolor="#efb5a8",
    )
    add_box(
        ax,
        (0.79, 0.34),
        (0.17, 0.18),
        "Gated Execution Service",
        [
            "Order execution and cancellation service exists internally.",
            "No automatic live executor is wired to the CLI yet.",
        ],
        facecolor="#fff7f4",
        edgecolor="#efb5a8",
    )
    add_box(
        ax,
        (0.79, 0.11),
        (0.17, 0.15),
        "Next Live Roadmap",
        [
            "Read-only loop -> dry-run intents -> OKX simulated trading -> small live pilot.",
        ],
        facecolor="#f7fbf7",
        edgecolor="#bedcc6",
    )

    arrow(ax, (0.22, 0.71), (0.28, 0.76), label="REST/WS adapters")
    arrow(ax, (0.22, 0.39), (0.28, 0.55), label="commands")
    arrow(ax, (0.38, 0.68), (0.38, 0.63))
    arrow(ax, (0.48, 0.55), (0.55, 0.78), label="sync")
    arrow(ax, (0.48, 0.55), (0.55, 0.56), label="research")
    arrow(ax, (0.48, 0.55), (0.55, 0.34), label="live ops")
    arrow(ax, (0.64, 0.70), (0.38, 0.38), dashed=True, label="persist")
    arrow(ax, (0.64, 0.48), (0.38, 0.38), dashed=True)
    arrow(ax, (0.64, 0.25), (0.38, 0.38), dashed=True)
    arrow(ax, (0.73, 0.34), (0.79, 0.69), color=COLORS["safe"], label="evaluate gate")
    arrow(ax, (0.875, 0.60), (0.875, 0.52), color=COLORS["danger"], label="blocked by default")
    arrow(ax, (0.875, 0.34), (0.875, 0.26), color=COLORS["danger"], dashed=True)

    ax.text(
        0.50,
        0.055,
        "Figure contract: schematic-led composite. Evidence chain: OKX reads -> modular CLI/AppServices -> local data/research/live state -> fail-closed gate -> deferred execution roadmap.",
        ha="center",
        va="bottom",
        fontsize=7,
        color=COLORS["muted"],
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, bbox_inches="tight", format="svg")
    plt.close(fig)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
