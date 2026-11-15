"""每日运行入口（GitHub Actions 调用）：取数 → 引擎 → 发信 → 存 state.json。
本地试跑：python main.py（没配邮箱时只打印邮件内容）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from engine import new_state, step
from fetch import FetchError, get_closes, to_rows
from mailer import render, send

ROOT = Path(__file__).parent
STATE, CONFIG = ROOT / "state.json", ROOT / "config.json"
JUMP = 0.15  # 单日涨跌超过 15% 视为数据异常


def load(p, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def market(rows, d, c) -> dict:
    """当日 / 近 5 日 / 近 1 个月（21 个交易日）涨跌。"""
    past = [x for x in rows if x[0] < d]
    def chg(n):
        return c / past[-n][1] - 1 if len(past) >= n else None
    return {"chg_1d": chg(1), "chg_5d": chg(5), "chg_1m": chg(21)}


def test_mail(cfg, state) -> int:
    """测试：按最新一个收盘价发一封日报，标题带【测试】，不改 state。"""
    rows = to_rows(get_closes("3mo")[0])
    d, c = rows[-1]
    msg = render([{"type": "daily", "date": d.isoformat()}], state, c, cfg, market(rows, d, c))
    ok = send("【测试】" + msg[0], msg[1])
    print("测试邮件", "已发送" if ok else "没发出（没配邮箱）")
    return 0 if ok else 1


def main() -> int:
    cfg = load(CONFIG, {})
    state = load(STATE, None)
    if "--test" in sys.argv and state:
        return test_mail(cfg, state)
    try:
        if state is None:
            hist, src = get_closes("max")
            rows = to_rows(hist)
            ath_d, ath = max(rows, key=lambda r: r[1])
            last_d, last_c = rows[-1]
            state = new_state(last_d, ath, ath_d)
            state["last_date"], state["last_close"] = last_d.isoformat(), last_c
            state["recent"] = [r[1] for r in rows[-5:]]
            save(STATE, state)
            send("纳指提醒 · 已启动",
                 f"程序已启动（数据源 {src}）。\n纳斯达克 100 历史最高收盘：{ath:,.2f}（{ath_d}）\n"
                 f"最新收盘：{last_c:,.2f}（{last_d}），距高点 {1 - last_c / ath:.2%}。\n"
                 "从下一个交易日开始按规则提醒；18 个月计时从今天算。")
            return 0
        closes, src = get_closes("3mo")
    except FetchError as e:
        send("【告警】纳指提醒 · 取数失败", f"今天没拿到纳斯达克 100 收盘价，没有给出任何操作建议。\n\n{e}")
        return 1

    rows = to_rows(closes)
    new_rows = [r for r in rows if r[0].isoformat() > state["last_date"]]
    for d, c in new_rows:
        prev = state["last_close"]
        if prev and abs(c / prev - 1) > JUMP and cfg.get("accept_jump") != d.isoformat():
            send("【告警】纳指提醒 · 数据异常",
                 f"{d} 收盘 {c:,.2f}，比前一天 {prev:,.2f} 变化 {c / prev - 1:+.1%}，超过 ±15%。\n"
                 "可能是数据源出错，这天先不处理。请手动核对：如果数据是真的，"
                 f"在 config.json 里加一行 \"accept_jump\": \"{d}\"，下次运行就会继续。")
            return 1
        state, acts = step(state, d, c, cfg)
        save(STATE, state)  # 先存再发：重跑不会重复处理同一天
        msg = render(acts, state, c, cfg, market(rows, d, c))
        if msg:
            send(*msg)
    print(f"处理 {len(new_rows)} 天（数据源 {src}），最新 {state['last_date']}，模式 {state['mode']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
