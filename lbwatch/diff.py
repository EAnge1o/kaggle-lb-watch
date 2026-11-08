"""变化分析：对比最新快照与上一次快照，产出中文 Markdown 报告。

名次方向约定：rank_change = 昨日名次 - 今日名次，正值 = 名次提升(↑)。
"""

from __future__ import annotations

import pandas as pd


def resolve_tracked(lb: pd.DataFrame, names: list[str], known_ids: list[str] | None = None):
    """按队伍名匹配我方队伍（大小写不敏感精确命中优先，子串兜底）；
    known_ids 来自上次记录，优先按 id 复用以防队名微调。返回 (我方行 DataFrame, 命中的 team_id 集合)。"""
    lb = lb.copy()
    lb = lb.assign(team_lower=lb["team"].str.casefold())

    matched_ids: set[str] = set()

    for tid in known_ids or []:
        hit = lb.loc[lb["team_id"].astype(str) == str(tid)]
        if not hit.empty:
            matched_ids.add(str(tid))

    for n in names:
        n = n.casefold().strip()
        exact = lb.loc[lb["team_lower"] == n, "team_id"].astype(str).tolist()
        if exact:
            matched_ids.update(exact)
            continue
        sub = lb.loc[lb["team_lower"].str.contains(n, regex=False), "team_id"].astype(str).tolist()
        if len(sub) == 1:
            matched_ids.add(sub[0])
        # 多个子串命中时不盲选，避免误报

    mine = lb[lb["team_id"].astype(str).isin(matched_ids)].sort_values("rank")
    return mine, sorted(matched_ids)


def compute_change(cur: pd.DataFrame, prev: pd.DataFrame | None, names: list[str], known_ids: list[str] | None = None) -> dict:
    """cur/prev 为当日/上日快照(DataFrame)。prev 为 None 表示首次记录。"""
    mine_cur, ids = resolve_tracked(cur, names, known_ids)
    mine_prev = pd.DataFrame()
    if prev is not None and len(prev):
        mine_prev, _ = resolve_tracked(prev, names, ids)

    total = len(cur)
    top1_cur = cur.iloc[0] if total else None
    top1_prev = prev.iloc[0] if prev is not None and len(prev) else None

    # 全场爬升/下跌（只看两次快照都出现的队伍）
    movers: list[tuple[str, int]] = []
    if prev is not None and len(prev):
        p = prev.set_index("team_id")
        c = cur.set_index("team_id")
        common = c.index.intersection(p.index)
        chg = p.loc[common, "rank"].astype(int) - c.loc[common, "rank"].astype(int)
        for tid, v in chg.sort_values(ascending=False).items():
            if v != 0:
                movers.append((str(c.loc[tid, "team"]), int(v)))

    tracked = []
    for _, row in mine_cur.iterrows():
        tid = str(row["team_id"])
        item = {
            "team_id": tid,
            "name": str(row["team"]),
            "rank": int(row["rank"]),
            "score": float(row["score"]),
        }
        pr = mine_prev.loc[mine_prev["team_id"].astype(str) == tid] if not mine_prev.empty else pd.DataFrame()
        if not pr.empty:
            p0 = pr.iloc[0]
            my_cur_rank, my_prev_rank = int(row["rank"]), int(p0["rank"])
            item.update(
                prev_rank=my_prev_rank,
                prev_score=float(p0["score"]),
                rank_change=my_prev_rank - my_cur_rank,
                score_delta=float(row["score"]) - float(p0["score"]),
            )
            # 谁超过我 / 我超过了谁（以名次线交叉判定）
            passed_me, passed_by = [], []
            if prev is not None and len(prev):
                p_idx = prev.set_index("team_id")
                c_idx = cur.set_index("team_id")
                common = c_idx.index.intersection(p_idx.index)
                for tid2 in common:
                    if tid2 == tid:
                        continue
                    r2_prev = int(p_idx.loc[tid2, "rank"])
                    r2_cur = int(c_idx.loc[tid2, "rank"])
                    if r2_cur < my_cur_rank and r2_prev > my_prev_rank:
                        passed_me.append((str(c_idx.loc[tid2, "team"]), r2_prev, r2_cur))
                    elif r2_cur > my_cur_rank and r2_prev < my_prev_rank:
                        passed_by.append((str(c_idx.loc[tid2, "team"]), r2_prev, r2_cur))
            item["passed_me"] = passed_me
            item["passed_by"] = passed_by
        else:
            item["first_seen"] = True
        tracked.append(item)

    top1_changed = None
    if top1_cur is not None and top1_prev is not None and str(top1_cur["team_id"]) != str(top1_prev["team_id"]):
        top1_changed = {"from": str(top1_prev["team"]), "to": str(top1_cur["team"])}

    return {"total": int(total), "tracked": tracked, "movers": movers[:10], "top1_changed": top1_changed}


def format_report(comp_name: str, date: str, d: dict) -> str:
    lines = [f"【{comp_name} · {date}】"]
    for t in d["tracked"]:
        base = f"{t['name']}: 名次 #{t['rank']} / {d['total']}, 分数 {t['score']:.5f}"
        if t.get("first_seen"):
            lines.append(base + "（首次记录）")
            continue
        rc = t["rank_change"]
        arrow = "↑" if rc > 0 else ("↓" if rc < 0 else "—")
        sign = "+" if t["score_delta"] > 0 else ""
        lines.append(
            f"{base}（{arrow}{abs(rc)} 于上次 #{t['prev_rank']}, 分数 {sign}{t['score_delta']:.5f}）"
        )
        if t.get("passed_me"):
            who = ", ".join(f"{n}({a}→{b})" for n, a, b in t["passed_me"][:5])
            lines.append(f"  ⚠️ 超过你: {who}")
        if t.get("passed_by"):
            who = ", ".join(f"{n}({a}→{b})" for n, a, b in t["passed_by"][:5])
            lines.append(f"  ✅ 你反超: {who}")

    ups = " · ".join(f"{n} ↑{v}" for n, v in [m for m in d["movers"] if m[1] > 0][:5])
    downs = " · ".join(f"{n} ↓{abs(v)}" for n, v in [m for m in d["movers"] if m[1] < 0][:5])
    if ups:
        lines.append(f"爬升: {ups}")
    if downs:
        lines.append(f"下跌: {downs}")
    if d["top1_changed"]:
        lines.append(f"👑 榜一易主: {d['top1_changed']['from']} → {d['top1_changed']['to']}")
    return "\n".join(lines)
