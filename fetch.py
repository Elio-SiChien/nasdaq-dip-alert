"""取纳斯达克 100（^NDX）日收盘。主源 yfinance，备用 Stooq；都失败抛 FetchError。
只返回已收盘的 K 线（日期早于今天美东时间，或今天美东已过 16:15）。"""
from __future__ import annotations

import io
import time
import urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")


class FetchError(Exception):
    pass


def _closed_only(s: pd.Series) -> pd.Series:
    now = datetime.now(ET)
    if (now.hour, now.minute) < (16, 15):
        return s[s.index.date < now.date()]
    return s[s.index.date <= now.date()]


def _yf(period: str) -> pd.Series:
    import yfinance as yf
    df = yf.download("^NDX", period=period, interval="1d", progress=False, auto_adjust=False)
    if df is None or df.empty:
        raise FetchError("yfinance 返回空数据")
    s = df["Close"]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s.dropna()


def _stooq() -> pd.Series:
    url = "https://stooq.com/q/d/l/?s=%5Endx&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=30).read().decode()
    df = pd.read_csv(io.StringIO(raw), parse_dates=["Date"], index_col="Date")
    if "Close" not in df or df.empty:
        raise FetchError("Stooq 返回格式不对")
    return df["Close"].dropna()


def get_closes(period: str = "1mo") -> tuple[pd.Series, str]:
    errors = []
    for attempt in range(3):
        try:
            return _closed_only(_yf(period)), "yfinance"
        except Exception as e:  # noqa: BLE001
            errors.append(f"yfinance #{attempt + 1}: {e}")
            time.sleep(5 * (attempt + 1))
    try:
        s = _stooq()
        if period != "max":
            s = s.iloc[-40:]
        return _closed_only(s), "stooq"
    except Exception as e:  # noqa: BLE001
        errors.append(f"stooq: {e}")
    raise FetchError("；".join(errors))


def to_rows(s: pd.Series) -> list[tuple[date, float]]:
    return [(ts.date(), float(v)) for ts, v in s.items()]
