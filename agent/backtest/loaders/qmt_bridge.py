"""Bridge script run by QMT's bundled Python 3.6 to fetch data via xtquant.

Called as a subprocess by ``qmt_loader.py`` (which runs under Python 3.12).
Reads a JSON request from stdin, fetches data via ``xtdata.get_market_data_ex``,
and writes a JSON response to stdout.

Must be invoked with ``cwd`` set to the QMT ``bin.x64`` directory so that
``Lib/site-packages/xtquant`` is on the import path.
"""

import sys
import os
import json
import datetime

# Make xtquant importable when cwd is the QMT bin.x64 directory.
sys.path.insert(0, os.path.join(os.getcwd(), "Lib", "site-packages"))


def _ts_to_str(ts):
    """Convert a QMT index value to 'YYYY-MM-DD HH:MM:SS' string.

    QMT xtdata returns index values in different formats depending on the
    period:
    - Daily/weekly: Int64Index with YYYYMMDD integers (e.g. 20250710)
    - Intraday: DatetimeIndex with millisecond timestamps
    """
    # pandas Timestamp
    if hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    # Get Python native value from numpy types
    val = ts.item() if hasattr(ts, "item") else ts
    if isinstance(val, (int, float)):
        s = str(int(val))
        # YYYYMMDD format (8 digits, daily/weekly bars)
        if len(s) == 8 and s.startswith("20"):
            return s[:4] + "-" + s[4:6] + "-" + s[6:8] + " 00:00:00"
        # YYYYMMDDHHMMSS format (14 digits, intraday)
        if len(s) == 14:
            return s[:4] + "-" + s[4:6] + "-" + s[6:8] + " " + s[8:10] + ":" + s[10:12] + ":" + s[12:14]
        # Millisecond timestamp
        if val > 1e12:
            return datetime.datetime.fromtimestamp(val / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
    return str(ts)


def main():
    params = json.loads(sys.stdin.read())

    from xtquant import xtdata

    # Ensure the xtdata client connects to the QMT terminal.
    # If ~/.xtquant config is missing (XtMiniQmt hasn't created it yet),
    # manually set the default port 58610 from xtdata.ini.
    client = xtdata.get_client()
    if client is not None:
        try:
            client.set_remote_addr("localhost", 58610)
            client.reset()
            succ, errmsg = client.connect_ex()
            if not succ:
                print(json.dumps({"error": "cannot connect to QMT terminal on port 58610: " + str(errmsg)}))
                return
        except Exception as exc:
            print(json.dumps({"error": "connection error: " + str(exc)}))
            return

    # Project interval -> QMT period
    interval_map = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1H": "1h",
        "1D": "1d",
        "1W": "1w",
    }

    interval = params.get("interval", "1D")
    period = interval_map.get(interval, "1d")

    # For 4H there is no native QMT period; fetch 1h and let the loader
    # resample.
    if interval == "4H":
        period = "1h"

    codes = params["codes"]
    start_time = params["start_date"].replace("-", "")
    end_time = params["end_date"].replace("-", "")

    # Download history data to local cache first (QMT requires this for
    # historical bars that aren't already cached).
    try:
        for code in codes:
            xtdata.download_history_data(code, period, start_time, end_time)
    except Exception:
        pass  # download may fail if data is already cached or not available

    try:
        data = xtdata.get_market_data_ex(
            stock_list=codes,
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=-1,
            dividend_type="none",
            fill_data=True,
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return

    result = {}
    if data is None:
        print(json.dumps(result))
        return

    for stock, df in data.items():
        if df is None or len(df) == 0:
            continue

        # Convert index to strings robustly
        idx = df.index.tolist()
        idx_str = [_ts_to_str(t) for t in idx]

        cols = list(df.columns)
        values = df.values.tolist()

        # Convert any non-serializable types (numpy scalars etc.)
        clean_values = []
        for row in values:
            clean_row = []
            for v in row:
                if isinstance(v, float):
                    clean_row.append(v)
                elif hasattr(v, "item"):
                    clean_row.append(v.item())
                elif v is None:
                    clean_row.append(None)
                else:
                    try:
                        clean_row.append(float(v))
                    except (TypeError, ValueError):
                        clean_row.append(str(v))
            clean_values.append(clean_row)

        result[stock] = {
            "columns": cols,
            "index": idx_str,
            "data": clean_values,
        }

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
