"""规则引擎：纯函数 step(state, date, close, cfg) -> (state, actions)。不读时间、不联网、不发信。

回撤 = 1 - 收盘 / 历史最高收盘（纳斯达克 100，收盘价），四舍五入到 0.01%。
状态（mode）：
  normal      平时：每月新钱按跌幅表
  crash       路线二进行中（跌到过 20%，还没涨回距高点 10% 以内）：新钱按跌幅表 + 债券底仓分档换仓
  recovered   路线二结束后：新钱 300/300/300/100 长期执行
  transition  满 18 个月没跌到 20%：每 3 个月挪一枚，4 枚挪完后新钱 300/300/300/100
任何状态下跌到 20% → 进入 crash（新一轮，档位清零，过渡进度清零）。
"""
from __future__ import annotations

import copy
from datetime import date, timedelta

# 默认规则（示例）。在 config.json 的 "rules" 里改成你自己的，没写的项沿用这里的默认值。
DEFAULT_RULES = {
    "assets": ["债券", "标普", "纳斯达克", "黄金"],
    "table": [  # [回撤下限, [各资产金额]]，从深到浅
        [0.30, [400, 200, 300, 100]],
        [0.20, [500, 200, 200, 100]],
        [0.10, [600, 200, 100, 100]],
        [0.00, [700, 200, 0, 100]],
    ],
    "after_crash": [300, 300, 300, 100],          # 路线二结束后的新钱
    "transition_after_months": 18,                 # 多久没跌到 crash_at 就开始过渡（0 = 不过渡）
    "transition_every_months": 3,
    "transition_steps": [[600, 300, 0, 100], [500, 300, 100, 100],
                         [400, 300, 200, 100], [300, 300, 300, 100]],
    "crash_at": 0.20,                              # 路线二启动
    "recover_at": 0.10,                            # 路线二结束
    "tiers": [20, 30, 40, 50],                     # 路线二档位（回撤 %）
    "tier_pct": 20,                                # 每档卖基数的 %
    "tranches": 3,                                 # 每档分几周买
    "avg_days": 5,                                 # 每月定档、判断涨回用几天平均收盘
}


def rules(cfg: dict | None) -> dict:
    r = dict(DEFAULT_RULES)
    r.update((cfg or {}).get("rules") or {})
    return r


def new_state(start: date, ath: float, ath_date: date) -> dict:
    return {
        "ath": ath, "ath_date": ath_date.isoformat(),
        "mode": "normal",
        "anchor_date": start.isoformat(),   # 18 个月从这天算（启动日 / 上一轮路线二结束日）
        "last_date": None,
        "last_close": None,
        "alloc_month": None,                # 已发过新钱分配的月份 YYYY-MM
        "recent": [],                       # 最近 avg_days 个收盘价
        "crash": None,                      # {"start","tiers_done":[],"pending":[...]}
        "transition": None,                 # {"coins":0,"next":"YYYY-MM"}
    }


def drawdown(close: float, ath: float) -> float:
    return round(1 - close / ath, 4)


def add_months(ym: str, n: int) -> str:
    y, m = map(int, ym.split("-"))
    m += n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def months_between(a: date, b: date) -> int:
    """a 到 b 满了多少个月。"""
    n = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        n -= 1
    return n


def table_alloc(dd: float, r: dict | None = None):
    r = r or DEFAULT_RULES
    for lo, alloc in r["table"]:
        if dd >= lo:
            return tuple(alloc)
    return tuple(r["table"][-1][1])


def fmt_alloc(a, r: dict | None = None) -> dict:
    return dict(zip((r or DEFAULT_RULES)["assets"], a))


