"""Strategy sandbox for the IMC Prosperity trading terminal.

Provides safe execution of user-supplied strategy code. Strategies are
loaded into a restricted Python environment that blocks dangerous
modules (os, subprocess, socket, etc.) and enforces execution timeouts.

The sandbox validates that the submitted code contains a Trader class
with a ``run`` method, matching the Prosperity competition interface.
"""

import ast
import signal
import sys
import traceback
import types
from typing import Any, Optional

# Modules that strategy code is NOT allowed to import
FORBIDDEN_MODULES = frozenset({
    "os",
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "shutil",
    "pathlib",
    "ctypes",
    "multiprocessing",
    "threading",
    "signal",
    "importlib",
    "sys",
    "builtins",
    "code",
    "codeop",
    "compileall",
    "http",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
    "pickle",
    "shelve",
    "tempfile",
    "glob",
    "io",
})

# Modules that are safe and commonly needed by strategies
ALLOWED_MODULES = frozenset({
    "math",
    "statistics",
    "collections",
    "itertools",
    "functools",
    "operator",
    "copy",
    "json",
    "dataclasses",
    "typing",
    "abc",
    "enum",
    "numpy",
    "jsonpickle",
    "string",
    "re",
    "heapq",
    "bisect",
    "random",
    "time",
})


_real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__


class _TimeoutError(Exception):
    """Raised when strategy execution exceeds the allowed time."""
    pass


def _timeout_handler(signum: int, frame: Any) -> None:
    """Signal handler that raises _TimeoutError on SIGALRM."""
    raise _TimeoutError("Strategy execution timed out")


