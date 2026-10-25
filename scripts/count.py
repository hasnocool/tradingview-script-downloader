#!/usr/bin/env python3
"""Count downloaded Pine files and their total size."""

import argparse
import os
from pathlib import Path


def get_directory_size(directory: Path) -> int:
    return sum(path.stat().st_size for path in directory.rglob("*.pine"))


def format_size(size: float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.2f} {units[index]}"


def main() -> int:
    shared = Path(
        os.environ.get(
            "TRADING_SCRIPT_DOWNLOADS",
            Path.home() / "Projects" / "TradingScriptDownloads",
        )
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory",
        nargs="?",
        default=str(shared / "Pine" / "TradingView"),
        help="directory to inspect (default: shared TradingView archive)",
    )
    args = parser.parse_args()
    directory = Path(args.directory).expanduser()

    if not directory.is_dir():
        parser.error(f"directory does not exist: {directory}")

    file_count = sum(1 for _ in directory.rglob("*.pine"))
    directory_size = get_directory_size(directory)
    print(f"The number of .pine files in '{directory}' is: {file_count}")
    print(f"The total size of those files is: {format_size(directory_size)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
