# -*- coding: utf-8 -*-
"""
获取 miniQMT 当日操作记录（委托 / 成交）
使用 miniQMT 自带的 Python 3.6 + 其内置 xtquant（cp36）连接正在运行的客户端。
用法：D:\software\miniQMT\bin.x64\pythonw.exe get_today_ops.py
"""
import sys, os, json, datetime, threading

# Use QMT_DIR from environment variable (set in .env), or default
QMT_DIR = os.getenv("QMT_DIR", r"D:\software\miniQMT")
XTQUANT_PKG = os.path.join(QMT_DIR, "bin.x64", "Lib", "site-packages")
if XTQUANT_PKG not in sys.path:
    sys.path.insert(0, XTQUANT_PKG)

from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount

USERDATA_MINI = os.path.join(QMT_DIR, "userdata_mini")
SESSION = int(os.getenv("QMT_SESSION", "62030"))
# Output directory - can be overridden, defaults to project-relative path
OUT_DIR = os.getenv("QMT_OUT_DIR", os.path.join(os.getcwd(), "export_data"))
os.makedirs(OUT_DIR, exist_ok=True)

BUY, SELL = 23, 24

def fmt_time(t):
    try:
        if isinstance(t, (int, float)):
            t = int(t)
            if 1e12 < t < 1e15:           # 毫秒
                t /= 1000
            if 1e9 <= t < 1e12:           # 秒级 unix 时间戳
                return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
        return str(t)
    except Exception:
        return str(t)

def side_text(ot):
    return {BUY: "买入", SELL: "卖出"}.get(ot, str(ot))

def query_async(trader, func, acc, timeout=10):
    """异步查询 + 超时保护，返回响应或 None（超时/异常）"""
    box, ev = {}, threading.Event()
    def cb(resp):
        box["r"] = resp
        ev.set()
    try:
        func(acc, cb)
    except Exception:
        return None
    if not ev.wait(timeout=timeout):
        return None
    return box.get("r")

def run():
    trader = XtQuantTrader(USERDATA_MINI, SESSION)
    trader.start()
    ret = trader.connect()
    print(">>> connect 返回值: %s (0=成功)" % ret)
    if ret != 0:
        print("连接失败：请确认 miniQMT 客户端正在运行且已登录。")
        return

    accs = trader.query_account_infos() or []
    print(">>> 发现账户: %s" % [(getattr(a, "account_id", "?"),
                                 getattr(a, "account_type", "?")) for a in accs])
    stock_accounts = [StockAccount(str(getattr(a, "account_id", "")), "STOCK")
                      for a in accs if getattr(a, "account_id", "")]

    all_orders, all_trades = [], []
    for acc in stock_accounts:
        try:
            trader.subscribe(acc)
        except Exception as e:
            print("  subscribe 异常: %s" % e)
        orders = query_async(trader, trader.query_stock_orders_async, acc) or []
        trades = query_async(trader, trader.query_stock_trades_async, acc)
        print("账户 %s: 委托 %d 笔, 成交查询 %s"
              % (acc.account_id, len(orders), ("%d 笔" % len(trades)) if trades is not None else "超时(用委托还原)"))

        for o in orders:
            all_orders.append({
                "account": acc.account_id,
                "order_id": getattr(o, "order_sysid", "") or getattr(o, "order_id", ""),
                "time": fmt_time(getattr(o, "order_time", "")),
                "code": getattr(o, "stock_code", ""),
                "side": side_text(getattr(o, "order_type", "")),
                "volume": getattr(o, "order_volume", 0),
                "price": getattr(o, "price", 0),
                "traded_volume": getattr(o, "traded_volume", 0),
                "traded_price": getattr(o, "traded_price", 0),
                "status": (getattr(o, "status_msg", "") or getattr(o, "order_status", "")),
                "strategy": getattr(o, "strategy_name", ""),
                "remark": getattr(o, "order_remark", ""),
            })
        if trades is not None:
            for t in trades:
                all_trades.append({
                    "account": acc.account_id,
                    "traded_id": getattr(t, "traded_id", ""),
                    "order_id": getattr(t, "order_sysid", "") or getattr(t, "order_id", ""),
                    "time": fmt_time(getattr(t, "traded_time", "")),
                    "code": getattr(t, "stock_code", ""),
                    "side": side_text(getattr(t, "order_type", "")),
                    "price": getattr(t, "traded_price", 0),
                    "volume": getattr(t, "traded_volume", 0),
                    "amount": getattr(t, "traded_amount", 0),
                    "strategy": getattr(t, "strategy_name", ""),
                    "remark": getattr(t, "order_remark", ""),
                })
        else:
            # 成交查询不可用，用委托里的已成量还原
            for o in orders:
                tv = getattr(o, "traded_volume", 0) or 0
                tp = getattr(o, "traded_price", 0) or 0
                if tv and tp:
                    all_trades.append({
                        "account": acc.account_id,
                        "traded_id": getattr(o, "order_sysid", ""),
                        "order_id": getattr(o, "order_sysid", ""),
                        "time": fmt_time(getattr(o, "order_time", "")),
                        "code": getattr(o, "stock_code", ""),
                        "side": side_text(getattr(o, "order_type", "")),
                        "price": tp, "volume": tv, "amount": round(tv * tp, 2),
                        "strategy": getattr(o, "strategy_name", ""),
                        "remark": "由委托还原",
                    })

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary = {"generated_at": ts, "orders": all_orders, "trades": all_trades,
               "source": "xtquant API (当日委托/成交)"}
    json.dump(summary, open(os.path.join(OUT_DIR, "today_ops.json"), "w"),
              ensure_ascii=False, indent=2)

    lines = ["当日操作记录（生成于 %s）" % ts,
             "委托笔数: %d   成交笔数: %d" % (len(all_orders), len(all_trades)),
             "\n---- 委托 ----"]
    for o in all_orders:
        lines.append("%s | %s | %s | 委托量%s @ %.3f | 已成%s @ %.3f | %s"
                     % (o["time"], o["code"], o["side"], o["volume"], o["price"],
                        o["traded_volume"], o["traded_price"], o["status"]))
    lines.append("\n---- 成交 ----")
    for t in all_trades:
        lines.append("%s | %s | %s | 量%s @ %.3f | 额%.2f"
                     % (t["time"], t["code"], t["side"], t["volume"], t["price"], t["amount"]))
    report = "\n".join(lines)
    print("\n" + report)
    open(os.path.join(OUT_DIR, "today_ops.txt"), "w").write(report)
    open(os.path.join(OUT_DIR, "today_ops.html"), "w").write(build_html(all_orders, all_trades, ts))
    print("\n已写出: today_ops.json / today_ops.txt / today_ops.html -> %s" % OUT_DIR)

