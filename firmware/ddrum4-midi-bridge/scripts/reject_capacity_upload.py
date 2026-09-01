#!/usr/bin/env python3
"""Reject uploads from the compile-only Uno capacity environment."""
from __future__ import annotations

import sys


print(
    "uno_capacity is compile-only and cannot upload firmware; use the reviewed live environment after promotion",
    file=sys.stderr,
)
raise SystemExit(2)
