"""Disk-backed full-day collectors; plotting/debug exports stay bounded."""

import struct
import tempfile
from array import array
from collections.abc import Sequence

from app.models.trading import FillEvent, PnLState


class PnLFile(Sequence):
    record = struct.Struct("<qddddq")

    def __init__(self):
        self.file = tempfile.TemporaryFile()
        self.count = 0

    def append(self, state):
        if any(product != "NVDA" for product in state.inventory):
            raise ValueError("Full-day storage supports NVDA only.")
        self.file.seek(0, 2)
        self.file.write(self.record.pack(state.timestamp, state.realized_pnl, state.unrealized_pnl,
                                        state.total_pnl, state.cash, state.inventory.get("NVDA", 0)))
        self.count += 1

    def __len__(self): return self.count

    def __getitem__(self, index):
        if index < 0: index += len(self)
        if not 0 <= index < len(self): raise IndexError(index)
        self.file.seek(index * self.record.size)
        timestamp, realized, unrealized, total, cash, inventory = self.record.unpack(self.file.read(self.record.size))
        return PnLState(timestamp=timestamp, realized_pnl=realized, unrealized_pnl=unrealized,
                        total_pnl=total, cash=cash, inventory={"NVDA": inventory})

    def sampled(self, limit=5000):
        if not len(self): return []
        step = max(1, (len(self) + limit - 2) // (limit - 1))
        indices = list(range(0, len(self) - 1, step)) + [len(self) - 1]
        return [self[index] for index in indices]


class FillFile(Sequence):
    def __init__(self):
        self.file = tempfile.TemporaryFile()
        self.offsets = array("Q")

    def append(self, fill):
        self.file.seek(0, 2)
        self.offsets.append(self.file.tell())
        self.file.write((fill.model_dump_json() + "\n").encode())

    def __len__(self): return len(self.offsets)

    def __getitem__(self, index):
        self.file.seek(self.offsets[index])
        return FillEvent.model_validate_json(self.file.readline())


class OrderCount:
    def __init__(self): self.count = 0
    def __len__(self): return self.count
    def extend(self, orders): self.count += len(orders)
