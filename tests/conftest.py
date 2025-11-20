"""Shared pytest fixtures and configuration."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Mock bittensor before any imports that use it
# This prevents the websockets.CloseCode import error
if "bittensor" not in sys.modules:
    mock_bt = MagicMock()
    mock_bt.logging = MagicMock()
    mock_bt.logging.debug = MagicMock()
    mock_bt.logging.info = MagicMock()
    mock_bt.logging.warning = MagicMock()
    mock_bt.logging.error = MagicMock()
    mock_bt.subtensor = MagicMock()
    mock_bt.wallet = MagicMock()
    sys.modules["bittensor"] = mock_bt

# Mock web3 if not already imported
if "web3" not in sys.modules:
    mock_web3 = MagicMock()
    sys.modules["web3"] = mock_web3
    sys.modules["web3.auto"] = MagicMock()
