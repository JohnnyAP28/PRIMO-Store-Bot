from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from discord_marketplace_bot.cli import main


if __name__ == "__main__":
    sys.argv = [sys.argv[0], "run"]
    main()
