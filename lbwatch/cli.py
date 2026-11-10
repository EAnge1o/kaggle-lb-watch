"""命令行入口：

    python -m lbwatch run    # 真实抓取（需 Kaggle 凭证）
    python -m lbwatch demo   # 合成数据演示（无需凭证）
    python -m lbwatch card   # 仅根据现有数据重新生成卡片
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from lbwatch import config, demo, diff, fetch, readme, store, svgcard

# Windows 控制台默认 GBK，会编码不了 emoji 报告；统一到 UTF-8（Actions 上无害）
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

ROOT = Path(__file__).resolve().parents[1]  # 仓库根目录（data/ 在这里）


def _load_prev(slug: str, date: str) -> pd.DataFrame | None:
    """取 date 之前最近一次数据作为 diff 基线：优先全量快照文件，其次 history.csv。"""
    d = store.comp_dir(ROOT, slug)
    snap = d / "snapshot"
    if snap.exists():
        cand = sorted((p.stem for p in snap.glob("*.csv")), reverse=True)
        cand = [c for c in cand if c <= date]
        if cand:
            return pd.read_csv(
                snap / f"{cand[0]}.csv", dtype={"rank": "Int64", "team_id": str, "team": str, "score": float}
            )
    hist = store.load_history(ROOT, slug)
    if hist.empty:
        return None
    older = sorted(set(hist["date"]) - {""})
    older = [x for x in older if x < date]
    if not older:
        return None
    return hist[hist["date"] == older[-1]].copy()


def _process_stream(
    slug: str,
    name: str,
    lb_by_date: dict[str, pd.DataFrame],
    settings: config.Settings,
) -> None:
    """对一场比赛按日期序列走完：快照 → history → diff 报告 → latest.json → 卡片。"""
    latest_prev = store.load_latest(ROOT, slug)
    known_ids = [str(t.get("team_id")) for t in (latest_prev or {}).get("tracked", []) if t.get("team_id")]

    reports: list[str] = []
    prev: pd.DataFrame | None = None
    for date in sorted(lb_by_date):
        lb = lb_by_date[date]
        if prev is None:
            prev = _load_prev(slug, date)  # 先取基线（可能是昨天，也可能是今天上一次运行），再覆盖写今日快照
        store.save_snapshot(ROOT, slug, date, lb)
        chg = diff.compute_change(lb, prev, settings.teams, known_ids)
        if chg["tracked"]:
            known_ids = [t["team_id"] for t in chg["tracked"]]
        store.upsert_history(ROOT, slug, date, lb, settings.history_top, known_ids or [])

        if prev is not None:
            reports.append(diff.format_report(name, date, chg))
        else:
            reports.append(f"【{name} · {date}】开始记录（首次快照，追踪 {len(chg['tracked'])} 支队伍）")
        prev = lb

        store.save_latest(
            ROOT,
            slug,
            {
                "date": date,
                "slug": slug,
                "name": name,
                "total": chg["total"],
                "tracked": chg["tracked"],
                "top1_changed": chg["top1_changed"],
            },
        )
        prev = lb

    store.prune_snapshots(ROOT, slug, settings.keep_snapshots)

    latest = store.load_latest(ROOT, slug)
    if not (latest or {}).get("tracked"):
        print(f"[card skip] {name}: 你的队伍暂未出现在 Public LB（还没有有效提交/出分？），上榜后出卡")
    else:
        ids = {str(t.get("team_id")) for t in latest.get("tracked", [])}
        hist = store.load_history(ROOT, slug)
        rows = [
            {"date": r["date"], "rank": int(r["rank"]), "score": float(r["score"])}
            for _, r in hist[hist["team_id"].astype(str).isin(ids)].sort_values("date").iterrows()
        ]
        svgcard.render_card(name, latest, rows, store.comp_dir(ROOT, slug) / "card.svg")

    print("\n".join(reports))


def _merge_discovered(settings: config.Settings) -> list[config.Competition]:
    """手动 competitions + 自动发现「我已加入的比赛」（去重、剔除黑名单）。"""
    comps = list(settings.competitions)
    if settings.discover == "off":
        return comps

    known = {c.slug for c in comps}
    excluded = set(settings.exclude)
    try:
        entered = fetch.list_entered_competitions()
    except Exception as e:  # 自动发现失败不拦整套运行，退回手动列表
        print(f"⚠️ 自动发现失败（{e}），退回手动 competitions 列表", file=sys.stderr)
        return comps

    now = datetime.now()
    added = 0
    for it in entered:
        slug = it["slug"]
        if slug in known or slug in excluded:
            continue
        dl = it["deadline"]
        if settings.discover == "active" and dl is not None:
            if dl.tzinfo is not None:
                dl = dl.replace(tzinfo=None)
            if dl < now:  # 已截止
                continue
        comps.append(config.Competition(slug=slug, name=it["title"]))
        added += 1
    print(f"自动发现：已加入 {len(entered)} 场，本轮新增追盯 {added} 场（其余重复或被剔除）")
    return comps


def cmd_run(settings: config.Settings) -> int:
    if not settings.competitions and settings.discover == "off":
        print("⚠️ config.yaml 尚未配置 competitions（示例见 config.example.yaml）。本次跳过抓取，保持绿灯。")
        return 0

    comps = _merge_discovered(settings)
    if not comps:
        print("没有可追盯的比赛（discover 开着但你还没 join 任何比赛？）。本次跳过，保持绿灯。")
        return 0

    failures: list[tuple[str, Exception]] = []
    for i, comp in enumerate(comps):
        if i:
            time.sleep(2.5)  # 场次间隔，降低 API 突发压力
        try:
            lb = fetch.fetch_leaderboard(comp.slug)
            _process_stream(comp.slug, comp.name, {store.utc_today(): lb}, settings)
            print(f"[OK] {comp.name}")
        except Exception as e:  # noqa: BLE001 —— 单场失败不影响其他场次
            failures.append((comp.slug, e))
            print(f"[FAIL] {comp.name}: {e}", file=sys.stderr)
    if failures and len(failures) == len(comps):
        print("所有比赛均抓取失败。", file=sys.stderr)
        return 1

    _text, n = readme.render(ROOT, ROOT / "README.md")
    print(f"[OK] README 全景已更新（{n} 场比赛）")
    return 0


def cmd_demo(settings: config.Settings) -> int:
    comp = config.Competition(slug="demo-comp", name="Demo Competition")
    lb_by_date = demo.generate_snapshots(n_teams=800)
    demo_settings = config.Settings(
        teams=settings.teams + ([demo.TRACKED_NAME] if demo.TRACKED_NAME not in settings.teams else []),
        competitions=[comp],
        history_top=200,
        keep_snapshots=0,
    )
    _process_stream(comp.slug, comp.name, lb_by_date, demo_settings)
    print("[OK] demo 数据已生成（60 天合成快照，队伍「我的队伍」已自动追踪）")
    return 0


def cmd_card(settings: config.Settings) -> int:
    comps = list(settings.competitions)
    # 无网络降级：直接扫描 data/ 下所有已有数据的比赛（含 config 没写的）
    data_dir = ROOT / "data"
    if data_dir.exists():
        known = {c.slug for c in comps}
        for d in sorted(data_dir.iterdir()):
            if d.is_dir() and (d / "latest.json").exists() and d.name not in known:
                comps.append(config.Competition(slug=d.name, name=(store.load_latest(ROOT, d.name) or {}).get("name") or d.name))
    for comp in comps:
        latest = store.load_latest(ROOT, comp.slug)
        if not latest:
            print(f"[SKIP] {comp.slug}: 无 latest.json（先跑 run/demo）")
            continue
        if not latest.get("tracked"):
            print(f"[SKIP] {comp.slug}: 你的队伍暂未上榜，无卡片")
            continue
        ids = {str(t.get("team_id")) for t in latest.get("tracked", [])}
        hist = store.load_history(ROOT, comp.slug)
        rows = [
            {"date": r["date"], "rank": int(r["rank"]), "score": float(r["score"])}
            for _, r in hist[hist["team_id"].astype(str).isin(ids)].sort_values("date").iterrows()
        ]
        svgcard.render_card(comp.name, latest, rows, store.comp_dir(ROOT, comp.slug) / "card.svg")
        print(f"[OK] 卡片已更新: data/{comp.slug}/card.svg")
    _text, n = readme.render(ROOT, ROOT / "README.md")
    print(f"[OK] README 全景已更新（{n} 场比赛）")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "run"

    try:
        settings = config.load()
    except FileNotFoundError:
        if cmd == "demo":
            # 没有配置文件也允许 demo 跑起来
            settings = config.Settings(teams=[demo.TRACKED_NAME], competitions=[config.Competition("demo-comp", "Demo")])
        elif cmd == "card":
            settings = config.Settings()  # 空配置：card 会扫描 data/ 下所有比赛
        else:
            raise

    if cmd == "run":
        return cmd_run(settings)
    if cmd == "demo":
        return cmd_demo(settings)
    if cmd == "card":
        return cmd_card(settings)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
