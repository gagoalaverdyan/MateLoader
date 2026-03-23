from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir():
    sys.path.insert(0, str(SRC))

from mateloader.cli import legacy_main


if __name__ == "__main__":
    raise SystemExit(legacy_main())
