"""A sorted, indexable full-day event stream with two chunks resident at most."""

import bisect
import copy
from collections import OrderedDict
from collections.abc import Sequence


class ChunkedEvents(Sequence):
    is_sorted_stream = True

    def __init__(self, repository):
        from app.services.nvda_dataset import NVDADataset
        self.repository = NVDADataset()
        self.repository._manifest = copy.deepcopy(repository._manifest)
        self.repository._source = repository._source
        self.windows = self.repository._manifest["windows"]
        self.offsets = [0]
        for window in self.windows:
            self.offsets.append(self.offsets[-1] + window["prices"]["rows"] + window["trades"]["rows"])
        self.cache = OrderedDict()

    def __len__(self): return self.offsets[-1]

    def _chunk(self, index):
        if index not in self.cache:
            service = self.repository._load_window(index)
            events = service.get_event_stream(["NVDA"], [0])
            for event in events:
                event.sequence_num += self.offsets[index]
            self.cache[index] = events
            if len(self.cache) > 2:
                self.cache.popitem(last=False)
        self.cache.move_to_end(index)
        return self.cache[index]

    def __getitem__(self, index):
        if isinstance(index, slice):
            return (self[i] for i in range(*index.indices(len(self))))
        if index < 0: index += len(self)
        if not 0 <= index < len(self): raise IndexError(index)
        chunk = bisect.bisect_right(self.offsets, index) - 1
        return self._chunk(chunk)[index - self.offsets[chunk]]

    def seek_index(self, timestamp):
        chunk = max(0, bisect.bisect_right([w["start"] for w in self.windows], timestamp) - 1)
        events = self._chunk(chunk)
        index = bisect.bisect_right(events, timestamp, key=lambda event: event.timestamp) - 1
        return max(0, self.offsets[chunk] + index)
