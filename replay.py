"""历史回放：python replay.py 2021-01-04 2024-06-28 [基数]
用 ^NDX 日收盘从起始日跑引擎，历史高点按起始日之前的全部数据初始化。不发信，只打印动作。"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from engine import new_state, step

CSV = Path(__file__).parent / "data" / "ndx.csv"


def load():
    if not CSV.exists():
        import yfinance as yf
        CSV.parent.mkdir(exist_ok=True)
        df = yf.download("^NDX", period="max", progress=False, auto_adjust=False)["Close"]
        df.to_csv(CSV)
    s = pd.read_csv(CSV, index_col=0, parse_dates=True).iloc[:, 0].dropna()
    return s


def main(start, end, base=None):
    s = load()
    before, run = s[:start].iloc[:-1], s[start:end]
    st = new_state(run.index[0].date(), float(before.max()), before.idxmax().date())
    cfg = {"base": base}
    last_alloc = None
    for ts, c in run.items():
        st, acts = step(st, ts.date(), float(c), cfg)
        for a in acts:
            t = a["type"]
            if t in ("heartbeat", "daily"):
                continue
            if t == "monthly":
                al = tuple(a["alloc"].values())
                if al == last_alloc:
                    continue
                last_alloc = al
            info = {k: v for k, v in a.items() if k not in ("type", "date")}
            print(f"{a['date']}  收盘 {c:>9,.0f}  回撤 {1 - c / st['ath']:6.1%}  {t:16s} {info}")
    print(f"结束 {st['last_date']} 模式 {st['mode']} 高点 {st['ath']:,.0f}（{st['ath_date']}）")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[1], float(a[2]) if len(a) > 2 else None)
