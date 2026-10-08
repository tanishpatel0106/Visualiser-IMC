"""Dataset and market data API endpoints."""

import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Optional

from app.core.deps import get_dataset_service
from app.core.config import settings
from app.engines.analytics.indicators import TechnicalIndicators
from app.engines.data.aggregator import DataAggregator
from app.services.dataset_service import DatasetService

router = APIRouter()


class LoadRequest(BaseModel):
    directory: str


def require_data_admin(authorization: Optional[str] = Header(None)):
    token = os.environ.get("IMC_DATA_ADMIN_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="Dataset administration is not configured.")
    supplied = (authorization or "").removeprefix("Bearer ")
    if not authorization or not authorization.startswith("Bearer ") or not secrets.compare_digest(
        supplied.encode(), token.encode()
    ):
        raise HTTPException(status_code=401, detail="Invalid dataset admin credentials.")


def require_shared_storage():
    if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        raise HTTPException(status_code=503, detail="Connect a private Vercel Blob store first.")


@router.post("/datasets/upload", dependencies=[Depends(require_data_admin), Depends(require_shared_storage)])
async def upload_dataset(files: list[UploadFile] = File(...)):
    """Replace the shared dataset with a complete, validated CSV collection."""
    from app.services.shared_dataset import MAX_UPLOAD_BYTES, shared_dataset
    contents = {}
    remaining = MAX_UPLOAD_BYTES
    try:
        if not 1 <= len(files) <= 32:
            raise ValueError("Upload between 1 and 32 CSV files.")
        for file in files:
            if file.filename in contents:
                raise ValueError("Duplicate filenames are not allowed.")
            raw = await file.read(remaining + 1)
            remaining -= len(raw)
            if remaining < 0:
                raise HTTPException(status_code=413, detail="Combined CSV contents exceed 3 MiB.")
            contents[file.filename or ""] = raw.decode("utf-8-sig")
        if settings.dataset_manifest and Path(settings.dataset_manifest).is_file():
            from app.services.nvda_dataset import nvda_dataset
            return await run_in_threadpool(nvda_dataset.publish, contents)
        return await run_in_threadpool(shared_dataset.publish, contents)
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to publish the shared dataset.") from exc
    finally:
        for file in files:
            await file.close()


@router.post("/datasets/reset", dependencies=[Depends(require_data_admin), Depends(require_shared_storage)])
def reset_dataset():
    """Remove the replacement and restore repository-bundled CSVs for all instances."""
    from app.services.shared_dataset import shared_dataset
    try:
        if settings.dataset_manifest and Path(settings.dataset_manifest).is_file():
            from app.services.nvda_dataset import nvda_dataset
            nvda_dataset.reset()
        else:
            shared_dataset.reset()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to reset the shared dataset.") from exc
    return {"source": "repository", "status": "ok"}


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------

@router.get("/health")
def health_check():
    return {"status": "ok"}


# ------------------------------------------------------------------
# Dataset management
# ------------------------------------------------------------------

@router.get("/datasets")
def list_datasets(ds: DatasetService = Depends(get_dataset_service)):
    """List currently loaded dataset metadata."""
    products = ds.get_products()
    days = ds.get_days()
    result = {
        "products": products,
        "days": days,
        "loaded": len(products) > 0,
    }
    if hasattr(ds, "windows"):
        result.update(windows=ds.windows, window_id=ds.window_id,
                      source=ds.dataset_source, total_snapshots=ds.total_snapshots,
                      total_trades=ds.total_trades)
    return result


@router.post("/datasets/load")
def load_dataset(
    req: LoadRequest,
    ds: DatasetService = Depends(get_dataset_service),
):
    """Load a dataset from the given directory."""
    if (os.environ.get("VERCEL") == "1" or os.environ.get("BLOB_READ_WRITE_TOKEN")
            or Path(settings.dataset_manifest).is_file()):
        raise HTTPException(status_code=403, detail="Use the admin-protected /api/datasets/upload endpoint.")
    try:
        summary = ds.load_dataset(req.directory)
        return summary
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ------------------------------------------------------------------
# Market data queries
# ------------------------------------------------------------------

@router.get("/products")
def list_products(ds: DatasetService = Depends(get_dataset_service)):
    """Return all product names."""
    return {"products": ds.get_products()}


@router.get("/days")
def list_days(ds: DatasetService = Depends(get_dataset_service)):
    """Return all available days."""
    return {"days": ds.get_days()}


@router.get("/snapshots")
def get_snapshots(
    product: str = Query(..., description="Product symbol"),
    day: Optional[int] = Query(None, description="Day filter"),
    ds: DatasetService = Depends(get_dataset_service),
):
    """Return order book snapshots for a product/day."""
    snaps = ds.get_snapshots(product, day)
    return {
        "product": product,
        "day": day,
        "count": len(snaps),
        "snapshots": [s.model_dump() for s in snaps],
    }


@router.get("/trades")
def get_trades(
    product: str = Query(..., description="Product symbol"),
    day: Optional[int] = Query(None, description="Day filter"),
    ds: DatasetService = Depends(get_dataset_service),
):
    """Return trade prints for a product/day."""
    trades = ds.get_trades(product, day)
    return {
        "product": product,
        "day": day,
        "count": len(trades),
        "trades": [t.model_dump() for t in trades],
    }


@router.get("/ohlcv")
def get_ohlcv(
    product: str = Query(..., description="Product symbol"),
    interval: int = Query(100, description="Bar interval in timestamp units"),
    day: Optional[int] = Query(None, description="Day filter"),
    ds: DatasetService = Depends(get_dataset_service),
):
    """Return OHLCV bars for a product."""
    snaps = ds.get_snapshots(product, day)
    trades = ds.get_trades(product, day)

    aggregator = DataAggregator()
    bars = aggregator.aggregate_ohlcv(snaps, trades, interval)
    return {
        "product": product,
        "interval": interval,
        "count": len(bars),
        "bars": bars,
    }


@router.get("/indicators")
def get_indicators(
    product: str = Query(..., description="Product symbol"),
    indicator: str = Query(..., description="Indicator name (sma, ema, rsi, macd, bollinger, roc, zscore, volatility)"),
    period: int = Query(20, description="Indicator period"),
    day: Optional[int] = Query(None, description="Day filter"),
    ds: DatasetService = Depends(get_dataset_service),
):
    """Compute and return indicator values for a product."""
    snaps = ds.get_snapshots(product, day)
    if not snaps:
        return {"product": product, "indicator": indicator, "values": []}

    # Extract mid-price series
    prices: list[float] = []
    timestamps: list[int] = []
    for snap in snaps:
        mid = snap.mid_price
        if mid is None and snap.bid_prices and snap.ask_prices:
            bp = snap.bid_prices[0]
            ap = snap.ask_prices[0]
            if bp is not None and ap is not None:
                mid = (bp + ap) / 2.0
        if mid is not None:
            prices.append(mid)
            timestamps.append(snap.timestamp)

    if not prices:
        return {"product": product, "indicator": indicator, "values": []}

    ti = TechnicalIndicators()
    indicator_lower = indicator.lower()

    if indicator_lower == "sma":
        values = ti.sma(prices, period)
    elif indicator_lower == "ema":
        values = ti.ema(prices, period)
    elif indicator_lower == "rsi":
        values = ti.rsi(prices, period)
    elif indicator_lower == "macd":
        macd_line, signal_line, histogram = ti.macd(prices)
        return {
            "product": product,
            "indicator": "macd",
            "timestamps": timestamps,
            "macd_line": macd_line,
            "signal_line": signal_line,
            "histogram": histogram,
        }
    elif indicator_lower == "bollinger":
        upper, mid, lower = ti.bollinger_bands(prices, period)
        return {
            "product": product,
            "indicator": "bollinger",
            "timestamps": timestamps,
            "upper": upper,
            "mid": mid,
            "lower": lower,
        }
    elif indicator_lower == "roc":
        values = ti.roc(prices, period)
    elif indicator_lower == "zscore":
        values = ti.rolling_zscore(prices, period)
    elif indicator_lower == "volatility":
        values = ti.rolling_volatility(prices, period)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown indicator: {indicator}")

    return {
        "product": product,
        "indicator": indicator,
        "period": period,
        "timestamps": timestamps,
        "values": values,
    }
