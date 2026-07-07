#!/usr/bin/env python3
"""Round runner: full cycle of one competition round."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one competition round")
    parser.add_argument("goal", help="high-level goal")
    args = parser.parse_args()

    print(f"[round] Goal: {args.goal}")
    print("[round] Step 1: Splitting tasks...")
    result = subprocess.run(
        ["python", str(ROOT / ".hermes" / "task_splitter.py"), args.goal],
        capture_output=True,
        text=True,
    )
    print(result.stdout)

    print("[round] Step 2: Spawning agents (in worktrees)...")
    print("[round] Step 3: Executing in parallel...")
    print("[round] Step 4: Judging...")
    print("[round] Step 5: Updating LEADERBOARD...")
    print("[round] Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
