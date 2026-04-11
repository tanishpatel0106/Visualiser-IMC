"""Prosperity protocol adapter for the IMC Prosperity trading terminal.

Translates between internal market models and the data structures
expected by Prosperity-compatible strategy code. Strategies written
for the IMC Prosperity competition expect a TradingState object with
specific attributes; this module builds that object from internal
engine state and parses the strategy's order output back into internal
StrategyOrder models.
"""

import uuid
from typing import Optional

from app.models.market import (
    OrderSide,
    OrderType,
    TradePrint,
    VisibleOrderBook,
)
from app.models.trading import StrategyOrder


# =====================================================================
# Prosperity-compatible helper classes
#
# These mirror the classes available in the Prosperity competition
# runtime so that strategy code can use them seamlessly.
# =====================================================================


class Listing:
    """Product listing information."""

    def __init__(self, symbol: str, product: str, denomination: str = "SEASHELLS") -> None:
        self.symbol = symbol
        self.product = product
        self.denomination = denomination

    def __repr__(self) -> str:
        return f"Listing(symbol={self.symbol!r}, product={self.product!r})"


class OrderDepth:
    """Order book depth for a single product.

    Attributes
    ----------
    buy_orders : dict[int, int]
        Maps price -> positive volume for bids.
    sell_orders : dict[int, int]
        Maps price -> negative volume for asks (Prosperity convention).
    """

    def __init__(self) -> None:
        self.buy_orders: dict[int, int] = {}
        self.sell_orders: dict[int, int] = {}

    def __repr__(self) -> str:
        return (
            f"OrderDepth(buys={len(self.buy_orders)}, sells={len(self.sell_orders)})"
        )


class Trade:
    """A single trade record in Prosperity format."""

    def __init__(
        self,
        symbol: str,
        price: float,
        quantity: int,
        buyer: str = "",
        seller: str = "",
        timestamp: int = 0,
    ) -> None:
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
        self.buyer = buyer
        self.seller = seller
        self.timestamp = timestamp

    def __repr__(self) -> str:
        return (
            f"Trade(symbol={self.symbol!r}, price={self.price}, "
            f"qty={self.quantity}, t={self.timestamp})"
        )


class Order:
    """A single order in Prosperity format."""

    def __init__(self, symbol: str, price: int, quantity: int) -> None:
        self.symbol = symbol
        self.price = price
        self.quantity = quantity

    def __repr__(self) -> str:
        return f"Order(symbol={self.symbol!r}, price={self.price}, qty={self.quantity})"


class ConversionObservation:
    """Conversion observation for a product (e.g. ORCHIDS).

    Provides bid/ask prices, fees, and tariffs for the southern
    archipelago conversion channel used in Prosperity.
    """

    def __init__(
        self,
        bidPrice: float,
        askPrice: float,
        transportFees: float,
        exportTariff: float,
        importTariff: float,
        sunlight: float = 0.0,
        humidity: float = 0.0,
    ) -> None:
        self.bidPrice = bidPrice
        self.askPrice = askPrice
        self.transportFees = transportFees
        self.exportTariff = exportTariff
        self.importTariff = importTariff
        self.sunlight = sunlight
        self.humidity = humidity

    def __repr__(self) -> str:
        return (
            f"ConversionObservation(bid={self.bidPrice}, ask={self.askPrice}, "
            f"transport={self.transportFees})"
        )


class Observation:
    """Observations container (placeholder for future enrichment)."""

    def __init__(self) -> None:
        self.plainValueObservations: dict[str, float] = {}
        self.conversionObservations: dict[str, "ConversionObservation"] = {}


class TradingState:
    """The state object passed to a Prosperity strategy's ``run`` method.

    This mirrors the official Prosperity TradingState so that
    competition-grade strategies can run unmodified inside the
    backtester.

    Attributes
    ----------
    timestamp : int
        Current simulation timestamp.
    traderData : str
        Opaque string the strategy returned on the previous call.
    listings : dict[str, Listing]
        Product listings.
    order_depths : dict[str, OrderDepth]
        Current order book depth per product.
    own_trades : dict[str, list[Trade]]
        Strategy's own fills since last call, keyed by product.
    market_trades : dict[str, list[Trade]]
        All other market trades since last call, keyed by product.
    position : dict[str, int]
        Current net position per product.
    observations : Observation
        Market observations (empty by default).
    """

    def __init__(self) -> None:
        self.timestamp: int = 0
        self.traderData: str = ""
        self.listings: dict[str, Listing] = {}
        self.order_depths: dict[str, OrderDepth] = {}
        self.own_trades: dict[str, list[Trade]] = {}
        self.market_trades: dict[str, list[Trade]] = {}
        self.position: dict[str, int] = {}
        self.observations: Observation = Observation()

    def __repr__(self) -> str:
        products = list(self.order_depths.keys())
        return f"TradingState(t={self.timestamp}, products={products})"


