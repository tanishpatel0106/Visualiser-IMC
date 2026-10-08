"""Prepare lossless, NVDA-only day-0 chunks from hydrated price/trade CSVs."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.nvda_preparation import prepare

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", required=True, type=Path)
    parser.add_argument("--trades", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-rows", type=int, default=10000)
    args = parser.parse_args()
    if args.max_rows < 1:
        parser.error("--max-rows must be positive")
    prepare(args.prices, args.trades, args.output, args.max_rows)
