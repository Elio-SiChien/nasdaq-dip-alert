"""把引擎动作写成邮件，用 Gmail SMTP 发。没配环境变量时只打印（dry run）。
环境变量：GMAIL_USER、GMAIL_APP_PASSWORD（应用专用密码）、MAIL_TO（默认同 GMAIL_USER）。"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header

from engine import fmt_alloc, rules

MODE_CN = {"normal": "平时", "crash": "路线二进行中", "recovered": "路线二已结束",
           "transition": "过渡中"}
FOOT = "\n\n——\n这是按你自己定的规则自动算出的提醒，不是投资建议。买不买、买多少，最后由你自己决定和操作。"


def _money(x):
    return f"{x:,.0f}" if x is not None else None


def render(acts: list[dict], state: dict, close: float, cfg: dict,
           market: dict | None = None) -> tuple[str, str] | None:
    """返回 (标题, 正文)；没有值得发的就返回 None。"""
    if not acts:
        return None
    need_action = any(a["type"] in ("tier", "tranche", "monthly", "transition_move", "crash_start")
                      for a in acts)
    dd = round(1 - close / state["ath"], 4)
    r = rules(cfg)
    src, dst = r.get("route2_from", r["assets"][0]), r.get("route2_to", "纳斯达克")
    fmt = lambda al: "，".join(f"{k} {v}" for k, v in al.items())
    lines = []
    for a in acts:
        t = a["type"]
        if t == "daily":
            continue
        if t == "monthly":
            al = a["alloc"]
            lines.append(f"【本月新钱分配】按最近 {a['n_avg']} 个交易日平均收盘，距高点 {a['dd_avg']:.1%} 定档：")
            lines.append("  " + fmt(al))
        elif t == "crash_start":
            lines.append(f"【路线二启动】纳斯达克 100 距历史高点已跌 {a['dd']:.1%}。")
            if not cfg.get("base"):
                lines.append(f"  ⚠️ 请把你今天的{src}总额填进仓库 config.json 的 base，之后邮件会直接写金额。")
        elif t == "tier":
            amt = _money(a["amount"])
            what = f"{amt}" if amt else f"基数的 {a['pct']}%"
            lines.append(f"【路线二新档 {'/'.join(map(str, a['tiers']))}%】卖出{src} {what} 换{dst}，"
                         f"分 {r['tranches']} 周买完（本轮累计 {a['cum_pct']}%）。")
        elif t == "tranche":
            amt = _money(a["amount"])
            what = f"{amt}" if amt else f"基数的 {a['pct']:.2f}%"
            lines.append(f"【本周买入 第 {a['n']}/{a['of']} 份】用{src}换{dst} {what}。")
        elif t == "crash_end":
            lines.append(f"【路线二结束】已涨回距高点 {r['recover_at']:.0%} 以内。之后每月新钱改为 "
                         + fmt(fmt_alloc(r["after_crash"], r)) + "。")
            if a.get("pending_dropped"):
                lines.append("  未买完的份额不再继续。")
        elif t == "transition_start":
            lines.append(f"【进入过渡】已满 {r['transition_after_months']} 个月没跌到 {r['crash_at']:.0%}，"
                         f"接下来每 {r['transition_every_months']} 个月调整一次新钱分配。")
        elif t == "transition_move":
            lines.append(f"【过渡第 {a['coin']}/{a['of']} 步】这次加到{a['to']}，本月起新钱按下面的分配。")
    if lines:
        lines = ["—— 今天要做的 ——"] + lines
    else:
        lines = ["今日无需操作。"]
    m = market or {}
    c1 = m.get("chg_1d")
    tag = "【需操作】" if need_action else ""
    title = (f"{tag}纳指 {close:,.0f}" + (f"（{c1:+.2%}）" if c1 is not None else "")
             + f" · 距高点 -{dd:.1%}" + ("" if need_action else " · 无需操作"))
    head = [f"日期：{acts[0]['date']}（美东收盘）",
            f"纳斯达克 100 收盘：{close:,.2f}"]
    for k, name in (("chg_1d", "当日"), ("chg_5d", "近 5 个交易日"), ("chg_1m", "近 1 个月")):
        if m.get(k) is not None:
            head.append(f"{name}涨跌：{m[k]:+.2%}")
    head += [f"历史最高收盘：{state['ath']:,.2f}（{state['ath_date']}）",
             f"距高点回撤：{dd:.2%}"]
    marks = sorted({lo for lo, _ in r["table"] if lo > 0} | {t / 100 for t in r["tiers"]} | {r["crash_at"]})
    nxt = next((t for t in marks if t > dd), None)
    if nxt is not None:
        lvl = state["ath"] * (1 - nxt)
        head.append(f"下一档：跌到 {nxt:.0%}（指数 {lvl:,.0f}），还要再跌 {1 - lvl / close:.1%}")
    ra = r["recover_at"]
    if state["mode"] == "crash" and dd > ra:
        lvl = state["ath"] * (1 - ra)
        head.append(f"涨回距高点 {ra:.0%} 以内（指数 {lvl:,.0f}）还要涨 {lvl / close - 1:.1%}")
    head.append(f"当前状态：{MODE_CN[state['mode']]}")
    return title, "\n".join(head) + "\n\n" + "\n".join(lines) + FOOT


def send(title: str, body: str) -> bool:
    user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("MAIL_TO") or user
    if not (user and pw):
        print("[dry run] 未配置邮箱，只打印：\n" + title + "\n" + body)
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"], msg["To"] = user, to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())
    return True
