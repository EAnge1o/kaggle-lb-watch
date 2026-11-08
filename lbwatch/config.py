"""配置加载：config.yaml → Settings"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Competition:
    slug: str
    name: str = ""

    def __post_init__(self):
        if not self.name:
            self.name = self.slug


@dataclass
class Settings:
    teams: list[str] = field(default_factory=list)
    competitions: list[Competition] = field(default_factory=list)
    discover: str = "active"       # 自动发现已加入的比赛: off / active(仅未截止) / all(含已结束)
    exclude: list[str] = field(default_factory=list)  # 自动发现时跳过的 slug
    history_top: int = 2000        # 常驻 history.csv 的队伍数上限（我方队伍不受限）
    keep_snapshots: int = 0        # 0=永久保留逐日快照；>0=只保留最近 N 天


def load(path: str | Path | None = None) -> Settings:
    """从 yaml 读取配置。默认找 config.yaml，可用 LBWATCH_CONFIG 环境变量覆盖。"""
    path = Path(path or os.environ.get("LBWATCH_CONFIG", "config.yaml"))
    if not path.exists():
        raise FileNotFoundError(
            f"找不到配置文件 {path}。请复制 config.example.yaml 为 config.yaml 并填写比赛 slug 与队伍名。"
        )
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    teams = [str(t) for t in (raw.get("teams") or []) if str(t).strip()]
    if not teams:
        raise ValueError("config.yaml 中 teams 不能为空：请填写你在排行榜上的队伍名。")

    comps_raw = raw.get("competitions") or []
    comps = []
    for c in comps_raw:
        if isinstance(c, str):
            comps.append(Competition(slug=c))
        else:
            slug = (c.get("slug") or "").strip()
            if not slug:
                raise ValueError(f"competitions 里有一项缺少 slug：{c!r}")
            comps.append(Competition(slug=slug, name=str(c.get("name") or slug)))

    fetch = raw.get("fetch") or {}
    discover = str(fetch.get("discover", "active") or "active").lower()
    if discover not in ("off", "active", "all"):
        raise ValueError(f"discover 只能是 off / active / all，收到：{discover}")

    return Settings(
        teams=teams,
        competitions=comps,
        discover=discover,
        exclude=[str(s) for s in (fetch.get("exclude") or []) if str(s).strip()],
        history_top=int(fetch.get("history_top", 2000)),
        keep_snapshots=int(fetch.get("keep_snapshots", 0)),
    )
