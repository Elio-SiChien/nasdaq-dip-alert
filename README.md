# 纳指定投提醒模板 · Nasdaq Dip Alert Template

每个美股交易日收盘后，自动看一眼纳斯达克 100 指数离历史最高点跌了多少，按**你自己定的规则**给你发一封邮件。免费、不用开电脑、手机就能搭好。

> ⚠️ 这只是一个提醒工具，不是投资建议。它不会下单、不碰你的账户。规则是你自己定的，买不买、买多少，最后都由你自己决定。

## 它会发什么邮件

- **每个交易日**：行情日报（收盘、当日/5 日/1 个月涨跌、距历史高点多少、离下一档还差多少）。没事做时标题写"无需操作"。
- **每月第一个交易日**：按你的规则，告诉你当月新钱怎么分（标题带【需操作】）。
- **大跌时**：跌到你设的线（默认 20%），当天提醒你按档位把一部分底仓换成纳指，分几周买完。
- **出问题时**：取不到数据、数据异常，会发告警，不会给操作建议。

## 手机 10 分钟搭好

1. **复制模板**：在本页点绿色按钮 **Use this template → Create a new repository**，建议选 **Private**（你的金额不会公开）。
2. **生成 Gmail 应用专用密码**：手机浏览器打开 <https://myaccount.google.com/apppasswords> → 起个名字 → 复制 16 位密码。（打不开就先在 Google 账号里开两步验证。注意：不是你的 Gmail 登录密码。）
3. **填 3 个 Secret**：你的新仓库 → **Settings → Secrets and variables → Actions** → 往下拉到 **Repository secrets** → 点 **New repository secret**，加三次：
   | Name | Secret |
   |---|---|
   | `GMAIL_USER` | 你的 Gmail 地址 |
   | `GMAIL_APP_PASSWORD` | 第 2 步的 16 位密码 |
   | `MAIL_TO` | 收提醒的邮箱（可以就是同一个 Gmail） |

   （不要点上面的 "Manage environment secrets"，那个程序读不到。手机上看不全就切"桌面版网站"。）
4. **跑第一次**：仓库 → **Actions** → 左边 **daily** → **Run workflow**。几十秒后你会收到"纳指提醒 · 已启动"的邮件。
5. **改成你的规则**：仓库里点 `config.json` → 铅笔图标编辑 → 改完点 **Commit changes**。

之后每个美股交易日的第二天早上（UTC 01:17，北京时间 09:17）自动运行。

## config.json 里能改什么

| 项 | 意思 | 默认 |
|---|---|---|
| `assets` | 你的几样资产叫什么 | 债券、标普、纳斯达克、黄金 |
| `table` | 每月新钱分配表：`[回撤下限, [各资产金额]]` | 跌 0/10/20/30% 各一档 |
| `avg_days` | 每月定档用几天平均收盘（避免一天偶然暴涨暴跌） | 5 |
| `crash_at` | 跌到多少启动"底仓换纳指" | 0.20 |
| `tiers` / `tier_pct` / `tranches` | 换仓档位（%）、每档换底仓的百分之几、分几周买完 | 20/30/40/50、20%、3 周 |
| `route2_from` / `route2_to` | 从哪样换到哪样 | 债券 → 纳斯达克 |
| `recover_at` | 涨回距高点多少以内算结束（每月第一个交易日判断） | 0.10 |
| `after_crash` | 结束后的新钱分配 | 300/300/300/100 |
| `transition_after_months` / `transition_every_months` / `transition_steps` | 很久没大跌时，逐步调整新钱分配（0 = 不用） | 18 个月后每 3 个月一步 |
| `base` | 底仓总额。第一次跌到 `crash_at` 时邮件会提醒你填，填了邮件就写具体金额 | null |

改完想先看看效果？电脑上可以用历史行情回放：

```bash
pip install -r requirements.txt
python replay.py 2021-06-01 2024-03-28 10000
```

## 常见问题

- **27,943 是一股的价格吗？** 不是，是纳斯达克 100 指数的点数。程序只看百分比，跟你买的基金价格无关。
- **周末、假日会发吗？** 不会，没有新收盘就不发。
- **想再发一封测试邮件？** Actions → daily → Run workflow，勾选 test。
- **数据从哪来？** Yahoo Finance（yfinance），失败时换 Stooq。

---

## English (short)

A free GitHub Actions bot that emails you after every US trading day: Nasdaq-100 close, distance from its all-time high, and — on the first trading day of each month or on big drops — what **your own rules** say to do with new money. It never trades. Not financial advice.

Setup (works from a phone): **Use this template** (private) → create a Gmail **app password** → add repo secrets `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `MAIL_TO` → **Actions → daily → Run workflow** → edit `config.json` to your rules.

MIT License.