def step(state: dict, d: date, close: float, cfg: dict | None = None):
    cfg = cfg or {}
    r = rules(cfg)
    s = copy.deepcopy(state)
    actions = []
    ds = d.isoformat()
    if s["last_date"] and ds <= s["last_date"]:
        return s, actions  # 处理过的日期跳过（重跑不重复）

    # 1. 历史高点
    if close > s["ath"]:
        s["ath"], s["ath_date"] = close, ds
    dd = drawdown(close, s["ath"])
    s["recent"] = ((s.get("recent") or [])[-(r["avg_days"] - 1):] if r["avg_days"] > 1 else []) + [close]
    avg = sum(s["recent"]) / len(s["recent"])
    dd_avg = drawdown(avg, s["ath"])        # 5 日平均回撤：每月定档、判断涨回用
    ym = ds[:7]

    # 2. 状态转换
    if dd >= r["crash_at"] and s["mode"] != "crash":
        s["mode"] = "crash"
        s["crash"] = {"start": ds, "tiers_done": [], "pending": []}
        s["transition"] = None
        actions.append({"type": "crash_start", "dd": dd})
    elif s["mode"] == "crash" and max(dd, dd_avg) <= r["recover_at"] and s["alloc_month"] != ym:
        # 当天和 5 日平均都在 10% 以内才算涨回（只看平均的话，2022-04-01 当天 10.3%、平均 9.5% 会被误判）
        # 只在每月第一个交易日判断是否涨回（避免 2022-03 那种两周内跌破 20% 又弹回 10% 的来回切换）
        left = s["crash"]["pending"]
        s["mode"], s["anchor_date"] = "recovered", ds
        s["crash"] = None
        actions.append({"type": "crash_end", "dd": dd, "dd_avg": dd_avg, "pending_dropped": left})
    elif (s["mode"] == "normal" and r["transition_after_months"]
          and months_between(date.fromisoformat(s["anchor_date"]), d) >= r["transition_after_months"]):
        s["mode"] = "transition"
        # 当月新钱已按旧表发过时，从下个月第一个交易日开始挪
        s["transition"] = {"coins": 0, "next": ym if s["alloc_month"] != ym else add_months(ym, 1)}
        actions.append({"type": "transition_start"})

    # 3. 路线二：新档（含跳档补齐）
    if s["mode"] == "crash":
        c = s["crash"]
        new = [t for t in r["tiers"] if dd >= t / 100 and t not in c["tiers_done"]]
        if new:
            c["tiers_done"] += new
            pct = r["tier_pct"] * len(new)
            done_pct = r["tier_pct"] * len(c["tiers_done"])
            c["pending"].append({"tiers": new, "pct": pct, "left": r["tranches"], "last": None})
            actions.append({"type": "tier", "tiers": new, "pct": pct, "cum_pct": done_pct,
                            "amount": _amt(cfg, pct), "dd": dd})
        # 分周买入
        for p in c["pending"]:
            if p["left"] and (p["last"] is None or d - date.fromisoformat(p["last"]) >= timedelta(days=7)):
                n = r["tranches"] - p["left"] + 1
                p["left"] -= 1
                p["last"] = ds
                actions.append({"type": "tranche", "tiers": p["tiers"], "n": n, "of": r["tranches"],
                                "pct": round(p["pct"] / r["tranches"], 4),
                                "amount": _amt(cfg, p["pct"] / r["tranches"])})
        c["pending"] = [p for p in c["pending"] if p["left"]]

    # 4. 过渡：每 3 个月挪一枚（当月第一个交易日）
    if s["mode"] == "transition":
        t = s["transition"]
        steps = r["transition_steps"]
        if ym >= t["next"] and t["coins"] < len(steps) and s["alloc_month"] != ym:
            prev = steps[t["coins"] - 1] if t["coins"] else r["table"][-1][1]
            t["coins"] += 1
            t["next"] = add_months(ym, r["transition_every_months"])
            cur = steps[t["coins"] - 1]
            to = [n for n, x, y in zip(r["assets"], prev, cur) if y > x]
            actions.append({"type": "transition_move", "coin": t["coins"], "of": len(steps),
                            "to": "、".join(to) or "—"})

    # 5. 每月新钱（当月第一个交易日）
    if s["alloc_month"] != ym:
        s["alloc_month"] = ym
        if s["mode"] in ("normal", "crash"):
            a = table_alloc(dd_avg, r)
        elif s["mode"] == "transition":
            k = s["transition"]["coins"]
            a = tuple(r["transition_steps"][k - 1]) if k else table_alloc(dd_avg, r)
        else:
            a = tuple(r["after_crash"])
        actions.append({"type": "monthly", "alloc": fmt_alloc(a, r), "dd": dd, "dd_avg": dd_avg,
                        "n_avg": len(s["recent"]), "mode": s["mode"]})

    # 6. 每日行情（每个交易日都发一封）
    actions.append({"type": "daily", "dd": dd})

    s["last_date"], s["last_close"] = ds, close
    for a in actions:
        a.setdefault("date", ds)
    return s, actions


def _amt(cfg, pct):
    base = cfg.get("base")
    return round(base * pct / 100, 2) if base else None
