"""lbwatch Streamlit 仪表盘（单页瘦身版）。

本地运行:  streamlit run app/main.py
Streamlit Cloud 部署: 选本仓库, main file = app/main.py（数据直接读仓库里的 data/）。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

st.set_page_config(page_title="lbwatch", page_icon="🏆", layout="wide")

st.title("🏆 lbwatch · Kaggle 排行榜监视器")
st.caption("数据来自每日 Public LB 快照（data/ 目录），Actions 每天自动更新")


def comp_slugs() -> list[str]:
    if not DATA.exists():
        return []
    return sorted(
        d.name for d in DATA.iterdir()
        if d.is_dir() and (d / "history.csv").exists()
    )


def load_df(slug: str) -> tuple[pd.DataFrame | None, dict | None]:
    hist_p = DATA / slug / "history.csv"
    latest_p = DATA / slug / "latest.json"
    hist = pd.read_csv(hist_p, dtype={"date": str, "team_id": str}) if hist_p.exists() else None
    import json

    latest = json.loads(latest_p.read_text(encoding="utf-8")) if latest_p.exists() else None
    return hist, latest


slugs = comp_slugs()
if not slugs:
    st.error("data/ 下还没有任何比赛数据。先运行 `python -m lbwatch demo` 生成演示数据，或跑一次真实抓取。")
    st.stop()

slug = st.sidebar.selectbox("比赛", slugs)
hist, latest = load_df(slug)

if hist is None or not latest:
    st.error(f"数据不完整：{slug}（缺 history.csv 或 latest.json）")
    st.stop()

# ---------- 我方主队伍的天序列（多队伍配置时取首个） ----------
tracked_ids = [str(t.get("team_id")) for t in latest.get("tracked", [])]
tracked_names = [t.get("name", "?") for t in latest.get("tracked", [])]
mine = (
    hist[hist["team_id"].astype(str) == str(tracked_ids[0])]
    .sort_values("date")
    .drop_duplicates(subset="date", keep="last")
)

if mine.empty:
    st.error(f"history.csv 里找不到我方队伍 {tracked_names}（可能掉出了 history_top 保留线）。")
    st.stop()

mine_daily = mine  # 每天一行（upsert 已按天幂等）

# ---------- 顶部指标 ----------
cur = latest["tracked"][0] if latest.get("tracked") else {}
c1, c2, c3, c4 = st.columns(4)
c1.metric("当前名次", f"#{cur.get('rank', '—')}", help="Public LB 最新名次")
rc = cur.get("rank_change")
delta_txt = None if rc is None else ("↑%d" % rc if rc > 0 else ("↓%d" % -rc if rc < 0 else "持平"))
delta_val = None if rc in (0, None) else rc
c2.metric("较上次", f"{delta_txt or '—'}", delta=delta_val, help="正值(绿↑)=名次提升")
c3.metric("当前分数", f"{cur.get('score', 0):.5f}")
c4.metric("参赛队伍", f"{latest.get('total', '—')}")

st.divider()

# ---------- 名次曲线（反转 Y 轴：越上面名次越好） ----------
import altair as alt

rank_src = mine_daily.rename(columns={"date": "日期", "rank": "名次"})[["日期", "名次"]]
base = alt.Chart(rank_src).mark_line(point=True).encode(
    x="日期:T",
    y=alt.Y("名次:Q", scale=alt.Scale(zero=False, reverse=True)),
    tooltip=["日期:T", "名次:Q"],
).properties(height=260, title="我的名次曲线（越高越好）")
st.altair_chart(base, use_container_width=True)

# ---------- 分数曲线 ----------
score_src = mine_daily.rename(columns={"date": "日期", "score": "分数"})[["日期", "分数"]]
base2 = alt.Chart(score_src).mark_line(color="#008ABC").encode(
    x="日期:T", y=alt.Y("分数:Q", scale=alt.Scale(zero=False)), tooltip=["日期:T", "分数:Q"]
).properties(height=220, title="我的分数曲线")
st.altair_chart(base2, use_container_width=True)

st.divider()

# ---------- 每日变化记录：谁超过我 / 我超过了谁 / 爬升榜 ----------
st.subheader("📅 每日变化记录")

wide_rank = hist.pivot_table(index="date", columns="team", values="rank", aggfunc="last")
wide_rank = wide_rank.sort_index()
dates = wide_rank.index.tolist()
name_col = mine_daily.set_index("date")["team"]

rows = []
for i in range(1, len(dates)):
    d_prev, d_cur = dates[i - 1], dates[i]
    r_prev, r_cur = wide_rank.loc[d_prev], wide_rank.loc[d_cur]
    my_team = name_col.get(d_cur) or name_col.get(d_prev)
    if my_team not in r_cur or pd.isna(r_cur[my_team]) or my_team not in r_prev or pd.isna(r_prev[my_team]):
        continue
    me_prev, me_cur = r_prev[my_team], r_cur[my_team]

    passed_me, passed_by = [], []
    movers = (r_prev - r_cur).dropna().sort_values(ascending=False)
    for team in wide_rank.columns:
        if team == my_team:
            continue
        pv, cv = r_prev.get(team), r_cur.get(team)
        if pd.isna(pv) or pd.isna(cv):
            continue
        if cv < me_cur and pv > me_prev:
            passed_me.append(f"{team}（{int(pv)}→{int(cv)}）")
        elif cv > me_cur and pv < me_prev:
            passed_by.append(f"{team}（{int(pv)}→{int(cv)}）")

    top_up = [f"{t} ↑{int(v)}" for t, v in movers.head(3).items() if v > 0]
    top_down = [f"{t} ↓{int(-v)}" for t, v in movers.tail(3).items() if v < 0]
    chg = int(me_prev - me_cur)
    rows.append(
        {
            "日期": d_cur,
            "我的名次": int(me_cur),
            "变化": ("↑" if chg > 0 else ("↓" if chg < 0 else "—")) + ("" if chg == 0 else str(abs(chg))),
            "超过我": ", ".join(passed_me[:4]) or "—",
            "我反超": ", ".join(passed_by[:4]) or "—",
            "今日爬升": " · ".join(top_up) or "—",
            "今日下跌": " · ".join(top_down) or "—",
        }
    )

if rows:
    st.dataframe(pd.DataFrame(rows).iloc[::-1], use_container_width=True, hide_index=True)
else:
    st.info("快照不足两天，还无法计算每日变化。明天之后这里会长出来。")

st.caption(f"数据范围: {dates[0]} ~ {dates[-1]} · 共 {len(dates)} 个快照日 · 队伍: {', '.join(tracked_names)}")