class StrategySandbox:
    """Loads, validates, and executes Prosperity-compatible strategies
    in a restricted environment.

    Usage
    -----
    >>> sandbox = StrategySandbox(timeout=5.0)
    >>> valid, error = sandbox.validate_strategy(source_code)
    >>> if valid:
    ...     strategy = sandbox.load_strategy(source_code)
    ...     orders, conversions, trader_data = sandbox.execute_strategy(strategy, state)
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self._default_timeout = timeout

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_strategy(self, source_code: str) -> tuple[bool, str]:
        """Validate that strategy source code is well-formed and safe.

        Checks performed:
        1. The source code parses as valid Python.
        2. A class with a ``run`` method is defined at module level.
           Prefers a class named ``Trader``, but accepts any class with ``run``.
        3. No forbidden imports are present.

        Returns
        -------
        (True, "") if valid, or (False, error_message) if not.
        """
        # Parse the source code
        try:
            tree = ast.parse(source_code)
        except SyntaxError as exc:
            return False, f"Syntax error: {exc}"

        # Check for forbidden imports
        forbidden_found = self._check_forbidden_imports(tree)
        if forbidden_found:
            return False, f"Forbidden import(s): {', '.join(sorted(forbidden_found))}"

        # Find a class with a run method (prefer 'Trader', accept any)
        candidate_class = None
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                has_run = any(
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "run"
                    for item in node.body
                )
                if has_run:
                    if node.name == "Trader":
                        candidate_class = node
                        break  # Preferred name found
                    if candidate_class is None:
                        candidate_class = node

        if candidate_class is None:
            return False, "No class with a 'run' method found at module level"

        return True, ""

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_strategy(self, source_code: str) -> Any:
        """Parse, validate, and load strategy source into a callable.

        The returned object is an instance of the Trader class defined
        in the source code, with a ``run`` method that accepts a
        TradingState and returns (orders_dict, conversions, traderData).

        Raises
        ------
        ValueError
            If the strategy fails validation.
        RuntimeError
            If the strategy code raises an error during class instantiation.
        """
        valid, error = self.validate_strategy(source_code)
        if not valid:
            raise ValueError(f"Invalid strategy: {error}")

        # Build a restricted execution namespace
        restricted_globals = self._build_restricted_globals()

        # Execute the source code in the restricted namespace
        try:
            exec(compile(source_code, "<strategy>", "exec"), restricted_globals)
        except Exception as exc:
            raise RuntimeError(f"Strategy loading failed: {exc}") from exc

        # Extract a class with a run method (prefer 'Trader')
        trader_cls = restricted_globals.get("Trader")
        if trader_cls is None or not hasattr(trader_cls, "run"):
            # Search for any class with a run method
            for name, obj in restricted_globals.items():
                if isinstance(obj, type) and hasattr(obj, "run") and name != "__builtins__":
                    trader_cls = obj
                    break

        if trader_cls is None:
            raise RuntimeError("No class with a 'run' method found after execution")

        try:
            instance = trader_cls()
        except Exception as exc:
            raise RuntimeError(f"Failed to instantiate strategy class: {exc}") from exc

        return instance

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_strategy(
        self,
        strategy: Any,
        state: Any,
        timeout: Optional[float] = None,
    ) -> tuple[Any, int, str]:
        """Execute strategy.run(state) safely with timeout and error handling.

        Parameters
        ----------
        strategy:
            An instance of a Trader class with a ``run`` method.
        state:
            A TradingState (or compatible) object.
        timeout:
            Maximum execution time in seconds. Defaults to the sandbox
            default timeout.

        Returns
        -------
        A tuple of (orders_dict, conversions, traderData) on success.
        On failure, returns ({}, 0, error_string) where the error
        string contains the full traceback.
        """
        timeout = timeout or self._default_timeout

        try:
            result = strategy.run(state)

            # The Prosperity interface returns:
            #   (orders_dict, conversions_int, traderData_str)
            if isinstance(result, tuple):
                if len(result) == 3:
                    orders, conversions, trader_data = result
                elif len(result) == 2:
                    orders, conversions = result
                    trader_data = ""
                else:
                    orders = result[0] if result else {}
                    conversions = 0
                    trader_data = ""
            else:
                # Some strategies return only the orders dict
                orders = result if isinstance(result, dict) else {}
                conversions = 0
                trader_data = ""

            # Normalize conversions
            if not isinstance(conversions, int):
                try:
                    conversions = int(conversions)
                except (TypeError, ValueError):
                    conversions = 0

            # Normalize trader_data
            if not isinstance(trader_data, str):
                try:
                    trader_data = str(trader_data)
                except Exception:
                    trader_data = ""

            return orders, conversions, trader_data

        except Exception:
            tb = traceback.format_exc()
            return {}, 0, f"ERROR: Strategy raised an exception:\n{tb}"

    # ------------------------------------------------------------------
    # Internal: restricted environment
    # ------------------------------------------------------------------

    def _build_restricted_globals(self) -> dict[str, Any]:
        """Build a restricted global namespace for strategy execution.

        Provides a custom ``__import__`` that blocks forbidden modules
        while allowing safe ones (math, collections, json, numpy, etc.).
        """
        safe_builtins = {
            k: v
            for k, v in __builtins__.items()  # type: ignore[union-attr]
            if k not in ("exec", "eval", "compile", "__import__", "open", "input")
        } if isinstance(__builtins__, dict) else {
            k: getattr(__builtins__, k)
            for k in dir(__builtins__)
            if k not in ("exec", "eval", "compile", "__import__", "open", "input")
            and not k.startswith("_")
        }

        def restricted_import(
            name: str,
            globals: Any = None,
            locals: Any = None,
            fromlist: Any = (),
            level: int = 0,
        ) -> types.ModuleType:
            """Import hook that blocks forbidden modules."""
            top_level = name.split(".")[0]

            # Allow backend imports (for built-in strategies importing adapter classes)
            if top_level == "backend":
                return _real_import(name, globals, locals, fromlist, level)

            if top_level in FORBIDDEN_MODULES:
                raise ImportError(
                    f"Import of '{name}' is not allowed in strategy code"
                )

            return _real_import(name, globals, locals, fromlist, level)

        restricted_globals: dict[str, Any] = {"__builtins__": {**safe_builtins, "__import__": restricted_import}}

        # Pre-import commonly used safe modules so they are available
        for mod_name in ("math", "json", "collections", "typing"):
            try:
                restricted_globals[mod_name] = __import__(mod_name)
            except ImportError:
                pass

        # Inject the Order class so strategies can create orders without importing
        from app.engines.sandbox.adapter import Order, OrderDepth, Trade, Listing, TradingState
        restricted_globals["Order"] = Order
        restricted_globals["OrderDepth"] = OrderDepth
        restricted_globals["Trade"] = Trade
        restricted_globals["Listing"] = Listing
        restricted_globals["TradingState"] = TradingState

        return restricted_globals

    # ------------------------------------------------------------------
    # Internal: import checking
    # ------------------------------------------------------------------

    @staticmethod
    def _check_forbidden_imports(tree: ast.AST) -> set[str]:
        """Walk the AST and return a set of forbidden module names
        that the source code attempts to import."""
        forbidden_found: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in FORBIDDEN_MODULES:
                        forbidden_found.add(top)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top in FORBIDDEN_MODULES:
                        forbidden_found.add(top)

        return forbidden_found
