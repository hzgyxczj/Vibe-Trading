"""Bridge for querying QMT daily operations (orders & trades).
Run under QMT's bundled Python 3.6 via subprocess.

Reads JSON request from stdin, queries xtquant, writes JSON response to stdout.
"""

import sys
import os
import json
import datetime
import threading

# Insert xtquant path before any imports
QMTPATH = os.path.join(os.getcwd(), "Lib", "site-packages")
if QMTPATH not in sys.path:
    sys.path.insert(0, QMTPATH)

from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount

BUY, SELL = 23, 24


def fmt_time(t):
    try:
        if isinstance(t, (int, float)):
            t = int(t)
            if 1e12 < t < 1e15:  # milliseconds
                t /= 1000
            if 1e9 <= t < 1e12:  # seconds
                return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
        return str(t)
    except Exception:
        return str(t)


def side_text(ot):
    return {BUY: "买入", SELL: "卖出"}.get(ot, str(ot))


def query_async(trader, func, acc, timeout=10):
    """Async query with timeout protection."""
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


def get_operations(userdata_dir, session_id, timeout=30):
    """Fetch orders and trades from QMT."""
    trader = XtQuantTrader(userdata_dir, session_id)
    trader.start()
    ret = trader.connect()
    if ret != 0:
        return {"error": f"connect failed, ret={ret}, please check QMT terminal"}

    accs = trader.query_account_infos() or []
    if not accs:
        return {"error": "no accounts found"}

    stock_accounts = [
        StockAccount(str(getattr(a, "account_id", "")), "STOCK")
        for a in accs if getattr(a, "account_id", "")
    ]

    all_orders, all_trades = [], []

    for acc in stock_accounts:
        try:
            trader.subscribe(acc)
        except Exception as e:
            print(f"subscribe error: {e}", file=sys.stderr)

        orders = query_async(trader, trader.query_stock_orders_async, acc) or []
        trades = query_async(trader, trader.query_stock_trades_async, acc)

        for o in orders:
            all_orders.append({
                "account": getattr(o, "account_id", ""),
                "order_id": getattr(o, "order_sysid", "") or getattr(o, "order_id", ""),
                "time": fmt_time(getattr(o, "order_time", "")),
                "code": getattr(o, "stock_code", ""),
                "side": side_text(getattr(o, "order_type", "")),
                "volume": getattr(o, "order_volume", 0),
                "price": getattr(o, "price", 0),
                "traded_volume": getattr(o, "traded_volume", 0),
                "traded_price": getattr(o, "traded_price", 0),
                "status": getattr(o, "status_msg", "") or getattr(o, "order_status", ""),
                "strategy": getattr(o, "strategy_name", ""),
                "remark": getattr(o, "order_remark", ""),
            })

        if trades is not None:
            for t in trades:
                all_trades.append({
                    "account": getattr(t, "account_id", ""),
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
            # Recover trades from orders where available
            for o in orders:
                tv = getattr(o, "traded_volume", 0) or 0
                tp = getattr(o, "traded_price", 0) or 0
                if tv and tp:
                    all_trades.append({
                        "account": getattr(o, "account_id", ""),
                        "traded_id": getattr(o, "order_sysid", ""),
                        "order_id": getattr(o, "order_sysid", ""),
                        "time": fmt_time(getattr(o, "order_time", "")),
                        "code": getattr(o, "stock_code", ""),
                        "side": side_text(getattr(o, "order_type", "")),
                        "price": tp,
                        "volume": tv,
                        "amount": round(tv * tp, 2),
                        "strategy": getattr(o, "strategy_name", ""),
                        "remark": "recovered from order",
                    })

    trader.stop()
    return {
        "orders": all_orders,
        "trades": all_trades,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def main():
    params = json.loads(sys.stdin.read())
    action = params.get("action")
    userdata_dir = params.get("userdata_dir")
    session_id = params.get("session_id", 62030)

    if action == "get_operations":
        try:
            result = get_operations(userdata_dir, session_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
            sys.exit(1)
    else:
        print(json.dumps({"error": f"unknown action: {action}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()