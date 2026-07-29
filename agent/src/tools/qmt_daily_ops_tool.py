"""QMT Daily Operations Tool.

Fetches today's orders and trades from QMT terminal via subprocess bridge.
Returns structured JSON suitable for analysis.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)


class QMTDailyOpsTool(BaseTool):
    """Query QMT daily trading operations (orders and trades)."""

    name = "get_qmt_daily_ops"
    description = (
        "Fetch today's orders and trades from the QMT terminal. "
        "Requires QMT (miniQMT) running and connected. Returns JSON with order/trade records "
        "for analysis purposes."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    repeatable = True
    is_readonly = True

    @classmethod
    def check_available(cls) -> bool:
        """Check if QMT bridge is available."""
        qmt_dir = os.getenv("QMT_DIR") or os.getenv("VIBE_TRADING_QMT_DIR")
        if not qmt_dir:
            return False
        python_exe = os.path.join(qmt_dir, "bin.x64", "pythonw.exe")
        return os.path.isfile(python_exe)

    def __init__(self) -> None:
        super().__init__()
        self.qmt_dir = os.getenv("QMT_DIR") or os.getenv("VIBE_TRADING_QMT_DIR") or r"D:\software\miniQMT"
        self.session_id = int(os.getenv("QMT_SESSION", "62030"))
        self.userdata_dir = os.path.join(self.qmt_dir, "userdata_mini")
        self.bridge_path = str(Path(__file__).parent / "qmt_ops_bridge.py")

    def _call_bridge(self, request: dict) -> Optional[Dict]:
        """Call the QMT bridge subprocess and parse response."""
        if not self.qmt_dir:
            logger.error("QMT_DIR not configured")
            return None

        python_exe = os.path.join(self.qmt_dir, "bin.x64", "pythonw.exe")
        qmt_cwd = os.path.join(self.qmt_dir, "bin.x64")

        if not os.path.exists(python_exe):
            logger.error(f"QMT Python not found: {python_exe}")
            return None

        try:
            proc = subprocess.Popen(
                [python_exe, self.bridge_path],
                cwd=qmt_cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            out, err = proc.communicate(input=json.dumps(request), timeout=30)
        except subprocess.TimeoutExpired:
            logger.warning("QMT bridge timed out")
            return None
        except Exception as e:
            logger.error(f"QMT bridge error: {e}")
            return None

        if proc.returncode != 0:
            logger.warning(f"QMT bridge exited with code {proc.returncode}: {err}")
            return None

        if not out.strip():
            logger.warning("QMT bridge returned empty output")
            return None

        try:
            return json.loads(out)
        except json.JSONDecodeError as e:
            logger.error(f"QMT bridge JSON parse error: {e}")
            return None

    def execute(self, **kwargs: Any) -> str:
        """Execute the QMT operations fetch."""
        request = {
            "action": "get_operations",
            "userdata_dir": self.userdata_dir,
            "session_id": self.session_id,
        }

        result = self._call_bridge(request)
        if result is None:
            return json.dumps({
                "status": "error",
                "error": "Failed to retrieve QMT data. Please ensure QMT is running and configured.",
            }, ensure_ascii=False)

        if "error" in result:
            return json.dumps({
                "status": "error",
                "error": result["error"],
            }, ensure_ascii=False)

        return json.dumps({
            "status": "ok",
            "data": result,
            "order_count": len(result.get("orders", [])),
            "trade_count": len(result.get("trades", [])),
        }, ensure_ascii=False, indent=2)