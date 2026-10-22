#!/usr/bin/env python3
"""Entry point: python mail_tool.py --help"""

import sys

from mailtool.cli import main

if __name__ == "__main__":
    sys.exit(main())
