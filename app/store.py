"""
MySQL-backed storage for lots and events.

This replaces the in-memory dictionaries from Day 2 (kept for
reference in store_inmemory.py) with real SQL queries against the
`lot_tracking` MySQL database. Every method here has the EXACT same
name, parameters, and return type as the in-memory version - that
was the whole point of building this as a Store class with a fixed
set of methods back on Day 2. app/main.py (our API routes) does not
need to change at all.

Key new concepts introduced here, explained inline as they appear:
  - a database CONNECTION (opening a line to the MySQL server)
  - a CURSOR (the object you actually run SQL through, and read
    results back from)
  - PARAMETERIZED QUERIES (using %s placeholders instead of pasting
    values directly into the SQL string - this prevents SQL
    injection, a real security vulnerability, and is standard
    practice in every production codebase)
"""

import os
from datetime import datetime, timezone

import mysql.connector
from dotenv import load_dotenv

from .models import Lot, LotEvent, LotState, ProcessStep, HoldReason

# Load variables from the .env file (DB_HOST, DB_USER, DB_PASSWORD,
# DB_NAME) into the environment, so os.environ can see them below.
# This call is safe to make multiple times and does nothing if no
# .env file is present.
load_dotenv()


class LotNotFoundError(Exception):
    """Raised when a lookup is done for a lot_id that doesn't exist."""
    pass


def _get_connection():
    """
    Open a new connection to MySQL using credentials from the
    environment (which load_dotenv() populated from .env).

    We open a FRESH connection per call rather than holding one open
    for the app's whole lifetime - simpler to reason about for a
    project this size, at the cost of being slightly slower than a
    pooled connection. Connection pooling is a real optimization
    worth knowing about, but it's an upgrade we can layer in later
    rather than something we need on day one.

    os.environ[...] (vs os.environ.get(...)) deliberately raises a
    clear KeyError immediately if a variable is missing from .env,
    rather than silently connecting with a blank value and failing
    confusingly later.
    """
    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
    )


def _as_utc(naive_dt: datetime) -> datetime:
    """
    Re-attach UTC timezone info to a naive datetime read back from
    MySQL.

    MySQL's DATETIME column type stores no timezone information at
    all - it's just numbers (year, month, day, hour, minute, second).
    We always WRITE UTC times into it (see datetime.now(timezone.utc)
    throughout this file), so by our own convention every value that
    comes back out should be interpreted as UTC too - but Python has
    no way to know that on its own, since the database genuinely
    didn't store it. This function makes that convention explicit
    instead of leaving it as an unstated assumption, and is the one
    place we need to fix if that convention ever changed.
    """
    return naive_dt.replace(tzinfo=timezone.utc)


def _row_to_lot(row: dict) -> Lot:
    """Convert one row from the `lots` table (as a dict) into our Lot dataclass."""
    return Lot(
        lot_id=row["lot_id"],
        wafer_count=row["wafer_count"],
        current_step=ProcessStep(row["current_step"]),
        current_eqp_id=row["current_eqp_id"],
        current_state=LotState(row["current_state"]),
    )


def _row_to_event(row: dict) -> LotEvent:
    """Convert one row from the `lot_events` table (as a dict) into our LotEvent dataclass."""
    return LotEvent(
        event_id=row["event_id"],
        lot_id=row["lot_id"],
        step_id=ProcessStep(row["step_id"]),
        eqp_id=row["eqp_id"],
        state=LotState(row["state"]),
        hold_reason=HoldReason(row["hold_reason"]) if row["hold_reason"] else None,
        timestamp=_as_utc(row["timestamp"]),
    )


