"""Local filesystem ownership and durable JSON records for script execution."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4


class ScriptBusyError(RuntimeError):
    pass


class ScriptCancelledError(RuntimeError):
    """Raised when an explicitly cancelled or fenced worker attempts to persist state."""


class RunControl:
    """
    Per-run cancellation, timeout, and completion coordinator scoped strictly to a single `run_id`.
    - Separates wall-clock deadline expiration (`timeout_event`) from explicit cancellation (`cancel_event`).
    - Prevents an old run's timer from affecting a newer run or converting a completed run into a failure.
    """

    def __init__(self, run_id: str, timeout_seconds: float) -> None:
        self.run_id = run_id
        self.timeout_seconds = float(timeout_seconds)
        self.deadline_monotonic = time.monotonic() + self.timeout_seconds
        self.cancel_event = threading.Event()
        self.timeout_event = threading.Event()
        self.completed_event = threading.Event()
        self._timer: threading.Timer | None = None

    def start_deadline_timer(self) -> None:
        timer = threading.Timer(self.timeout_seconds, self.mark_timeout, args=(self.run_id,))
        timer.daemon = True
        self._timer = timer
        timer.start()

    def mark_timeout(self, expected_run_id: str) -> None:
        if expected_run_id != self.run_id or self.completed_event.is_set():
            return
        self.timeout_event.set()

    def cancel(self, expected_run_id: str) -> None:
        if expected_run_id != self.run_id or self.completed_event.is_set():
            return
        self.cancel_event.set()

    def mark_completed(self) -> None:
        self.completed_event.set()
        if self._timer is not None:
            self._timer.cancel()

    def stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set() and not self.completed_event.is_set()

    def is_timed_out(self) -> bool:
        if self.completed_event.is_set():
            return False
        return self.timeout_event.is_set() or (time.monotonic() >= self.deadline_monotonic)

    def remaining_seconds(self) -> float:
        return self.deadline_monotonic - time.monotonic()


_threads = {}
_guard = threading.Lock()


@contextmanager
def exclusive(path, wait_seconds: float = 0.0):
    """
    Per-project OS-backed exclusive lock (threading.Lock + Windows msvcrt.locking / POSIX fcntl.flock).
    When wait_seconds == 0.0, fails immediately with ScriptBusyError if another thread or process holds the lock.
    """
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _guard:
        lock = _threads.setdefault(str(path).casefold(), threading.Lock())

    deadline = time.monotonic() + max(0.0, wait_seconds)
    thread_acquired = lock.acquire(blocking=False)
    while not thread_acquired and time.monotonic() < deadline:
        time.sleep(0.01)
        thread_acquired = lock.acquire(blocking=False)
    if not thread_acquired:
        raise ScriptBusyError("This project already has an active operation. Retry after it finishes.")

    stream = None
    acquired = False
    try:
        stream = path.open("a+b")
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        while True:
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if time.monotonic() < deadline:
                    time.sleep(0.01)
                    continue
                raise ScriptBusyError("This project is owned by another process. Retry after it finishes.") from exc
        yield
    finally:
        if stream:
            if acquired:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream, fcntl.LOCK_UN)
                except OSError:
                    pass
            stream.close()
        lock.release()


def is_locked(path) -> bool:
    """Return True if another thread or process currently holds the OS exclusive lock on `path`."""
    try:
        with exclusive(path, wait_seconds=0.0):
            return False
    except ScriptBusyError:
        return True


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def save_record(path, data):
    atomic_json(path, {"checksum": digest(data), "data": data})


def load_record(path):
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(record, dict) or "data" not in record or "checksum" not in record:
            raise ValueError("Invalid record envelope")
        data = record["data"]
        if not isinstance(data, dict) or record["checksum"] != digest(data):
            raise ValueError("Checksum mismatch")
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Recovery record is missing or corrupt: {Path(path).name}. Preserve it for review.") from exc


class RequestLedger:
    """
    Durable, checksummed, OS-locked per-project request budget ledger.
    - Preserves cumulative reservation ceiling across restarts and stale manifest writes.
    - Distinguishes reserved requests (written pre-transport) from completed/failed responses (written post-transport).
    - Rejects invalid or corrupt accounting rather than resetting to zero.
    """

    def __init__(self, directory, ceiling, legacy_count=0, required=False):
        self.path = Path(directory) / "script_requests.json"
        self.lock = Path(directory) / ".script_requests.lock"
        if not isinstance(ceiling, int) or ceiling < 1:
            raise ValueError("Invalid approved request ceiling.")
        with exclusive(self.lock, wait_seconds=5.0):
            if not self.path.exists():
                if required:
                    raise ValueError("Request accounting file is missing. Generation is blocked.")
                if not isinstance(legacy_count, int) or legacy_count < 0:
                    raise ValueError("Invalid previous request accounting.")
                save_record(
                    self.path,
                    {"ceiling": ceiling, "legacy_count": legacy_count, "reservations": [], "outcomes": {}},
                )
            self.read()
        self.ceiling = ceiling

    def read(self):
        data = load_record(self.path)
        records = data.get("reservations")
        outcomes = data.get("outcomes", {})
        if (
            not isinstance(records, list)
            or not isinstance(outcomes, dict)
            or not isinstance(data.get("ceiling"), int)
            or data["ceiling"] < 1
            or not isinstance(data.get("legacy_count"), int)
            or data["legacy_count"] < 0
            or not all(isinstance(r, str) and len(r) == 32 for r in records)
            or len(set(records)) != len(records)
        ):
            raise ValueError("Request accounting is inconsistent. Generation is blocked.")
        return data

    def reserve(self):
        with exclusive(self.lock, wait_seconds=5.0):
            data = self.read()
            effective_ceiling = min(self.ceiling, data["ceiling"])
            if data["legacy_count"] + len(data["reservations"]) >= effective_ceiling:
                raise ValueError("Approved cumulative script request limit reached.")
            reservation = uuid4().hex
            data["reservations"].append(reservation)
            outcomes = data.setdefault("outcomes", {})
            outcomes[reservation] = {"status": "reserved", "time": time.time()}
            save_record(self.path, data)
            return reservation

    def record_outcome(
        self,
        reservation_id: str,
        status: str,
        http_status=None,
        routed_model=None,
        category=None,
    ):
        """Record the terminal response outcome for an existing reservation ID without altering the reservation count."""
        if not reservation_id:
            return
        with exclusive(self.lock, wait_seconds=5.0):
            data = self.read()
            if reservation_id not in data["reservations"]:
                raise ValueError(f"Unknown reservation ID '{reservation_id}' in request ledger.")
            outcomes = data.setdefault("outcomes", {})
            outcomes[reservation_id] = {
                "status": status,
                "http_status": http_status,
                "routed_model": routed_model,
                "category": category,
                "time": time.time(),
            }
            save_record(self.path, data)

    @property
    def count(self):
        data = self.read()
        return data["legacy_count"] + len(data["reservations"])

    @property
    def completed_count(self):
        data = self.read()
        outcomes = data.get("outcomes", {})
        return sum(1 for v in outcomes.values() if isinstance(v, dict) and v.get("status") == "completed")

    @property
    def reserved_pending_count(self):
        data = self.read()
        outcomes = data.get("outcomes", {})
        return sum(1 for r in data["reservations"] if (outcomes.get(r) or {}).get("status", "reserved") == "reserved")
