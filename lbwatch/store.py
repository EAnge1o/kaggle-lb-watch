"""数据仓：快照归档 + 每日 history 幂等 upsert + 裁剪。

data/<slug>/
├── history.csv          长表: date, rank, team_id, team, score（每日: 当日 topN ∪ 我方队伍）
├── snapshot/YYYY-MM-DD.csv   当日全量快照（同日重跑覆盖，幂等）
└── latest.json          最新一次记录的元数据（我方名次/变化，卡片与仪表盘共用）
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HISTORY_COLS = ["date", "rank", "team_id", "team", "score"]


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def comp_dir(root: Path, slug: str) -> Path:
    return Path(root) / "data" / slug


# ---------- snapshot ----------

def save_snapshot(root: Path, slug: str, date: str, lb: pd.DataFrame) -> Path:
    d = comp_dir(root, slug) / "snapshot"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{date}.csv"
    lb.to_csv(p, index=False)
    return p


def prune_snapshots(root: Path, slug: str, keep_days: int) -> int:
    """keep_days<=0 表示永久保留。返回删除的文件数。"""
    if keep_days <= 0:
        return 0
    d = comp_dir(root, slug) / "snapshot"
    if not d.exists():
        return 0
    removed = 0
    today = datetime.now(timezone.utc).date()
    for f in sorted(d.glob("*.csv")):
        try:
            day = datetime.strptime(f.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if (today - day).days > keep_days:
            f.unlink()
            removed += 1
    return removed


# ---------- history ----------

def load_history(root: Path, slug: str) -> pd.DataFrame:
    p = comp_dir(root, slug) / "history.csv"
    if not p.exists():
        return pd.DataFrame(columns=HISTORY_COLS)
    return pd.read_csv(p, dtype={"date": str, "rank": "Int64", "team_id": str, "team": str, "score": float})


def upsert_history(
    root: Path,
    slug: str,
    date: str,
    lb: pd.DataFrame,
    history_top: int,
    tracked_ids: list[str],
) -> Path:
    """按天幂等写入：同一天重跑先删旧行再做当日快照的 topN ∪ 我方队伍。"""
    lb = lb.copy()
    lb["team_id"] = lb["team_id"].astype(str)
    keep = lb["rank"] <= history_top
    if tracked_ids:
        keep = keep | lb["team_id"].isin(set(map(str, tracked_ids)))
    today = lb[keep].assign(date=date)[HISTORY_COLS]

    hist = load_history(root, slug)
    hist = hist[hist["date"] != date]
    merged = today if hist.empty else (
        pd.concat([hist, today], ignore_index=True)
        .sort_values(["date", "rank"], kind="stable")
        .reset_index(drop=True)
    )
    p = comp_dir(root, slug) / "history.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(p, index=False)
    return p


# ---------- latest.json ----------

def save_latest(root: Path, slug: str, payload: dict) -> Path:
    p = comp_dir(root, slug) / "latest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return p


def load_latest(root: Path, slug: str) -> dict | None:
    p = comp_dir(root, slug) / "latest.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)