# =====================================================================
# ProsperityAdapter
# =====================================================================


class ProsperityAdapter:
    """Adapts internal market state to Prosperity-compatible objects
    and converts strategy output back to internal models.

    Usage
    -----
    >>> adapter = ProsperityAdapter()
    >>> state = adapter.build_state(
    ...     timestamp=1000,
    ...     products=["EMERALDS"],
    ...     books={"EMERALDS": book},
    ...     positions={"EMERALDS": 0},
    ...     own_trades={"EMERALDS": []},
    ...     market_trades={"EMERALDS": recent_trades},
    ...     trader_data="",
    ... )
    >>> # Pass state to strategy.run(state) ...
    >>> orders = adapter.parse_orders(raw_orders)
    """

    @staticmethod
    def build_state(
        timestamp: int,
        products: list[str],
        books: dict[str, VisibleOrderBook],
        positions: dict[str, int],
        own_trades: dict[str, list[TradePrint]],
        market_trades: dict[str, list[TradePrint]],
        trader_data: str = "",
    ) -> TradingState:
        """Build a Prosperity TradingState from internal engine state.

        Parameters
        ----------
        timestamp:
            Current simulation time.
        products:
            List of active product symbols.
        books:
            Current VisibleOrderBook per product.
        positions:
            Net position per product.
        own_trades:
            The strategy's own recent fills, as TradePrint objects.
        market_trades:
            Other participants' recent trades, as TradePrint objects.
        trader_data:
            Opaque string the strategy returned on its last invocation.

        Returns
        -------
        TradingState ready to be passed into strategy.run().
        """
        state = TradingState()
        state.timestamp = timestamp
        state.traderData = trader_data

        # Build listings
        for product in products:
            state.listings[product] = Listing(
                symbol=product,
                product=product,
                denomination="SEASHELLS",
            )

        # Build order depths from visible books
        for product in products:
            depth = OrderDepth()
            book = books.get(product)
            if book is not None:
                for level in book.bids:
                    depth.buy_orders[int(level.price)] = level.volume
                for level in book.asks:
                    # Prosperity convention: sell volumes are negative
                    depth.sell_orders[int(level.price)] = -level.volume
            state.order_depths[product] = depth

        # Build positions
        for product in products:
            state.position[product] = positions.get(product, 0)

        # Convert own trades
        for product in products:
            state.own_trades[product] = [
                _trade_print_to_prosperity(tp) for tp in own_trades.get(product, [])
            ]

        # Convert market trades
        for product in products:
            state.market_trades[product] = [
                _trade_print_to_prosperity(tp)
                for tp in market_trades.get(product, [])
            ]

        # Observations left empty for now
        state.observations = Observation()

        return state

    @staticmethod
    def parse_orders(
        raw_orders: dict[str, list],
        timestamp: int = 0,
    ) -> list[StrategyOrder]:
        """Convert Prosperity-style order output to internal StrategyOrder list.

        Prosperity strategies return a dict mapping product -> list of
        Order objects. Each Order has symbol, price, and quantity where
        positive quantity means BUY and negative means SELL.

        Parameters
        ----------
        raw_orders:
            Dict of product -> list of Order-like objects (must have
            symbol, price, quantity attributes).
        timestamp:
            Timestamp to assign to each created order.

        Returns
        -------
        List of StrategyOrder objects ready for the ExecutionEngine.
        """
        strategy_orders: list[StrategyOrder] = []

        for product, orders in raw_orders.items():
            for order in orders:
                qty = getattr(order, "quantity", 0)
                price = getattr(order, "price", 0)
                symbol = getattr(order, "symbol", product)

                if qty == 0:
                    continue

                side = OrderSide.BUY if qty > 0 else OrderSide.SELL

                strategy_orders.append(
                    StrategyOrder(
                        order_id=str(uuid.uuid4()),
                        product=symbol,
                        side=side,
                        order_type=OrderType.LIMIT,
                        price=float(price),
                        quantity=abs(qty),
                        timestamp=timestamp,
                        created_at=timestamp,
                    )
                )

        return strategy_orders


# =====================================================================
# Internal helpers
# =====================================================================


def _trade_print_to_prosperity(tp: TradePrint) -> Trade:
    """Convert an internal TradePrint to a Prosperity Trade object."""
    return Trade(
        symbol=tp.symbol,
        price=tp.price,
        quantity=tp.quantity,
        buyer=tp.buyer,
        seller=tp.seller,
        timestamp=tp.timestamp,
    )
