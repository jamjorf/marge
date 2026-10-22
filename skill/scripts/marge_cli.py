#!/usr/bin/env python3
"""Run the bundled marge calculator.

    python3 marge_cli.py check    -p positions.csv -s securities.csv -b baskets.csv -c config.toml
    python3 marge_cli.py run      -p positions.csv -s securities.csv -b baskets.csv -c config.toml
    python3 marge_cli.py leverage -p positions.csv ... --equity 10000000
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from marge.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
