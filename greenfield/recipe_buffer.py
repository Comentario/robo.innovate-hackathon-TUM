"""Finite shared colour banks and pallet-boundary recipe control.

Control model only: a transport adapter must execute/acknowledge each transfer.
No trajectory, speed, upstream supply or plant KPI is invented here.
"""
from collections import Counter, deque
from dataclasses import dataclass
import math

SHADES = ("Warm", "Copper", "Russet")


@dataclass(frozen=True)
class Recipe:
    mode: str = "mixed"
    shade: str | None = None

    def __post_init__(self):
        if self.mode not in ("mixed", "single"):
            raise ValueError("Recipe must be mixed or single")
        if (self.mode == "single" and self.shade not in SHADES) or (self.mode == "mixed" and self.shade is not None):
            raise ValueError("Single colour needs one approved shade; mixed needs none")

    def layer(self, number):
        # Rotation across layers prevents vertical runs as well as row/column runs.
        return [self.shade if self.mode == "single" else SHADES[(r+c+number) % 3]
                for r in range(4) for c in range(10)]

    @property
    def label(self):
        return "Mixed" if self.mode == "mixed" else "Single colour · " + self.shade


class PalletOrders:
    """Four layer formers per line; all fourteen layers belong to one recipe.

    Requests affect the next pallet, including when the current pallet has no
    completed layers but already has assigned work. No implicit recipe fallback.
    """
    def __init__(self, recipes=None):
        self.recipes = list(recipes or [Recipe(), Recipe()])
        if len(self.recipes) != 2 or any(not isinstance(r, Recipe) for r in self.recipes):
            raise ValueError("Two line recipes required")
        self.pending = [deque(), deque()]
        self.assigned = [0, 0]
        self.layers = [{}, {}]
        self.stacked = [set(), set()]
        self.jobs = {}
        self.completed = []
        self.serial = [0, 0]
        self.used_ids = set()

    def queue(self, line, recipe):
        if line not in (0, 1) or not isinstance(recipe, Recipe):
            raise ValueError("Valid line and recipe required")
        self.pending[line].append(recipe)

    def demand(self, cell):
        if type(cell) is not int or not 0 <= cell < 8:
            raise ValueError("Cell must be 0..7")
        line = cell // 4
        if cell not in self.jobs:
            if self.assigned[line] == 14:
                return None
            number = self.assigned[line]
            self.assigned[line] += 1
            self.jobs[cell] = {"number": number, "pattern": self.recipes[line].layer(number), "ids": []}
        job = self.jobs[cell]
        return job["pattern"][len(job["ids"])]

    def accept(self, cell, identity, shade):
        expected = self.demand(cell)
        if expected is None or shade != expected:
            raise ValueError("Brick does not match reserved pallet slot")
        if identity in self.used_ids:
            raise ValueError("Duplicate output identity")
        self.used_ids.add(identity)
        line = cell // 4
        job = self.jobs[cell]
        job["ids"].append(identity)
        if len(job["ids"]) != 40:
            return None
        self.layers[line][job["number"]] = job["ids"][:]
        del self.jobs[cell]
        return {"line": line, "pallet": self.serial[line], "layer": job["number"],
                "ids": job["ids"][:]}

    def acknowledge_layer(self, line, pallet, layer):
        """Stacker acknowledgement, separate from layer formation or selection."""
        if line not in (0, 1) or pallet != self.serial[line] or layer not in self.layers[line]:
            raise ValueError("Unknown or stale layer acknowledgement")
        if layer in self.stacked[line]:
            raise ValueError("Layer already acknowledged")
        self.stacked[line].add(layer)
        if len(self.stacked[line]) != 14:
            return None
        result = {"line": line, "number": self.serial[line], "mode": self.recipes[line].mode,
                  "shade": self.recipes[line].shade,
                  "ids": [i for n in range(14) for i in self.layers[line][n]]}
        assert len(result["ids"]) == len(set(result["ids"])) == 560
        self.completed.append(result)
        self.serial[line] += 1
        self.layers[line] = {}
        self.stacked[line] = set()
        self.assigned[line] = 0
        if self.pending[line]:
            self.recipes[line] = self.pending[line].popleft()
        return result


@dataclass(frozen=True)
class Transfer:
    number: int
    identity: str
    source: tuple
    destination: tuple
    line: int | None


