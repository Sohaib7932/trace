#!/usr/bin/env python3
"""Compatibility entry point for the shared primary-session-only Claude adapter."""

import runpy
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "scripts"))
sys.argv = [str(root / "scripts/agent_session_logs.py"), "hook", "--agent", "claude"]
runpy.run_path(sys.argv[0], run_name="__main__")
