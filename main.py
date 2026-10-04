"""开发时的入口：无需先安装包，直接 python3 main.py --demo。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from weekend_agent.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
