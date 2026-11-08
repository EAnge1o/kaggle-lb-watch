"""README 动态区域：把所有比赛的最新名次/变化汇总成表格 + 折叠式卡片墙。

只改 <!-- lbwatch:start --> 与 <!-- lbwatch:end --> 之间的内容，用户其他内容不动。
每次 cmd_run / cmd_card 自动重写。新比赛（数据目录出现）自动上首页。
"""

from __future__ import annotations

import json
from pathlib import Path

START = "<!-- lbwatch:start -->"
END = "<!-- lbwatch:end -->"


def _delta_text(rc) -> str:
    if rc is None or rc == 0:
        return "—"
    return f"↑{rc}" if rc > 0 else f"↓{-rc}"


def _collect(root: Path):
    """返回 (tracked_rows, untracked_rows, cards)。tracked 行按名次升序。"""
    data = root / "data"
    tracked: list[dict] = []
    untracked: list[dict] = []
    cards: list[str] = []

    if not data.exists():
        return tracked, untracked, cards

    for d in sorted(data.iterdir()):
        if not d.is_dir():
            continue
        ljp = d / "latest.json"
        if not ljp.exists():
            continue
        try:
            latest = json.loads(ljp.read_text(encoding="utf-8"))
        except Exception:
            continue
        slug = d.name
        name = latest.get("name") or slug
        url = f"https://www.kaggle.com/competitions/{slug}/leaderboard"
        date_short = (latest.get("date") or "")[5:]
        tracked_list = latest.get("tracked") or []
        if tracked_list:
            t = tracked_list[0]
            tracked.append(
                {
                    "name": name,
                    "url": url,
                    "rank": f"#{t.get('rank', '?')} / {latest.get('total', '?')}",
                    "delta": _delta_text(t.get("rank_change")),
                    "score": f"{t.get('score', 0):.5f}",
                    "date": date_short,
                    "_rank": t.get("rank") or 10**9,
                }
            )
        else:
            untracked.append(
                {
                    "name": name,
                    "url": url,
                    "rank": "—",
                    "delta": "—",
                    "score": "—",
                    "date": date_short,
                    "_rank": 10**9,
                }
            )
        if (d / "card.svg").exists():
            cards.append(f"![{name}](data/{slug}/card.svg)")

    tracked.sort(key=lambda r: r["_rank"])
    untracked.sort(key=lambda r: r["name"])
    return tracked, untracked, cards


def render(root: Path, readme_path: Path) -> str:
    tracked, untracked, cards = _collect(root)

    lines = ["### 📋 盯着的比赛", ""]
    if tracked or untracked:
        lines.append("| 比赛 | 我的名次 | 较上次 | 分数 | 更新 |")
        lines.append("|---|---|---|---|---|")
        for r in tracked + untracked:
            lines.append(
                f"| [{r['name']}]({r['url']}) | {r['rank']} | {r['delta']} | {r['score']} | {r['date']} |"
            )
    else:
        lines.append("（还没有任何比赛数据：跑一次 `python -m lbwatch run` 后这里会长出来）")

    if cards:
        lines += ["", "<details>", f"<summary>🖼 全部排名卡片（{len(cards)} 张）</summary>", ""]
        lines += cards + ["", "</details>"]

    block = START + "\n" + "\n".join(lines) + "\n" + END

    if readme_path.exists():
        text = readme_path.read_text(encoding="utf-8")
        if START in text and END in text:
            head, rest = text.split(START, 1)
            _, tail = rest.split(END, 1)
            new_text = head + block + tail
        else:
            new_text = text.rstrip() + "\n\n" + block + "\n"
    else:
        new_text = block + "\n"

    readme_path.write_text(new_text, encoding="utf-8")
    return new_text, len(tracked) + len(untracked)
