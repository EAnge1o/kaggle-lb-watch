"""通过 Kaggle 官方 SDK（kagglesdk）分页拉取 Public LB 全量数据。

认证支持（kaggle>=2.2.5）：
  - KAGGLE_API_TOKEN 环境变量（KGAT_ 开头的新式 token，推荐的 GitHub Actions 方式）
  - KAGGLE_USERNAME + KAGGLE_KEY（Legacy API key）
  - ~/.kaggle/access_token 文件 / ~/.kaggle/kaggle.json / kaggle auth login 缓存

已知事实（2026-11 实测）：get_leaderboard 每页服务端上限 200 条，需 page_token 翻页；
KaggleApi.competition_leaderboard_view 会丢弃 next_page_token，所以这里直接走 sdk client。

统一输出 DataFrame，列: rank(int) / team_id(str) / team(str) / score(float)。
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

PAGE_SIZE = 200     # 服务器硬上限
MAX_PAGES = 500     # 防呆：200*500 = 10 万队足够覆盖任何比赛
PAGE_SLEEP = 0.75   # 每页间隔（秒）：防 429 Too Many Requests
RETRY_BACKOFF = (15, 45, 120)   # 429/5xx 时的指数退避重试


def _credentials_available() -> bool:
    k = Path.home() / ".kaggle"
    return bool(
        os.environ.get("KAGGLE_API_TOKEN")
        or (os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"))
        or (k / "access_token").exists()
        or (k / "kaggle.json").exists()
    )


def _make_api():
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError as e:
        raise RuntimeError("kaggle 库未安装：pip install -r requirements.txt") from e

    if not _credentials_available():
        raise RuntimeError(
            "找不到 Kaggle 凭证。GitHub Actions 请配置 secret KAGGLE_API_TOKEN"
            "（kaggle.com/settings/api → API → Generate New Token）；"
            "本地可设置环境变量 KAGGLE_API_TOKEN，或把 raw token 存到 ~/.kaggle/access_token，"
            "或使用 Legacy 的 ~/.kaggle/kaggle.json（username+key）。"
        )

    api = KaggleApi()
    try:
        api.authenticate()  # 2.x 认证链：token → legacy key → OAuth → 匿名(按命令允许)
    except SystemExit as e:
        raise RuntimeError("Kaggle 认证失败（凭证无效或过期），请重新生成 token。") from e
    except Exception as e:
        raise RuntimeError(f"Kaggle 认证出错：{e}") from e
    return api


def fetch_leaderboard(slug: str) -> pd.DataFrame:
    from kagglesdk.competitions.types.competition_api_service import ApiGetLeaderboardRequest

    api = _make_api()

    rows: list = []
    token: str | None = None
    pages = 0
    while pages < MAX_PAGES:
        pages += 1
        for attempt, wait in enumerate((0,) + RETRY_BACKOFF):
            if wait:
                print(f"⚠️ {slug} 被 Kaggle 限流/服务异常，退避 {wait}s 后重试（补试 {attempt}/{len(RETRY_BACKOFF)}）")
                time.sleep(wait)
            with api.build_kaggle_client() as kaggle:
                req = ApiGetLeaderboardRequest()
                req.competition_name = slug
                req.page_size = PAGE_SIZE
                req.page_token = token or ""
                try:
                    resp = kaggle.competitions.competition_api_client.get_leaderboard(req)
                    break
                except Exception as e:
                    msg = str(e)
                    transient = "429" in msg or "Too Many Requests" in msg or "50" in msg[:4]
                    if transient:
                        if attempt < len(RETRY_BACKOFF):
                            continue
                        raise RuntimeError(
                            f"拉取排行榜失败（{slug}）：Kaggle API 已重试 4 次仍被限流/服务异常（{msg[:160]}）。"
                            "明天会自动重试；如持续出现请反馈。"
                        ) from e
                    raise RuntimeError(
                        f"拉取排行榜失败（{slug}）：{e}\n常见原因：slug 拼错（kaggle.com/competitions/ 后面那串）；"
                        "比赛已结束且公开榜关闭；token 有效期已过。"
                    ) from e
        page = resp.submissions or []
        rows.extend(page)
        token = resp.next_page_token
        if not token or not page:
            break
        time.sleep(PAGE_SLEEP)
    else:
        raise RuntimeError(f"{slug} 分页超过 {MAX_PAGES} 页仍未取完，异常终止。")

    if not rows:
        raise RuntimeError(f"排行榜为空（{slug}）：确认 slug 正确且比赛仍有公开 LB。")

    out = pd.DataFrame(
        {
            "rank": range(1, len(rows) + 1),  # 返回顺序即官方名次，不做本地重排
            "team_id": [str(s.team_id) for s in rows],
            "team": [str(s.team_name) for s in rows],
            "score": [float(s.score) if s.score not in (None, "") else float("nan") for s in rows],
        }
    )
    return out


def list_entered_competitions() -> list[dict]:
    """我已加入的比赛（服务端过滤 group=entered，一次请求）。

    返回 [{slug, title, deadline}]；deadline 为 None 或已解析的 datetime（可能无时区，仅用于日级过滤）。
    """
    from kagglesdk.competitions.types.competition_api_service import (
        ApiListCompetitionsRequest,
        CompetitionListTab,
    )

    api = _make_api()
    with api.build_kaggle_client() as kaggle:
        req = ApiListCompetitionsRequest()
        req.group = CompetitionListTab.COMPETITION_LIST_TAB_ENTERED
        req.page_size = 100
        try:
            resp = kaggle.competitions.competition_api_client.list_competitions(req)
        except Exception as e:
            raise RuntimeError(f"读取「已加入的比赛」列表失败：{e}") from e

    out: list[dict] = []
    for it in resp.competitions or []:
        ref = (it.ref or "").strip()  # ref 可能是完整 URL
        slug = ref.rstrip("/").split("/")[-1] if ref else ""
        if not slug:
            continue
        dl = it.deadline
        if isinstance(dl, str):
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dl = datetime.strptime(dl, fmt)
                    break
                except ValueError:
                    continue
        out.append({"slug": slug, "title": (it.title or slug), "deadline": dl})
    return out
