"""Demo 模式：生成合成排行榜数据（无需 Kaggle 凭证），用于零门槛预览全流程。

随机种子固定，每天跑结果一致；全体队伍分数做随机游走，我方队伍在中游起伏。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pandas as pd

TEAM_PREFIX = "team_"
TRACKED_NAME = "我的队伍"


def generate_dates(days: int = 60) -> list[str]:
    today = datetime.now(timezone.utc).date()
    return [(today - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d") for i in range(days)]


def generate_population(n_teams: int = 800) -> list[dict]:
    """返回队伍静态档案：team_id / name / 初始分。top 少而强，中游密集。"""
    rng = random.Random(42)
    teams = []
    for i in range(n_teams):
        # 大师组分布：前 50 队接近满分，之后快速衰减到 0.7 区间
        if i < 50:
            s = 0.995 - i * 0.0012 - rng.random() * 0.002
        else:
            s = 0.985 - (i - 50) * (0.42 / (n_teams - 50)) * (0.9 + rng.random() * 0.2)
        teams.append({"team_id": str(1000 + i), "team": f"{TEAM_PREFIX}{i + 1:04d}", "score": max(s, 0.0)})
    return teams


def generate_snapshots(days: int = 60, n_teams: int = 800, tracked: str = TRACKED_NAME, slug: str = "demo-comp") -> dict[str, pd.DataFrame]:
    """逐日生成排行榜快照：分数随机游走 + 尾部新队伍陆续入场。"""
    rng = random.Random(1337)
    teams = generate_population(n_teams)
    # 追踪队：把中游某队替换成“我的队伍”
    tracked_profile = teams[99]
    tracked_profile["team"] = tracked

    drift = {t["team_id"]: t["score"] for t in teams}
    join_day = {t["team_id"]: rng.randint(0, max(1, days // 3)) for t in teams}  # 前 1/3 周期内陆续“提交上榜”
    join_day[tracked_profile["team_id"]] = min(join_day[tracked_profile["team_id"]], 2)  # 追踪队尽早入榜
    tracked_drift_speed = rng.uniform(0.8, 1.2)

    out: dict[str, pd.DataFrame] = {}
    for day_i, date in enumerate(generate_dates(days)):
        rows = []
        for t in teams:
            tid = t["team_id"]
            if day_i < join_day[tid]:
                continue  # 尚未上榜
            speed = tracked_drift_speed if t["team"] == tracked else rng.uniform(0.2, 2.0)
            drift[tid] += rng.gauss(0, 0.00035) * speed
            drift[tid] = max(0.0, min(1.0, drift[tid]))
            rows.append(
                {
                    "rank": 0,
                    "team_id": tid,
                    "team": t["team"],
                    "score": round(drift[tid], 6),
                }
            )
        df = pd.DataFrame(rows)
        # 名次 = 分数降序；并列分沿用生成顺序（Kaggle 实际为准，这里模拟）
        df = df.sort_values("score", ascending=False, kind="stable").reset_index(drop=True)
        df["rank"] = df.index + 1
        out[date] = df[["rank", "team_id", "team", "score"]]
    return out