class Store:
    """
    Same public interface as the in-memory Store (store_inmemory.py),
    now backed by MySQL. No __init__ state is needed anymore - there's
    nothing to initialize in Python, since MySQL itself holds all the
    data now, not an in-memory dict.
    """

    def create_lot(
        self,
        lot_id: str,
        wafer_count: int,
        step_id: ProcessStep,
        eqp_id: str,
    ) -> Lot:
        now = datetime.now(timezone.utc)

        conn = _get_connection()
        # dictionary=True makes the cursor return rows as dicts
        # (column_name -> value) instead of plain tuples - much
        # easier to read and matches what _row_to_lot/_row_to_event
        # expect above.
        cursor = conn.cursor(dictionary=True)
        try:
            # %s is a placeholder - mysql-connector substitutes the
            # values from the tuple SAFELY (escaping anything that
            # could otherwise be interpreted as SQL syntax). Never
            # build a query with an f-string like f"... = '{lot_id}'"
            # - that's the classic SQL injection vulnerability.
            cursor.execute(
                """
                INSERT INTO lots (lot_id, wafer_count, current_step, current_eqp_id, current_state)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (lot_id, wafer_count, step_id.value, eqp_id, LotState.WAITING.value),
            )
            cursor.execute(
                """
                INSERT INTO lot_events (lot_id, step_id, eqp_id, state, hold_reason, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (lot_id, step_id.value, eqp_id, LotState.WAITING.value, None, now),
            )
            # Nothing is actually saved to disk until we commit -
            # MySQL groups statements into a transaction, and commit()
            # makes them permanent. This also means if the second
            # INSERT had failed, the first one could be rolled back -
            # we're not handling that rollback explicitly yet (a
            # reasonable next-step improvement), but it's worth
            # knowing the concept exists.
            conn.commit()
        finally:
            cursor.close()
            conn.close()

        return Lot(
            lot_id=lot_id,
            wafer_count=wafer_count,
            current_step=step_id,
            current_eqp_id=eqp_id,
            current_state=LotState.WAITING,
        )

    def get_lot(self, lot_id: str) -> Lot:
        conn = _get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM lots WHERE lot_id = %s", (lot_id,))
            row = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

        if row is None:
            raise LotNotFoundError(lot_id)
        return _row_to_lot(row)

    def get_events(self, lot_id: str) -> list[LotEvent]:
        conn = _get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Confirm the lot itself exists first, so we raise the
            # same LotNotFoundError the in-memory version did for an
            # unknown lot_id (a lot with zero events would otherwise
            # be indistinguishable from a lot that doesn't exist).
            cursor.execute("SELECT 1 FROM lots WHERE lot_id = %s", (lot_id,))
            if cursor.fetchone() is None:
                raise LotNotFoundError(lot_id)

            cursor.execute(
                "SELECT * FROM lot_events WHERE lot_id = %s ORDER BY timestamp",
                (lot_id,),
            )
            rows = cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

        return [_row_to_event(row) for row in rows]

    def record_event(
        self,
        lot_id: str,
        step_id: ProcessStep,
        eqp_id: str,
        state: LotState,
        hold_reason: HoldReason | None = None,
    ) -> LotEvent:
        now = datetime.now(timezone.utc)

        conn = _get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT 1 FROM lots WHERE lot_id = %s", (lot_id,))
            if cursor.fetchone() is None:
                raise LotNotFoundError(lot_id)

            cursor.execute(
                """
                INSERT INTO lot_events (lot_id, step_id, eqp_id, state, hold_reason, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    lot_id,
                    step_id.value,
                    eqp_id,
                    state.value,
                    hold_reason.value if hold_reason else None,
                    now,
                ),
            )
            new_event_id = cursor.lastrowid  # AUTO_INCREMENT value MySQL just assigned

            cursor.execute(
                """
                UPDATE lots
                SET current_step = %s, current_eqp_id = %s, current_state = %s
                WHERE lot_id = %s
                """,
                (step_id.value, eqp_id, state.value, lot_id),
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

        return LotEvent(
            event_id=new_event_id,
            lot_id=lot_id,
            step_id=step_id,
            eqp_id=eqp_id,
            state=state,
            hold_reason=hold_reason,
            timestamp=now,
        )

    def last_event_timestamp(self, lot_id: str) -> datetime:
        """Timestamp of the most recent event - used to compute 'since' / time-in-state."""
        events = self.get_events(lot_id)
        return max(e.timestamp for e in events)


# A single shared Store instance, same as Day 2 - app/main.py imports
# this directly. Since each method now opens/closes its own MySQL
# connection rather than holding Python state, this object is
# effectively stateless - it exists mainly so main.py's import stays
# unchanged.
store = Store()