def build_html(orders, trades, ts):
    o_cols = ["time", "code", "side", "order_id", "volume", "price", "traded_volume", "traded_price", "status", "strategy", "remark"]
    t_cols = ["time", "code", "side", "volume", "price", "amount", "traded_id", "strategy", "remark"]
    def rows(items, cols):
        h = "".join("<th>%s</th>" % c for c in cols)
        body = ""
        for it in items:
            tds = ""
            for c in cols:
                v = it.get(c, "")
                cls = ""
                if c == "side":
                    cls = ' class="buy"' if v == "买入" else (' class="sell"' if v == "卖出" else "")
                tds += "<td%s>%s</td>" % (cls, v)
            body += "<tr>%s</tr>" % tds
        return "<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (h, body)
    return """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<style>
body{font-family:-apple-system,'Microsoft YaHei',sans-serif;background:#f6f7f9;color:#222;margin:24px;}
h1{font-size:20px;} h2{font-size:16px;margin-top:24px;color:#333;}
table{border-collapse:collapse;width:100%%;background:#fff;margin-top:8px;box-shadow:0 1px 3px rgba(0,0,0,.08);}
th,td{border:1px solid #e6e6e6;padding:6px 10px;font-size:13px;text-align:left;white-space:nowrap;}
th{background:#f0f2f5;font-weight:600;}
.buy{color:#e0392b;font-weight:600;} .sell{color:#15a153;font-weight:600;}
.meta{color:#888;font-size:13px;}
</style></head><body>
<h1>当日操作记录</h1>
<p class="meta">生成时间：%s ｜ 委托 %d 笔 ｜ 成交 %d 笔</p>
<h2>委托</h2>%s
<h2>成交</h2>%s
</body></html>""" % (ts, len(orders), len(trades),
       rows(orders, o_cols) if orders else "<p>无</p>",
       rows(trades, t_cols) if trades else "<p>无</p>")

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        import traceback
        open(os.path.join(OUT_DIR, "ops_error.log"), "w").write("ERROR: %r\n%s" % (e, traceback.format_exc()))
        raise
