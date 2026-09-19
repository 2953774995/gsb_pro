#!/usr/bin/env python3
"""Convenience launcher so `./sqlq-cli.py` works without installation."""

import sys

from sqlq.cli import main

if __name__ == "__main__":
    sys.exit(main())
