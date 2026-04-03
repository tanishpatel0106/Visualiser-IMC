"""Performance analytics engine for backtest and live trading evaluation."""

from __future__ import annotations

import numpy as np

from backend.app.models.analytics import PerformanceMetrics
from backend.app.models.trading import FillEvent, PnLState, PositionState
from backend.app.models.market import OrderSide


class PerformanceAnalyzer:
    """Computes aggregate performance metrics from fills, PnL history, and positions."""

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_metrics(
        fills: list,
        pnl_history: list,
        positions: dict,
    ) -> PerformanceMetrics:
        """
        Parameters
        ----------
        fills : list[FillEvent]
            Chronologically ordered fill events.
        pnl_history : list[PnLState]
            Time-series PnL snapshots (sorted by timestamp).
        positions : dict[str, PositionState]
            Current open positions keyed by product.

        Returns
        -------
        PerformanceMetrics
        """
        metrics = PerformanceMetrics()

        if not fills and not pnl_history:
            return metrics

        # -- PnL bookkeeping ------------------------------------------- #
        realized = sum(pos.realized_pnl for pos in positions.values())
        unrealized = sum(pos.unrealized_pnl for pos in positions.values())
        metrics.realized_pnl = realized
        metrics.unrealized_pnl = unrealized
        metrics.total_pnl = realized + unrealized

        # PnL by product
        pnl_by_product: dict[str, float] = {}
        for product, pos in positions.items():
            pnl_by_product[product] = pos.total_pnl
        metrics.pnl_by_product = pnl_by_product

        # -- Trade-level statistics ------------------------------------ #
        num_trades = len(fills)
        metrics.num_trades = num_trades

        if num_trades > 0:
            # Turnover = sum of |price * quantity| across all fills
            turnover = sum(abs(f.price * f.quantity) for f in fills)
            metrics.turnover = turnover
            metrics.return_per_trade = metrics.total_pnl / num_trades if num_trades else 0.0

            # Approximate per-trade PnL by pairing buys and sells per product
            trade_pnls = PerformanceAnalyzer._estimate_trade_pnls(fills)
            wins = [p for p in trade_pnls if p > 0]
            losses = [p for p in trade_pnls if p < 0]
            metrics.avg_win = float(np.mean(wins)) if wins else 0.0
            metrics.avg_loss = float(np.mean(losses)) if losses else 0.0
            metrics.win_rate = len(wins) / len(trade_pnls) if trade_pnls else 0.0

            # Profit factor
            gross_profit = sum(wins) if wins else 0.0
            gross_loss = abs(sum(losses)) if losses else 0.0
            metrics.profit_factor = (
                gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
            )

            # Consecutive wins / losses
            max_cw, max_cl = PerformanceAnalyzer._max_consecutive(trade_pnls)
            metrics.max_consecutive_wins = max_cw
            metrics.max_consecutive_losses = max_cl

        # -- PnL time-series analytics --------------------------------- #
        if len(pnl_history) >= 2:
            pnl_values = np.array([s.total_pnl for s in pnl_history], dtype=np.float64)
            increments = np.diff(pnl_values)

            # Sharpe ratio (annualisation not meaningful in tick-space; raw ratio)
            std = float(np.std(increments, ddof=1)) if len(increments) > 1 else 0.0
            mean = float(np.mean(increments))
            metrics.sharpe_ratio = mean / std if std > 0 else 0.0
            metrics.pnl_volatility = std

            # Drawdown
            running_max = np.maximum.accumulate(pnl_values)
            drawdowns = running_max - pnl_values
            metrics.max_drawdown = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

            # Drawdown duration (longest streak below the running max)
            in_dd = drawdowns > 0
            max_dur = 0
            current_dur = 0
            for flag in in_dd:
                if flag:
                    current_dur += 1
                    max_dur = max(max_dur, current_dur)
                else:
                    current_dur = 0
            metrics.drawdown_duration = max_dur

            # PnL per unit risk
            metrics.pnl_per_unit_risk = (
                metrics.total_pnl / metrics.pnl_volatility if metrics.pnl_volatility > 0 else 0.0
            )

        # -- Inventory statistics -------------------------------------- #
        if pnl_history:
            inventory_sizes = []
            for snap in pnl_history:
                total_inv = sum(abs(v) for v in snap.inventory.values())
                inventory_sizes.append(total_inv)
            if inventory_sizes:
                metrics.avg_inventory = float(np.mean(inventory_sizes))
                metrics.max_inventory = float(np.max(inventory_sizes))

        # -- Average holding period (simple estimate) ------------------- #
        if fills and pnl_history:
            metrics.avg_holding_period = PerformanceAnalyzer._avg_holding_period(fills)

        return metrics

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _estimate_trade_pnls(fills: list) -> list[float]:
        """
        Estimate per-round-trip PnL using FIFO matching of buys and sells
        per product. Returns a list of PnL values for each closed round-trip.
        """
        from collections import deque

        buys: dict[str, deque] = {}
        sells: dict[str, deque] = {}
        pnls: list[float] = []

        for f in fills:
            product = f.product
            if f.side == OrderSide.BUY:
                buys.setdefault(product, deque()).append((f.price, f.quantity))
            else:
                sells.setdefault(product, deque()).append((f.price, f.quantity))

            # Try to match
            buy_q = buys.get(product, deque())
            sell_q = sells.get(product, deque())
            while buy_q and sell_q:
                bp, bq = buy_q[0]
                sp, sq = sell_q[0]
                matched = min(bq, sq)
                pnls.append((sp - bp) * matched)
                bq -= matched
                sq -= matched
                if bq == 0:
                    buy_q.popleft()
                else:
                    buy_q[0] = (bp, bq)
                if sq == 0:
                    sell_q.popleft()
                else:
                    sell_q[0] = (sp, sq)

        return pnls

    @staticmethod
    def _max_consecutive(pnls: list[float]) -> tuple[int, int]:
        """Return (max_consecutive_wins, max_consecutive_losses)."""
        max_w = max_l = cur_w = cur_l = 0
        for p in pnls:
            if p > 0:
                cur_w += 1
                cur_l = 0
            elif p < 0:
                cur_l += 1
                cur_w = 0
            else:
                cur_w = 0
                cur_l = 0
            max_w = max(max_w, cur_w)
            max_l = max(max_l, cur_l)
        return max_w, max_l

    @staticmethod
    def _avg_holding_period(fills: list) -> float:
        """
        Rough average holding period in timestamp units.
        Pairs the first buy with the first sell per product (FIFO).
        """
        from collections import deque

        open_times: dict[str, deque] = {}
        durations: list[float] = []

        for f in fills:
            product = f.product
            if f.side == OrderSide.BUY:
                open_times.setdefault(product, deque()).append((f.timestamp, f.quantity))
            else:
                q = open_times.get(product, deque())
                remaining = f.quantity
                while q and remaining > 0:
                    ot, oq = q[0]
                    matched = min(oq, remaining)
                    durations.append(f.timestamp - ot)
                    remaining -= matched
                    oq -= matched
                    if oq == 0:
                        q.popleft()
                    else:
                        q[0] = (ot, oq)

        return float(np.mean(durations)) if durations else 0.0
