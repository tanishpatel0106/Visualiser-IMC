"""Data loading and CSV parsing for IMC Prosperity trading data."""

import logging
import os
import re
from pathlib import Path
from typing import Optional

import pandas as pd

from backend.app.models.market import MarketSnapshot, TradePrint

logger = logging.getLogger(__name__)

# Expected column schemas
PRICE_REQUIRED_COLUMNS = {
    "day", "timestamp", "product",
    "bid_price_1", "bid_volume_1",
    "ask_price_1", "ask_volume_1",
    "mid_price",
}

PRICE_OPTIONAL_COLUMNS = {
    "bid_price_2", "bid_volume_2",
    "bid_price_3", "bid_volume_3",
    "ask_price_2", "ask_volume_2",
    "ask_price_3", "ask_volume_3",
    "profit_and_loss",
}

TRADE_REQUIRED_COLUMNS = {
    "timestamp", "buyer", "seller", "symbol", "currency", "price", "quantity",
}

# File-name patterns
PRICE_PATTERN = re.compile(r"prices_round_(\d+)_day_([-]?\d+)\.csv$")
TRADE_PATTERN = re.compile(r"trades_round_(\d+)_day_([-]?\d+)\.csv$")


class DataLoader:
    """Discovers and loads IMC Prosperity CSV datasets into domain models."""

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def discover_datasets(self, directory: str) -> dict[str, str]:
        """
        Walk *directory* and return a mapping of dataset keys to file paths.

        Keys have the form ``prices_round_{N}_day_{D}`` or
        ``trades_round_{N}_day_{D}``.  Values are absolute file paths.

        Parameters
        ----------
        directory : str
            Root directory to search (non-recursive by default, then
            falls back to recursive).

        Returns
        -------
        dict[str, str]
            Mapping of dataset key -> absolute file path.

        Raises
        ------
        FileNotFoundError
            If *directory* does not exist.
        """
        dir_path = Path(directory)
        if not dir_path.is_dir():
            raise FileNotFoundError(f"Dataset directory not found: {directory}")

        datasets: dict[str, str] = {}

        for root, _dirs, files in os.walk(dir_path):
            for fname in files:
                full_path = os.path.join(root, fname)

                price_match = PRICE_PATTERN.search(fname)
                if price_match:
                    rnd, day = price_match.group(1), price_match.group(2)
                    key = f"prices_round_{rnd}_day_{day}"
                    datasets[key] = full_path
                    continue

                trade_match = TRADE_PATTERN.search(fname)
                if trade_match:
                    rnd, day = trade_match.group(1), trade_match.group(2)
                    key = f"trades_round_{rnd}_day_{day}"
                    datasets[key] = full_path

        logger.info("Discovered %d dataset files in %s", len(datasets), directory)
        return datasets

    # ------------------------------------------------------------------
    # Schema validation
    # ------------------------------------------------------------------
    def validate_price_schema(self, df: pd.DataFrame) -> bool:
        """
        Validate that *df* contains all required price columns.

        Returns True on success.  Raises ``ValueError`` with a
        human-readable message listing missing columns on failure.
        """
        missing = PRICE_REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(
                f"Price CSV is missing required columns: {sorted(missing)}. "
                f"Found columns: {sorted(df.columns)}"
            )
        return True

    def validate_trade_schema(self, df: pd.DataFrame) -> bool:
        """
        Validate that *df* contains all required trade columns.

        Returns True on success.  Raises ``ValueError`` with a
        human-readable message listing missing columns on failure.
        """
        missing = TRADE_REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(
                f"Trade CSV is missing required columns: {sorted(missing)}. "
                f"Found columns: {sorted(df.columns)}"
            )
        return True

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------
    def load_price_csv(self, filepath: str) -> list[MarketSnapshot]:
        """
        Load a prices CSV file and return a list of ``MarketSnapshot``
        objects.

        Parameters
        ----------
        filepath : str
            Path to the CSV file.

        Returns
        -------
        list[MarketSnapshot]

        Raises
        ------
        FileNotFoundError
            If *filepath* does not exist.
        ValueError
            If the CSV schema is invalid.
        """
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"Price file not found: {filepath}")

        try:
            df = pd.read_csv(filepath, sep=";")
        except Exception:
            # Fall back to comma-separated
            df = pd.read_csv(filepath, sep=",")

        # Strip any leading/trailing whitespace from column names
        df.columns = [c.strip() for c in df.columns]

        self.validate_price_schema(df)
        df = self._normalize_price_types(df)

        snapshots: list[MarketSnapshot] = []
        for _, row in df.iterrows():
            try:
                bid_prices: list[Optional[float]] = []
                bid_volumes: list[Optional[int]] = []
                ask_prices: list[Optional[float]] = []
                ask_volumes: list[Optional[int]] = []

                for level in range(1, 4):
                    bp_col = f"bid_price_{level}"
                    bv_col = f"bid_volume_{level}"
                    ap_col = f"ask_price_{level}"
                    av_col = f"ask_volume_{level}"

                    bid_prices.append(
                        None if bp_col not in df.columns or pd.isna(row.get(bp_col))
                        else float(row[bp_col])
                    )
                    bid_volumes.append(
                        None if bv_col not in df.columns or pd.isna(row.get(bv_col))
                        else int(row[bv_col])
                    )
                    ask_prices.append(
                        None if ap_col not in df.columns or pd.isna(row.get(ap_col))
                        else float(row[ap_col])
                    )
                    ask_volumes.append(
                        None if av_col not in df.columns or pd.isna(row.get(av_col))
                        else int(row[av_col])
                    )

                mid = None if pd.isna(row.get("mid_price")) else float(row["mid_price"])
                pnl = None if pd.isna(row.get("profit_and_loss", None)) else float(row.get("profit_and_loss", 0))

                snapshot = MarketSnapshot(
                    day=int(row["day"]),
                    timestamp=int(row["timestamp"]),
                    product=str(row["product"]).strip(),
                    bid_prices=bid_prices,
                    bid_volumes=bid_volumes,
                    ask_prices=ask_prices,
                    ask_volumes=ask_volumes,
                    mid_price=mid,
                    profit_and_loss=pnl,
                )
                snapshots.append(snapshot)
            except Exception as exc:
                logger.warning("Skipping malformed price row %s: %s", _, exc)

        logger.info("Loaded %d market snapshots from %s", len(snapshots), filepath)
        return snapshots

    def load_trade_csv(self, filepath: str) -> list[TradePrint]:
        """
        Load a trades CSV file and return a list of ``TradePrint``
        objects.

        Parameters
        ----------
        filepath : str
            Path to the CSV file.

        Returns
        -------
        list[TradePrint]

        Raises
        ------
        FileNotFoundError
            If *filepath* does not exist.
        ValueError
            If the CSV schema is invalid.
        """
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"Trade file not found: {filepath}")

        try:
            df = pd.read_csv(filepath, sep=";")
        except Exception:
            df = pd.read_csv(filepath, sep=",")

        df.columns = [c.strip() for c in df.columns]

        self.validate_trade_schema(df)
        df = self._normalize_trade_types(df)

        trades: list[TradePrint] = []
        for _, row in df.iterrows():
            try:
                trade = TradePrint(
                    timestamp=int(row["timestamp"]),
                    buyer=str(row["buyer"]).strip(),
                    seller=str(row["seller"]).strip(),
                    symbol=str(row["symbol"]).strip(),
                    currency=str(row["currency"]).strip(),
                    price=float(row["price"]),
                    quantity=int(row["quantity"]),
                )
                trades.append(trade)
            except Exception as exc:
                logger.warning("Skipping malformed trade row %s: %s", _, exc)

        logger.info("Loaded %d trade prints from %s", len(trades), filepath)
        return trades

    # ------------------------------------------------------------------
    # Type normalization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_price_types(df: pd.DataFrame) -> pd.DataFrame:
        """Cast price-CSV columns to their expected types."""
        int_cols = ["day", "timestamp"]
        for col in int_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

        float_cols = [
            "mid_price", "profit_and_loss",
        ]
        for level in range(1, 4):
            float_cols.append(f"bid_price_{level}")
            float_cols.append(f"ask_price_{level}")

        for col in float_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        vol_cols = []
        for level in range(1, 4):
            vol_cols.append(f"bid_volume_{level}")
            vol_cols.append(f"ask_volume_{level}")

        for col in vol_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

        if "product" in df.columns:
            df["product"] = df["product"].astype(str).str.strip()

        return df

    @staticmethod
    def _normalize_trade_types(df: pd.DataFrame) -> pd.DataFrame:
        """Cast trade-CSV columns to their expected types."""
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").astype("Int64")
        if "price" in df.columns:
            df["price"] = pd.to_numeric(df["price"], errors="coerce")
        if "quantity" in df.columns:
            df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype("Int64")

        str_cols = ["buyer", "seller", "symbol", "currency"]
        for col in str_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()

        return df