class RecipeBuffer:
    """Two shared banks, each with one independently accessible FIFO per shade.

    Destination capacity is reserved BEFORE departure; source occupancy remains
    held until completion. A full bank causes backpressure, never silent discard.
    A single bank transport resource per line serializes shared access. It is a
    logical resource whose physical mechanism is deliberately not selected yet.
    """
    def __init__(self, loop_capacity=66, high_water=54, capacity_per_colour=560):
        for name, value in (("loop_capacity", loop_capacity), ("high_water", high_water),
                            ("capacity_per_colour", capacity_per_colour)):
            if type(value) is not int or value < 1:
                raise ValueError(name + " must be a positive integer")
        if high_water >= loop_capacity:
            raise ValueError("High-water mark must leave admission headroom")
        self.loop_capacity = loop_capacity
        self.high_water = high_water
        self.capacity_per_colour = capacity_per_colour
        self.queues = {( "loop", c): deque() for c in range(8)}
        self.queues.update({("bank", line, shade): deque() for line in range(2) for shade in SHADES})
        self.shades = {}
        self.output = []
        self.inflight = {}
        self.reserved = Counter()
        self.busy_ids = set()
        self.busy_lines = set()
        self.sequence = 0
        self.events = []

    def capacity(self, port):
        return self.loop_capacity if port[0] == "loop" else self.capacity_per_colour

    def room(self, port):
        return len(self.queues[port]) + self.reserved[port] < self.capacity(port)

    def _start(self, identity, source, destination, line):
        if not self.room(destination) or identity in self.busy_ids or line in self.busy_lines:
            return None
        if source[0] != "external" and identity not in self.queues[source]:
            raise ValueError("Source does not own brick")
        self.sequence += 1
        transfer = Transfer(self.sequence, identity, source, destination, line)
        self.inflight[transfer.number] = transfer
        self.reserved[destination] += 1
        self.busy_ids.add(identity)
        if line is not None:
            self.busy_lines.add(line)
        self.events.append({"kind": "transfer_reserved", "id": identity,
                            "source": source, "destination": destination})
        return transfer

    def admit(self, cell, identity, shade, wanted=None):
        if type(cell) is not int or not 0 <= cell < 8 or shade not in SHADES:
            raise ValueError("Unknown cell or approved shade")
        if identity in self.shades:
            raise ValueError("Brick already admitted or in transit")
        loop = ("loop", cell)
        line = cell // 4
        bank = ("bank", line, shade)
        pressure = len(self.queues[loop]) + self.reserved[loop] >= self.high_water
        # Direct route stays preferred; bypass only when it protects admission.
        destination = bank if ((pressure and shade != wanted) or not self.room(loop)) else loop
        transport_line = line if destination[0] == "bank" else None
        transfer = self._start(identity, ("external",), destination, transport_line)
        if transfer is not None:
            self.shades[identity] = shade
        return transfer

    def plan(self, cell, wanted):
        if type(cell) is not int or not 0 <= cell < 8 or wanted not in SHADES:
            raise ValueError("Unknown cell or approved shade")
        line = cell // 4
        if line in self.busy_lines:
            return None
        loop = ("loop", cell)
        available = [i for i in self.queues[loop] if i not in self.busy_ids]
        matching = any(self.shades[i] == wanted for i in available)
        bank = ("bank", line, wanted)
        if not matching and self.room(loop) and self.queues[bank]:
            identity = self.queues[bank][0]
            return self._start(identity, bank, loop, line)
        # Evacuate surplus to create a protected return slot, including full loops.
        if not matching or len(self.queues[loop]) >= self.high_water:
            for identity in available:
                if self.shades[identity] != wanted:
                    destination = ("bank", line, self.shades[identity])
                    if self.room(destination):
                        return self._start(identity, loop, destination, line)
        return None

    def take(self, cell, shade):
        port = ("loop", cell)
        for identity in self.queues[port]:
            if identity not in self.busy_ids and self.shades[identity] == shade:
                self.queues[port].remove(identity)
                self.output.append(identity)
                return identity
        return None

    def complete(self, transfer):
        if self.inflight.get(transfer.number) != transfer:
            raise ValueError("Transfer is not pending")
        if transfer.source[0] != "external":
            self.queues[transfer.source].remove(transfer.identity)
        self.queues[transfer.destination].append(transfer.identity)
        self._release(transfer)
        self.events.append({"kind": "transfer_completed", "id": transfer.identity,
                            "destination": transfer.destination})
        self.audit()

    def cancel(self, transfer):
        if self.inflight.get(transfer.number) != transfer:
            raise ValueError("Transfer is not pending")
        self._release(transfer)
        if transfer.source[0] == "external":
            del self.shades[transfer.identity]
        self.events.append({"kind": "transfer_cancelled", "id": transfer.identity})
        self.audit()

    def _release(self, transfer):
        del self.inflight[transfer.number]
        self.reserved[transfer.destination] -= 1
        self.busy_ids.remove(transfer.identity)
        if transfer.line is not None:
            self.busy_lines.remove(transfer.line)

    def audit(self):
        physical = [i for queue in self.queues.values() for i in queue] + self.output
        # Incoming external material is held at its admission interface until ACK.
        external = [t.identity for t in self.inflight.values() if t.source[0] == "external"]
        ids = physical + external
        if len(ids) != len(set(ids)) or set(ids) != set(self.shades):
            raise AssertionError("Material identity / ownership mismatch")
        for port, queue in self.queues.items():
            if len(queue) + self.reserved[port] > self.capacity(port):
                raise AssertionError("Destination capacity exceeded")
            if port[0] == "bank" and any(self.shades[i] != port[2] for i in queue):
                raise AssertionError("Wrong colour in FIFO bank")
        return True

    def snapshot(self):
        return {"loops": [len(self.queues["loop", c]) for c in range(8)],
                "banks": [{s: len(self.queues["bank", line, s]) for s in SHADES} for line in range(2)],
                "in_transit": len(self.inflight), "accepted": len(self.shades),
                "issued": len(self.output), "capacity_per_colour": self.capacity_per_colour}


def pallets_per_hour(completed_pallets, elapsed_seconds):
    if not math.isfinite(elapsed_seconds) or elapsed_seconds <= 0:
        raise ValueError("Positive elapsed time required")
    if type(completed_pallets) is not int or completed_pallets < 0:
        raise ValueError("Completed pallet count must be nonnegative")
    return completed_pallets * 3600 / elapsed_seconds
