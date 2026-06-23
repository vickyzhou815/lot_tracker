"""
In-memory storage for lots and events.

This is a deliberately simple stand-in for a real database, scoped
to today (Day 2) so we can run and test the full API before MySQL
is wired up (Day 3). The key design choice: routes will call methods
on this `Store` class, not touch dictionaries directly. When we swap
in MySQL later, we replace the BODY of these methods (SQL queries
instead of dict lookups) while keeping the same method signatures -
the route handlers won't need to change at all.

C++ comparison: this is the Repository pattern - similar to hiding a
database behind an interface/abstract base class so callers depend
on the interface, not the concrete storage mechanism.
"""

from datetime import datetime, timezone

from .models import Lot, LotEvent, LotState, ProcessStep, HoldReason


class LotNotFoundError(Exception):
    """Raised when a lookup is done for a lot_id that doesn't exist."""
    pass


class Store:
    def __init__(self) -> None:
        # lot_id -> Lot (current snapshot)
        self._lots: dict[str, Lot] = {}
        # lot_id -> list of LotEvent, in insertion order (our append-only log)
        self._events: dict[str, list[LotEvent]] = {}
        # simple counter to assign event_id, stands in for an AUTO_INCREMENT PK
        self._next_event_id = 1

    def create_lot(
        self,
        lot_id: str,
        wafer_count: int,
        step_id: ProcessStep,
        eqp_id: str,
    ) -> Lot:
        now = datetime.now(timezone.utc)
        lot = Lot(
            lot_id=lot_id,
            wafer_count=wafer_count,
            current_step=step_id,
            current_eqp_id=eqp_id,
            current_state=LotState.WAITING,
        )
        self._lots[lot_id] = lot
        # The lot's creation is itself the first event in its history -
        # this keeps the event log as the single source of truth from
        # the very first moment the lot exists.
        self._events[lot_id] = [
            LotEvent(
                lot_id=lot_id,
                step_id=step_id,
                eqp_id=eqp_id,
                state=LotState.WAITING,
                timestamp=now,
                event_id=self._next_event_id,
            )
        ]
        self._next_event_id += 1
        return lot

    def get_lot(self, lot_id: str) -> Lot:
        if lot_id not in self._lots:
            raise LotNotFoundError(lot_id)
        return self._lots[lot_id]

    def get_events(self, lot_id: str) -> list[LotEvent]:
        if lot_id not in self._events:
            raise LotNotFoundError(lot_id)
        return self._events[lot_id]

    def record_event(
        self,
        lot_id: str,
        step_id: ProcessStep,
        eqp_id: str,
        state: LotState,
        hold_reason: HoldReason | None = None,
    ) -> LotEvent:
        if lot_id not in self._lots:
            raise LotNotFoundError(lot_id)

        now = datetime.now(timezone.utc)
        event = LotEvent(
            lot_id=lot_id,
            step_id=step_id,
            eqp_id=eqp_id,
            state=state,
            timestamp=now,
            hold_reason=hold_reason,
            event_id=self._next_event_id,
        )
        self._next_event_id += 1
        self._events[lot_id].append(event)

        # Update the current snapshot to match the latest event.
        lot = self._lots[lot_id]
        lot.current_step = step_id
        lot.current_eqp_id = eqp_id
        lot.current_state = state

        return event

    def last_event_timestamp(self, lot_id: str) -> datetime:
        """Timestamp of the most recent event - used to compute 'since' / time-in-state."""
        events = self.get_events(lot_id)
        return max(e.timestamp for e in events)


# A single shared Store instance for the app's lifetime. FastAPI will
# import this directly for now; Day 3 will replace this pattern with
# a proper dependency-injected database session instead of a module-
# level singleton, which is the more production-realistic approach.
store = Store()
