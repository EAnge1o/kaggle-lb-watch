"""SVG 排名卡片：从 history.csv + latest.json 生成暗色主题卡片（致敬 kaggle-card）。

输出 data/<slug>/card.svg，README 里用 ![card](data/<slug>/card.svg) 嵌入，
每次 Actions commit 后自动更新。纯手工拼 SVG 字符串，无第三方渲染依赖。
"""

from __future__ import annotations

from datetime import datetime
from xml.sax.saxutils import escape

W, H = 720, 210
BLUE = "#008ABC"
GREEN = "#3fb950"
RED = "#f85149"
GRAY = "#8b949e"
BORDER = "#30363d"
BG = "#0d1117"


def _escape(s: str) -> str:
    return escape(str(s))


def _spark_points(dates: list[str], ranks: list[int], x0: float, y0: float, w: float, h: float):
    """名次越靠前 = 越好 = 越高。rank 轴反转。"""
    n = len(dates)
    if n == 0:
        return "", ""
    rmin, rmax = min(ranks), max(ranks)
    if rmax == rmin:
        rmax = rmin + 1
    dmin = datetime.strptime(dates[0], "%Y-%m-%d")
    dmax = datetime.strptime(dates[-1], "%Y-%m-%d")
    span = max((dmax - dmin).days, 1)

    pts: list[str] = []
    area = ""
    for d, r in zip(dates, ranks):
        dd = datetime.strptime(d, "%Y-%m-%d")
        x = x0 + w * (dd - dmin).days / span
        y = y0 + h * (1 - (rmax - r) / (rmax - rmin))
        pts.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(pts)
    if len(pts) > 1:
        area = f"M{pts[0]} L" + " L".join(pts[1:]) + f" L{pts[-1]} L{pts[0].split(',')[0]},{y0 + h} Z"
    return polyline, area


def render_card(comp_name: str, latest: dict, history_rows: list[dict], out_path) -> str:
    """history_rows: 已排序的 [{date, rank, score}]（我方队伍每日一行）。"""
    tracked = (latest.get("tracked") or [{}])[0]
    rank = tracked.get("rank", 0)
    total = latest.get("total", 0)
    score = tracked.get("score", 0.0)
    rc = tracked.get("rank_change", 0)
    date = latest.get("date", "")

    if not tracked.get("first_seen") and rc:
        arrow = "↑" if rc > 0 else "↓"
        color = GREEN if rc > 0 else RED
        delta = f'<text x="250" y="120" font-size="20" fill="{color}">{arrow}{abs(rc)}</text>'
    elif tracked.get("first_seen"):
        delta = f'<text x="250" y="120" font-size="16" fill="{GRAY}">首次记录</text>'
    else:
        delta = f'<text x="250" y="120" font-size="20" fill="{GRAY}">— 持平</text>'

    dates = [r["date"] for r in history_rows]
    ranks = [int(r["rank"]) for r in history_rows]
    polyline, area = _spark_points(dates, ranks, 350, 46, 330, 108)

    best_rank = min(ranks) if ranks else rank
    best_date = ""
    if ranks:
        i = ranks.index(best_rank)
        best_date = dates[i]

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="12" fill="{BG}" stroke="{BORDER}"/>
  <text x="28" y="38" font-family="Segoe UI,sans-serif" font-size="14" fill="#58a6ff">{_escape(comp_name)}
    <tspan fill="{GRAY}" font-size="12"> · lbwatch</tspan>
  </text>
  <text x="692" y="38" text-anchor="end" font-family="Segoe UI,sans-serif" font-size="12" fill="{GRAY}">更新 {_escape(date)}</text>

  <text x="28" y="100" font-family="Segoe UI,sans-serif" font-size="46" font-weight="700" fill="#e6edf3">#{rank}</text>
  <text x="128" y="100" font-family="Segoe UI,sans-serif" font-size="16" fill="{GRAY}">/ {total} 队</text>
  <text x="28" y="136" font-family="Segoe UI,sans-serif" font-size="15" fill="{BLUE}">score {score:.5f}</text>
  {delta}

  <line x1="350" y1="40" x2="692" y2="40" stroke="{BORDER}" stroke-dasharray="3 3"/>
  <line x1="350" y1="160" x2="692" y2="160" stroke="{BORDER}" stroke-dasharray="3 3"/>
  {f'<path d="{area}" fill="{BLUE}" opacity="0.15"/>' if area else ''}
  {f'<polyline points="{polyline}" fill="none" stroke="{BLUE}" stroke-width="2"/>' if polyline else ''}
  {f'<circle cx="{polyline.split()[-1].split(",")[0]}" cy="{polyline.split()[-1].split(",")[1]}" r="3.5" fill="{BLUE}"/>' if polyline else ''}

  <text x="350" y="184" font-family="Segoe UI,sans-serif" font-size="11" fill="{GRAY}">名次曲线（越高越好，最佳 #{best_rank}{("，出现在 " + best_date) if best_date else ""}）</text>
  <text x="692" y="184" text-anchor="end" font-family="Segoe UI,sans-serif" font-size="11" fill="{GRAY}">lbwatch · 数据来自 Public LB 快照</text>
</svg>'''

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg, encoding="utf-8")
    return svg
