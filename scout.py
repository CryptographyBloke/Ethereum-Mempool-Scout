"""Backwards-compatible entry point.

v1 of this project was a single script.  It is now the ``mempool_scout`` package:

    python -m mempool_scout collect --wss wss://YOUR_NODE
    python -m mempool_scout serve
    python -m mempool_scout report

Running ``python scout.py`` with no arguments starts the collector using the
SCOUT_WSS_URL environment variable.
"""

import sys

from mempool_scout.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["collect"]))
