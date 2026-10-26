"""Entry point that works under `python -I`.

Isolated mode adds no paths to sys.path (not even this folder), which keeps a stray file in a data
directory from being imported. This adds only the repo folder, explicitly.

    python -I run.py measure-reprints --hours 6
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline.cli import main  # noqa: E402

sys.exit(main())
