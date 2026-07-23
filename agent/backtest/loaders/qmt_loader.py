"""QMT loader: A-share OHLCV via xtquant (QMT terminal must be running).

Uses a subprocess bridge to call QMT's bundled Python 3.6 (which has the
``xtquant`` package with compiled ``.pyd`` extensions). The project itself
runs under Python 3.12, which is incompatible with xtquant's binary
extensions (max cp311), so we delegate the actual data fetch to QMT's
Python via ``subprocess.Popen``.

Requirements:
  - QMT terminal (XtMiniQmt.exe) running and connected.
  - ``qmt_dir`` configured in ``~/.vibe-trading/data-bridge/config.yaml``::

      qmt_dir: "D:/software/迅投极速策略交易系统交易终端 华鑫证券QMT实盘"

  - The ``bin.x64`` subdirectory must contain ``pythonw.exe`` and
    ``Lib/site-packages/xtquant``.

Scope: A-share OHLCV (沪/深/京). Supports 1m/5m/15m/30m/1H/4H/1D/1W.
Real-time tick data is not exposed through this loader.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml

from backtest.loaders.base import cached_loader_fetch, validate_date_range, validate_ohlc
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path.home() / ".vibe-trading" / "data-bridge"
_CONFIG_PATH = _CONFIG_DIR / "config.yaml"

# Project intervals that QMT supports natively.
_QMT_INTERVALS = {"1m", "5m", "15m", "30m", "1H", "1D", "1W"}

# Resampling rules for intervals QMT doesn't have natively.
_RESAMPLE_RULES = {
    "4H": "4h",
}
_OHLCV_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}

# Timeout for the subprocess call (seconds). QMT's xtdata can hang
# indefinitely if the terminal is running but the data server is
# unreachable.
_SUBPROCESS_TIMEOUT = 30


def _load_qmt_dir() -> str | None:
    """Read ``qmt_dir`` from the Data Bridge config."""
    if not _CONFIG_PATH.exists():
        return None
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    qmt_dir = config.get("qmt_dir")
    if isinstance(qmt_dir, str) and qmt_dir.strip():
        return str(Path(qmt_dir.strip()).expanduser())
    return None


def _is_a_share(code: str) -> bool:
    """Accept ``.SH/.SZ/.BJ`` suffix or bare 6-digit ticker."""
    upper = code.upper()
    if upper.endswith((".SH", ".SZ", ".BJ")):
        return True
    return len(code) == 6 and code.isdigit()


def _normalize_qmt_symbol(code: str) -> str:
    """Ensure the symbol has a ``.SH/.SZ/.BJ`` suffix for QMT.

    QMT requires the exchange suffix. Bare 6-digit codes are resolved
    by prefix: 6xx→SH, 0xx/3xx→SZ, 4xx/8xx→BJ.
    """
    upper = code.upper()
    if upper.endswith((".SH", ".SZ", ".BJ")):
        return upper
    if len(code) == 6 and code.isdigit():
        if code[0] == "6":
            return f"{code}.SH"
        elif code[0] in ("0", "3"):
            return f"{code}.SZ"
        elif code[0] in ("4", "8"):
            return f"{code}.BJ"
    return code


@register
class DataLoader:
    """QMT-backed A-share OHLCV loader (subprocess bridge to xtquant)."""

    name = "qmt"
    markets = {"a_share"}
    requires_auth = False

    def __init__(self) -> None:
        self._qmt_dir: str | None = None
        self._bridge_script: str | None = None

    def _ensure_config(self) -> None:
        if self._qmt_dir is not None:
            return
        self._qmt_dir = _load_qmt_dir()
        if self._qmt_dir:
            self._bridge_script = str(
                Path(__file__).parent / "qmt_bridge.py"
            )

    def is_available(self) -> bool:
        """Available if QMT is configured and the bundled Python exists."""
        qmt_dir = _load_qmt_dir()
        if not qmt_dir:
            return False
        python_exe = os.path.join(qmt_dir, "bin.x64", "pythonw.exe")
        return os.path.isfile(python_exe)

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch A-share OHLCV via QMT's xtquant.

        Args:
            codes: Symbol list (``.SH/.SZ/.BJ`` suffix or bare 6-digit).
            start_date: YYYY-MM-DD.
            end_date: YYYY-MM-DD.
            interval: ``1m/5m/15m/30m/1H/4H/1D/1W``.
            fields: Ignored.

        Returns:
            Mapping symbol -> OHLCV DataFrame.
        """
        validate_date_range(start_date, end_date)
        self._ensure_config()

        if not self._qmt_dir:
            logger.warning("qmt: qmt_dir not configured in %s", _CONFIG_PATH)
            return {}

        # 4H is resampled from 1H in the loader, so accept it here.
        if interval not in _QMT_INTERVALS and interval != "4H":
            logger.warning("qmt: unsupported interval %r", interval)
            return {}

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            if not _is_a_share(code):
                logger.debug("qmt: skipping non-A-share symbol %s", code)
                continue
            try:
                df = cached_loader_fetch(
                    source=self.name,
                    symbol=code,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda c=code: self._fetch_one(c, start_date, end_date, interval),
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:
                logger.warning("qmt failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self, code: str, start_date: str, end_date: str, interval: str,
    ) -> Optional[pd.DataFrame]:
        """Call the QMT bridge script via subprocess and parse the result."""
        qmt_symbol = _normalize_qmt_symbol(code)
        request = {
            "codes": [qmt_symbol],
            "start_date": start_date,
            "end_date": end_date,
            "interval": interval,
        }

        python_exe = os.path.join(self._qmt_dir, "bin.x64", "pythonw.exe")
        qmt_cwd = os.path.join(self._qmt_dir, "bin.x64")

        try:
            proc = subprocess.Popen(
                [python_exe, self._bridge_script],
                cwd=qmt_cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            out, err = proc.communicate(
                input=json.dumps(request),
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            logger.warning("qmt: subprocess timed out for %s (terminal running?)", code)
            return None
        except Exception as exc:
            logger.warning("qmt: subprocess error for %s: %s", code, exc)
            return None

        if proc.returncode != 0:
            logger.warning("qmt: bridge exited %d for %s: %s", proc.returncode, code, err)
            return None

        if not out.strip():
            logger.warning("qmt: empty output for %s", code)
            return None

        try:
            data = json.loads(out)
        except json.JSONDecodeError as exc:
            logger.warning("qmt: JSON parse error for %s: %s", code, exc)
            return None

        if "error" in data:
            logger.warning("qmt: bridge error for %s: %s", code, data["error"])
            return None

        symbol_key = qmt_symbol
        if symbol_key not in data:
            logger.debug("qmt: no data for %s", code)
            return None

        entry = data[symbol_key]
        df = self._build_dataframe(entry)
        if df is None or df.empty:
            return None

        # Resample 4H from 1H if needed
        if interval == "4H":
            df = self._resample(df, "4h", code)

        # Clip to requested date range (inclusive end-of-day)
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        df = df[(df.index >= start) & (df.index <= end)]
        return df if not df.empty else None

    @staticmethod
    def _build_dataframe(entry: dict) -> Optional[pd.DataFrame]:
        """Reconstruct a DataFrame from the JSON bridge response."""
        cols = entry.get("columns", [])
        idx = entry.get("index", [])
        values = entry.get("data", [])

        if not cols or not idx or not values:
            return None

        df = pd.DataFrame(values, columns=cols, index=pd.to_datetime(idx))
        df.index.name = "trade_date"

        # Select and normalize OHLCV columns
        ohlcv = []
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
                ohlcv.append(col)
        if not {"open", "high", "low", "close"}.issubset(set(ohlcv)):
            logger.warning("qmt: missing OHLC columns in response: %s", cols)
            return None

        if "volume" not in df.columns:
            df["volume"] = 0.0

        df = df[["open", "high", "low", "close", "volume"]]
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = validate_ohlc(df)
        for col in df.columns:
            df[col] = df[col].astype("float64")
        return df.sort_index() if not df.empty else None

    @staticmethod
    def _resample(df: pd.DataFrame, rule: str, symbol: str) -> pd.DataFrame:
        """Resample OHLCV to a coarser interval."""
        resampled = df.resample(rule).agg(_OHLCV_AGG)
        resampled = resampled.dropna(subset=["open", "high", "low", "close"])
        resampled.index.name = df.index.name
        return resampled
