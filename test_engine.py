import unittest
from datetime import date, timedelta

from engine import new_state, step, months_between, table_alloc

D0 = date(2026, 1, 5)


def run(prices, start=D0, cfg=None, state=None):
    """prices: [(date, close)]，返回 (state, 全部 actions)"""
    s = state or new_state(start, 100.0, start)
    out = []
    for d, c in prices:
        s, a = step(s, d, c, cfg)
        out += a
    return s, out


def types(acts, t):
    return [a for a in acts if a["type"] == t]


class T(unittest.TestCase):
    def test_table_edges(self):
        self.assertEqual(table_alloc(0.0999), (700, 200, 0, 100))
        self.assertEqual(table_alloc(0.10), (600, 200, 100, 100))
        self.assertEqual(table_alloc(0.20), (500, 200, 200, 100))
        self.assertEqual(table_alloc(0.45), (400, 200, 300, 100))

    def test_monthly_once_per_month_first_trading_day(self):
        days = [(date(2026, 2, 2) + timedelta(days=i), 95.0) for i in range(5)]
        _, acts = run(days)
        m = types(acts, "monthly")
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["date"], "2026-02-02")
        self.assertEqual(m[0]["alloc"]["纳斯达克"], 0)

    def test_rerun_same_day_no_duplicate(self):
        s, a1 = run([(date(2026, 2, 2), 85.0)])
        s, a2 = step(s, date(2026, 2, 2), 85.0)
        self.assertEqual(a2, [])

    def test_ath_updates(self):
        s, _ = run([(date(2026, 2, 2), 120.0)])
        self.assertEqual(s["ath"], 120.0)

    def test_crash_tier_and_skip_fill(self):
        cfg = {"base": 10000}
        # 第一次跌到 20% 当天就是 31% → 一次补齐 20+30 两档 = 40%
        s, acts = run([(date(2026, 2, 2), 69.0)], cfg=cfg)
        tier = types(acts, "tier")
        self.assertEqual(tier[0]["tiers"], [20, 30])
        self.assertEqual(tier[0]["pct"], 40)
        self.assertEqual(tier[0]["amount"], 4000)
        self.assertEqual(types(acts, "tranche")[0]["amount"], round(4000 / 3, 2))

    def test_tier_only_once_after_rebound(self):
        prices = [(date(2026, 2, 2), 79.0), (date(2026, 2, 3), 85.0), (date(2026, 2, 4), 79.0)]
        s, acts = run(prices)
        self.assertEqual(len(types(acts, "tier")), 1)

    def test_three_weekly_tranches(self):
        d = date(2026, 2, 2)
        prices = [(d + timedelta(days=i), 79.0) for i in range(0, 22)]
        _, acts = run(prices)
        tr = types(acts, "tranche")
        self.assertEqual([t["n"] for t in tr], [1, 2, 3])
        self.assertEqual([t["date"] for t in tr], ["2026-02-02", "2026-02-09", "2026-02-16"])

    def test_recover_then_balanced_then_new_round(self):
        prices = ([(date(2026, 2, 2), 75.0)] + [(date(2026, 2, 23 + i), 91.0) for i in range(5)]
                  + [(date(2026, 3, 2), 91.0)] + [(date(2026, 3, 25 + i), 85.0) for i in range(5)]
                  + [(date(2026, 4, 1), 85.0)] + [(date(2026, 4, 24 + i), 79.0) for i in range(5)]
                  + [(date(2026, 5, 1), 79.0)])
        s, acts = run(prices)
        self.assertEqual(len(types(acts, "crash_end")), 1)
        m = types(acts, "monthly")
        self.assertEqual(m[1]["alloc"], {"债券": 300, "标普": 300, "纳斯达克": 300, "黄金": 100})
        self.assertEqual(m[2]["alloc"]["纳斯达克"], 300)  # recovered 跌 15% 仍 300/300/300/100
        self.assertEqual(len(types(acts, "crash_start")), 2)  # 再跌到 20% 新一轮
        self.assertEqual(s["crash"]["tiers_done"], [20])

    def test_transition_after_18_months(self):
        start = date(2024, 1, 2)
        prices = []
        d = start
        while d < date(2026, 3, 1):
            if d.weekday() < 5:
                prices.append((d, 99.0))
            d += timedelta(days=1)
        s, acts = run(prices, start=start)
        moves = types(acts, "transition_move")
        self.assertEqual(types(acts, "transition_start")[0]["date"][:7], "2025-07")
        self.assertEqual([m["date"][:7] for m in moves], ["2025-08", "2025-11", "2026-02"])
        self.assertEqual(moves[0]["to"], "标普")
        last = types(acts, "monthly")[-1]
        self.assertEqual(last["alloc"], {"债券": 400, "标普": 300, "纳斯达克": 200, "黄金": 100})

    def test_transition_interrupted_by_crash(self):
        start = date(2024, 1, 2)
        s = new_state(start, 100.0, start)
        s["mode"], s["transition"] = "transition", {"coins": 2, "next": "2026-05"}
        s, acts = run([(date(2026, 3, 2), 79.0)], state=s)
        self.assertEqual(s["mode"], "crash")
        self.assertIsNone(s["transition"])
        self.assertEqual(types(acts, "monthly")[0]["alloc"]["债券"], 500)

    def test_recover_only_checked_on_month_start(self):
        prices = [(date(2026, 2, 2), 79.0), (date(2026, 2, 16), 92.0), (date(2026, 3, 2), 85.0)]
        s, acts = run(prices)
        self.assertEqual(types(acts, "crash_end"), [])  # 月中弹回 8%、月初又在 15% → 仍在路线二
        self.assertEqual(s["mode"], "crash")

    def test_monthly_uses_5day_average(self):
        # 前 4 天 95（回撤 5%），月初当天暴跌到 88（12%）→ 5 日平均 93.6（6.4%）→ 仍是第 0 档
        prices = [(date(2026, 1, 26 + i), 95.0) for i in range(4)] + [(date(2026, 2, 2), 88.0)]
        _, acts = run(prices)
        feb = [a for a in types(acts, "monthly") if a["date"] == "2026-02-02"][0]
        self.assertEqual(feb["alloc"]["纳斯达克"], 0)
        self.assertEqual(feb["dd_avg"], 0.064)

    def test_no_base_amount_none(self):
        _, acts = run([(date(2026, 2, 2), 79.0)])
        self.assertIsNone(types(acts, "tier")[0]["amount"])

    def test_custom_rules_two_assets(self):
        cfg = {"rules": {"assets": ["货币基金", "纳指基金"],
                         "table": [[0.15, [0, 500]], [0.0, [500, 0]]],
                         "after_crash": [250, 250], "transition_after_months": 0,
                         "crash_at": 0.25, "tiers": [25, 40], "tier_pct": 50, "tranches": 2,
                         "avg_days": 1}}
        s, acts = run([(date(2026, 2, 2), 84.0)], cfg=cfg)
        self.assertEqual(types(acts, "monthly")[0]["alloc"], {"货币基金": 0, "纳指基金": 500})
        self.assertEqual(types(acts, "tier"), [])           # 16% 还没到 25%
        s, acts = run([(date(2026, 2, 3), 74.0)], cfg=cfg, state=s)
        self.assertEqual(types(acts, "tier")[0]["pct"], 50)
        self.assertEqual(types(acts, "tranche")[0]["of"], 2)

    def test_mail_render_uses_rules(self):
        from mailer import render
        cfg = {"rules": {"assets": ["现金", "纳指"], "table": [[0.0, [600, 400]]], "route2_from": "现金",
                         "route2_to": "纳指", "after_crash": [500, 500]}}
        s, acts = run([(date(2026, 2, 2), 79.0)], cfg=cfg)
        title, body = render(acts, s, 79.0, cfg)
        self.assertIn("【需操作】", title)
        self.assertIn("现金 600，纳指 400", body)
        self.assertIn("卖出现金", body)
        self.assertNotIn("债券", body)

    def test_months_between(self):
        self.assertEqual(months_between(date(2024, 1, 31), date(2025, 7, 30)), 17)
        self.assertEqual(months_between(date(2024, 1, 2), date(2025, 7, 2)), 18)


if __name__ == "__main__":
    unittest.main()
