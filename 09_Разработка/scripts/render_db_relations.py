"""Рендер схемы связей БД WeldPassport в PNG."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "WeldPassport_DB_relations.png"

# Позиции таблиц (x, y) — сгруппированы по доменам
POSITIONS: dict[str, tuple[float, float]] = {
    "ПРОЕКТЫ": (1.0, 9.0),
    "ОБЪЕКТЫ": (1.0, 7.5),
    "ИЗОМЕТРИИ": (1.0, 6.0),
    "СТЫКИ": (1.0, 4.5),
    "ФАКТЫ_СВАРКИ": (1.0, 3.0),
    "УЧАСТНИКИ_СВАРКИ": (1.0, 1.5),
    "КОНТРОЛЬ": (3.5, 4.5),
    "РАБОТНИКИ": (6.5, 7.5),
    "СВАРЩИКИ": (6.5, 6.0),
    "ДОКУМЕНТЫ_СВАРЩИКА": (9.5, 6.0),
    "АТТЕСТАЦИИ_СВАРЩИКОВ": (9.5, 4.5),
    "ВНУТРЕННИЕ_ДОПУСКИ_СВАРЩИКОВ": (9.5, 3.0),
    "ДОПУСКИ_К_ОБЪЕКТУ": (6.5, 4.5),
}

# from -> to (направление FK: дочерняя -> родительская)
EDGES: list[tuple[str, str]] = [
    ("ОБЪЕКТЫ", "ПРОЕКТЫ"),
    ("ИЗОМЕТРИИ", "ОБЪЕКТЫ"),
    ("СТЫКИ", "ИЗОМЕТРИИ"),
    ("ФАКТЫ_СВАРКИ", "СТЫКИ"),
    ("КОНТРОЛЬ", "СТЫКИ"),
    ("УЧАСТНИКИ_СВАРКИ", "ФАКТЫ_СВАРКИ"),
    ("УЧАСТНИКИ_СВАРКИ", "РАБОТНИКИ"),
    ("УЧАСТНИКИ_СВАРКИ", "СВАРЩИКИ"),
    ("СВАРЩИКИ", "РАБОТНИКИ"),
    ("ДОКУМЕНТЫ_СВАРЩИКА", "СВАРЩИКИ"),
    ("АТТЕСТАЦИИ_СВАРЩИКОВ", "СВАРЩИКИ"),
    ("АТТЕСТАЦИИ_СВАРЩИКОВ", "ДОКУМЕНТЫ_СВАРЩИКА"),
    ("ВНУТРЕННИЕ_ДОПУСКИ_СВАРЩИКОВ", "СВАРЩИКИ"),
    ("ДОПУСКИ_К_ОБЪЕКТУ", "СВАРЩИКИ"),
    ("ДОПУСКИ_К_ОБЪЕКТУ", "ОБЪЕКТЫ"),
    ("ДОПУСКИ_К_ОБЪЕКТУ", "ДОКУМЕНТЫ_СВАРЩИКА"),
]

BOX_W = 2.6
BOX_H = 0.55


def box_center(name: str) -> tuple[float, float]:
    x, y = POSITIONS[name]
    return x + BOX_W / 2, y + BOX_H / 2


def draw_box(ax, name: str, color: str) -> None:
    x, y = POSITIONS[name]
    box = FancyBboxPatch(
        (x, y),
        BOX_W,
        BOX_H,
        boxstyle="round,pad=0.03,rounding_size=0.08",
        linewidth=1.2,
        edgecolor="#334155",
        facecolor=color,
    )
    ax.add_patch(box)
    label = name.replace("_", "\n") if len(name) > 18 else name
    ax.text(
        x + BOX_W / 2,
        y + BOX_H / 2,
        label,
        ha="center",
        va="center",
        fontsize=8,
        fontweight="bold",
        color="#0f172a",
    )


def draw_arrow(ax, child: str, parent: str) -> None:
    cx, cy = box_center(child)
    px, py = box_center(parent)
    dx, dy = px - cx, py - cy
    dist = (dx**2 + dy**2) ** 0.5 or 1.0
    shrink = 0.35
    start = (cx + dx / dist * shrink, cy + dy / dist * shrink)
    end = (px - dx / dist * shrink, py - dy / dist * shrink)
    arrow = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=1.0,
        color="#64748b",
        connectionstyle="arc3,rad=0.08",
    )
    ax.add_patch(arrow)


def main() -> None:
    colors = {
        "production": "#dbeafe",
        "workers": "#dcfce7",
        "permits": "#fef3c7",
        "control": "#fce7f3",
    }
    table_colors = {
        "ПРОЕКТЫ": colors["production"],
        "ОБЪЕКТЫ": colors["production"],
        "ИЗОМЕТРИИ": colors["production"],
        "СТЫКИ": colors["production"],
        "ФАКТЫ_СВАРКИ": colors["production"],
        "УЧАСТНИКИ_СВАРКИ": colors["production"],
        "КОНТРОЛЬ": colors["control"],
        "РАБОТНИКИ": colors["workers"],
        "СВАРЩИКИ": colors["workers"],
        "ДОКУМЕНТЫ_СВАРЩИКА": colors["permits"],
        "АТТЕСТАЦИИ_СВАРЩИКОВ": colors["permits"],
        "ВНУТРЕННИЕ_ДОПУСКИ_СВАРЩИКОВ": colors["permits"],
        "ДОПУСКИ_К_ОБЪЕКТУ": colors["permits"],
    }

    fig, ax = plt.subplots(figsize=(14, 10), dpi=150)
    ax.set_xlim(0, 12.5)
    ax.set_ylim(0.5, 10.2)
    ax.axis("off")
    ax.set_title(
        "WeldPassport — связи таблиц PostgreSQL (схема test)",
        fontsize=14,
        fontweight="bold",
        pad=16,
        color="#0f172a",
    )

    for child, parent in EDGES:
        draw_arrow(ax, child, parent)

    for name in POSITIONS:
        draw_box(ax, name, table_colors[name])

    legend_items = [
        ("Производство", colors["production"]),
        ("Персонал", colors["workers"]),
        ("Допуски и документы", colors["permits"]),
        ("Контроль", colors["control"]),
    ]
    for i, (label, color) in enumerate(legend_items):
        ax.add_patch(
            FancyBboxPatch(
                (0.3, 0.65 - i * 0.35),
                0.35,
                0.22,
                boxstyle="round,pad=0.02",
                facecolor=color,
                edgecolor="#334155",
                linewidth=0.8,
                transform=ax.transAxes,
                clip_on=False,
            )
        )
        ax.text(
            0.72,
            0.76 - i * 0.35,
            label,
            transform=ax.transAxes,
            fontsize=9,
            va="center",
            color="#334155",
        )

    ax.text(
        0.5,
        0.02,
        "Стрелка: дочерняя таблица → родительская (FK)",
        transform=ax.transAxes,
        ha="center",
        fontsize=9,
        color="#64748b",
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Сохранено: {OUT}")


if __name__ == "__main__":
    main()
