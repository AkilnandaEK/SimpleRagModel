"""Pytest configuration and shared fixtures for the tracing + benchmark test suites."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the repo root is on sys.path when running pytest from any directory.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def config():
    from benchmark.config import load_config_from_env
    return load_config_from_env()
