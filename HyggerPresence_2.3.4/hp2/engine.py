"""Hygger Presence 2.0 (Qt) - engine.

UI-free: process detection (reused from the 1.x package), Discord RPC, the session
clock and playtime recording. The Qt layer only polls `Engine.tick()` and renders
what the engine exposes.

Detection itself is *not* rewritten here: `app.detector.DetectorMixin` is imported
from the 1.x tree, so 2.0 keeps the same matching rules (path > same name+folder >
process_names > other exe in the game folder > unique name) that were debugged in
1.0.3/1.0.4.
"""
import os
import queue
import threading
import time
from pathlib import Path

from .core import format_time, debug_log, SMART_TIME_FORMAT
from .detector import DetectorMixin
from .winapi import snapshot_processes, wait_for_process_exit

MAX_LINE = 128
RPC_CALL_TIMEOUT = 10.0      # a single Discord call may not take longer
RPC_LOCK_TIMEOUT = 5.0       # nor may waiting for the rpc lock
KEEPALIVE = 20.0            # Discord allows 5 updates / 20 s; 3 of them as keepalive
# One process snapshot without the game is not a close: a game that renames its
# own exe, or a slow Toolhelp snapshot, is back a moment later, and clearing on
# the first miss made the Discord card vanish for no reason.
MISSING_GRACE = 2.0
MIN_PUSH_INTERVAL = 0.8        # floor between two sends
PUSH_BURST = 5                 # Discord allows 5 updates ...
PUSH_WINDOW = 20.0             # ... per 20 s, so allow exactly that             # 1.0.3 pushed every 55 s; Discord allows 5 per 20 s
STATUS_DEBOUNCE = 1.0         # a new status must hold this long before it is pushed
RPC_STALL = 8.0               # a Discord call slower than this gets reconnected


def _clip(value, limit=MAX_LINE):
    """Discord rejects name / details / state longer than 128 characters."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"


def _subst(text, mapping):
    """Fill in every {token} this app knows; unknown tokens are left alone."""
    text = str(text or "")
    for key, value in mapping.items():
        text = text.replace("{%s}" % key, str(value))
    return text


def _rating_text(value):
    """Rating on the 0-10 scale with two decimals, or N/A.

    The v2 API reports 0-100 (87.5 for the 8.75 the site shows) and games saved
    by older builds may already hold a scaled-up number, so anything above 10
    is divided back down before it reaches a template.
    """
    if value in (None, "", "N/A"):
        return "N/A"
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return str(value)
    if number > 10:
        number /= 10.0
    return "%.2f" % number

POLL_INTERVAL = 1.0
SCAN_INTERVAL = 3.0
IDLE_SCAN_INTERVAL = 2.0      # nothing tracked: full process scan this often          # 1.0.3 used 3 s; the tick itself is ~0.04 ms
# A game that closes keeps its session this long, so a restart, a launcher
# handing over to the engine or a game renaming its own exe continue the same
# session, while anything slower starts a fresh one.
SESSION_GRACE = 8.0
IDLE_SECONDS_DEFAULT = 300      # 5 minutes before the status turns Idle
IDLE_SECONDS_MIN = 10           # the slider/field never goes below this
IDLE_SECONDS_MAX = 4 * 60 * 60  # 4 hours; beyond that it is "never"
IDLE_THRESHOLD = IDLE_SECONDS_DEFAULT   # name kept for older callers

DEFAULT_TEMPLATES = {
    "Reading": {"name": "{title}", "details": "{developer} | {year}",
                "state": "{status} • Total {total_time}"},
    "Paused": {"name": "{title}", "details": "{developer} | {year}",
               "state": "{status} • Session {session_time} • Total {total_time}"},
    "Idle": {"name": "{title}", "details": "{developer} | {year}",
             "state": "{status} • Session {session_time} • Total {total_time}"},
}


class Engine(DetectorMixin):
    """Detection + presence. Poll `tick()` about once a second from the UI thread."""

    def __init__(self, client_id="", templates=None, stats=None, on_change=None,
                 presence=None, idle_seconds=None):
        self.games = []
        # how long the user may be away before the card says Idle
        self.idle_seconds = self._clamp_idle(idle_seconds)
        self.client_id = client_id or ""
        self.templates = templates or DEFAULT_TEMPLATES
        self.opts = presence or {}
        self.stats = stats
        self.on_change = on_change          # callable(engine) after every change
        self.on_save = None                 # callable() after mutating a game dict
        self._debug = lambda *_a, **_k: None

        # detector caches (DetectorMixin expects these on self)
        self._scan_cache_game = None
        self._scan_cache_pids = set()
        self._scan_cache_time = 0.0
        self._vndb_retry_at = {}
        self._stat_buffer = 0.0          # seconds not yet written (short stretches)
        self._stat_buffer_game = None
        self._pushed_identity = None    # (exe, vndb_id) of the last presence push
        self._pushed_status = None      # status that actually reached Discord
        self._status_candidate = None   # (status, since) waiting to be stable
        self._tick_busy = False
        self._rpc_thread = None         # supervisor owning every Discord call
        self._rpc_stop = threading.Event()
        self._desired = ("none", None)  # latest wanted action, never a queue
        self._watchdog_busy = False
        self._next_push_at = 0.0        # rate-limit backoff
        self._missing_since = None      # first tick that did not see the game
        self._wake = threading.Event()  # supervisor wakes up immediately
        self._push_token = 0            # guard against late (orphan) sends
        self.pinned_exe = None          # manual override from the UI
        self._meta_thread = None
        self._meta_queue = None
        self.error_count = 0
        self._retry_count = 0

        # presence state
        self.rpc = None
        self._rpc_lock = threading.RLock()
        self.presence_enabled = True
        self.game = None
        self.status = None
        self.preview = {}
        self.session_seconds = 0.0
        self.total_seconds = 0.0
        self.last_error = ""
        self._reading_start = None
        self._session_accumulated = 0.0
        # key -> [seconds, missing_since]: a session belongs to a *running* game,
        # so switching between two open games never restarts either one. A game
        # that exits keeps its entry for SESSION_GRACE seconds, which is what lets
        # a restart, a launcher handing over to the engine or a game renaming its
        # own exe continue the same session.
        self._session_memory = {}
        self._session_games = {}       # key -> game dict (liveness + banking)
        self._session_key = None
        self._card_shown = False       # True while a card is on the profile
        self._last_sent = 0.0
        self._exit_watch = {}
        # routes: each game owns {"routes": [{"name", "seconds"}], "route": name}

    # ---------------------------------------------------------------- detection
    def scan(self, force=False):
        now = time.time()
        # while nothing is tracked, look again soon — but not on every tick. A
        # full process scan every second was the biggest idle CPU cost, and two
        # seconds is still fast enough for a freshly launched game to show up.
        if self._scan_cache_game is None:
            if not force and (now - self._scan_cache_time) < IDLE_SCAN_INTERVAL:
                return None, ()
            force = True
        if not force and self._scan_cache_game is not None and \
                (now - self._scan_cache_time) < SCAN_INTERVAL:
            return self._scan_cache_game, self._scan_cache_pids
        game, pids = self.find_active_game()
        self._scan_cache_game, self._scan_cache_pids = game, pids
        self._scan_cache_time = now
        return game, pids

    def _ensure_metadata(self, game):
        """Refill missing VNDB fields (1.x did this on every presence update)."""
        needs = (not game.get("developer") or game.get("developer") == "Unknown"
                 or not game.get("rating_average") or game.get("rating_average") == "N/A"
                 or not game.get("romanized"))
        if not needs or not game.get("vndb_id"):
            return
        now = time.time()
        if now < self._vndb_retry_at.get(game["vndb_id"], 0.0):
            return
        if self._meta_queue is None:
            self._meta_queue = queue.Queue()
            self._meta_thread = threading.Thread(target=self._meta_loop,
                                                 name="hp-vndb", daemon=True)
            self._meta_thread.start()
        self._vndb_retry_at[game["vndb_id"]] = now + 300          # one try per 5 min
        self._meta_queue.put(game)

    def _meta_loop(self):
        while True:
            game = self._meta_queue.get()
            try:
                if game is None:
                    return
                try:
                    from .vndb import fetch_vndb
                    info = fetch_vndb(game.get("vndb_id", ""))
                except Exception as error:
                    debug_log("vndb refresh failed: %s" % error)
                    info = None
                if info:
                    self._apply_metadata(game, info)
            finally:
                self._meta_queue.task_done()

    def _apply_metadata(self, game, info):
        self._vndb_retry_at.pop(game.get("vndb_id"), None)
        game.update({
            "developer": info.get("developer") or "Unknown",
            "year": info.get("year") or "????",
            "image": info.get("image") or game.get("image"),
            "original": info.get("original") or game.get("original"),
            "title": info.get("original") or game.get("title"),
            "romanized": info.get("romanized") or game.get("romanized", ""),
        })
        # Only overwrite a rating the API actually has: v2 dropped the Bayesian
        # number, and a refresh used to replace a stored one with "N/A".
        for key in ("rating_average", "rating_weighted"):
            value = info.get(key)
            if value and value != "N/A":
                game[key] = _rating_text(value)
        if self.on_save:
            try:
                self.on_save()
            except Exception:
                pass

    def _hard_reset(self):
        """Drop the connection without touching the UI state (called by the worker)."""
        self._next_push_at = 0.0
        self._pushed_identity = None
        presence, self.rpc = self.rpc, None
        if presence is not None:
            self._close_async(presence)

    def pending_seconds(self):
        """Seconds that are not in stats.db yet: the buffer plus the open segment."""
        total = self._stat_buffer
        game = self._stat_buffer_game
        if self._reading_start is not None:
            now = time.time()
            if self.status == "Idle":
                from .winapi import get_idle_seconds
                total += max(0.0, (now - get_idle_seconds()) - self._reading_start)
            else:
                total += max(0.0, now - self._reading_start)
            if game is None:
                game = self.game
        return total, game

    def clear_now(self):
        """Clear the Discord card now; the next tick republishes it (1.x behaviour)."""
        self._clear()
        self.status = None
        self._last_sent = 0.0
        self._notify()

    def _pids_alive(self, pids):
        """Any of these pids still running? (lived in the 1.x watcher mixin)"""
        import psutil
        for pid in pids or ():
            try:
                if psutil.pid_exists(pid):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _names_of(game):
        names = set()
        if game.get("exe"):
            names.add(Path(game["exe"]).name.lower())
        for extra in game.get("process_names") or ():
            extra = str(extra).strip().lower()
            if extra:
                names.add(extra)
        return names

    def process_matches(self, game, name, path=None):
        """Same name, an extra process name, or any exe in the game's own folder.

        Games that hand over to a launcher (sayagatari_chs.exe -> SiglusEngine.exe)
        are only found by the folder rule.
        """
        if not name:
            return False
        lowered = str(name).lower()
        if lowered in self._names_of(game):
            return True
        folder = Path(game.get("exe", "")).parent if game.get("exe") else None
        if folder and path:
            try:
                if Path(path).parent == folder:
                    return True
            except Exception:
                return False
        return False

    def _names_with_learned(self, game):
        names = self._names_of(game)
        extra = getattr(self, "_learned_names", {}).get(game.get("exe") or "", set())
        return names | set(extra)

    def pids_for_game(self, game):
        """Running pids that belong to this library entry.

        This used to walk psutil.process_iter() and call process.exe() for every
        process on the machine (about 300 open handles + path resolves) — 10 ms
        every single tick, i.e. the largest idle cost of the whole app. The
        detector's Toolhelp snapshot answers the same question from one
        enumeration and reads an exe path only for processes whose *name* could
        match, which costs about 0.1 ms while a game is tracked.
        """
        if not game:
            return set()
        try:
            return self.get_game_pids(game)
        except Exception:
            return self._pids_for_game_psutil(game)

    def _pids_for_game_psutil(self, game):
        """Fallback for a Toolhelp failure: the old, slow but portable version."""
        import psutil
        found = set()
        for process in psutil.process_iter(["pid", "name"]):
            try:
                name = process.info.get("name") or ""
                try:
                    path = process.exe()
                except Exception:
                    path = None
                if self.process_matches(game, name, path):
                    found.add(process.info["pid"])
            except Exception:
                continue
        return found

    def pids_for_exe(self, exe_path):
        game = next((g for g in self.games if g.get("exe") == exe_path), None)
        return self.pids_for_game(game)

    def running_games(self):
        """[(game, running exe name)] for every library entry running right now.

        Measured at 114 ms in 2.1.x: it walked psutil.process_iter() once per
        library entry and called process.exe() for every process, so 12 games
        meant 3600 handle opens. The pinned-game dropdown calls this every six
        seconds, which alone kept the app at ~2 % of a core. One Toolhelp
        snapshot plus the name filter below answers it in ~1 ms.
        """
        try:
            rows = snapshot_processes()
        except Exception:
            rows = ()
        names_now = {name for _pid, _ppid, name in rows if name}
        alive = []
        for game in self.games:
            names = self._names_of(game)
            hit = next((name for name in names if name in names_now), "")
            if not hit:
                # a differently named exe started from the game's own folder
                # (patched exe, bundled engine) still belongs to the entry
                if self.pids_for_game(game):
                    hit = Path(game.get("exe", "")).name or game.get("title", "")
            if hit:
                alive.append((game, hit))
        return alive

    def set_pin(self, exe_path):
        self.pinned_exe = exe_path or None

    def game_of_window(self, hwnd):
        """The library entry that owns this window, if any.

        Used by the window-show hook while the app is idle: a game that starts
        without taking focus should still be picked up within ~120 ms instead of
        waiting for the 10 s safety probe.
        """
        try:
            from .winapi import get_window_pid
            import psutil
            pid = get_window_pid(hwnd)
            if not pid:
                return None
            process = psutil.Process(pid)
            name = (process.name() or "").lower()
            if not name:
                return None
            try:
                path = process.exe()
            except Exception:
                path = None
        except Exception:
            return None
        for game in self.games:
            if self.process_matches(game, name, path):
                return game
        return None

    def _focused_library_game(self):
        """The library game that owns the foreground window, if any."""
        try:
            from .winapi import get_foreground_pid
            import psutil
            pid = get_foreground_pid()
            if not pid:
                return None
            process = psutil.Process(pid)      # one handle, not two
            name = (process.name() or "").lower()
            if not name:
                return None
            try:
                path = process.exe()
            except Exception:
                path = None
        except Exception:
            return None
        for game in self.games:
            if self.process_matches(game, name, path):
                return game
        return None

    def _status_for(self, game, pids):
        if not pids:
            return "Idle"
        focus, why = self.resolve_focus(game, pids)
        if focus == "paused":
            return "Paused"
        from .winapi import get_idle_seconds
        if get_idle_seconds() >= self.idle_seconds:
            return "Idle"
        return "Reading"

    # ------------------------------------------------------------------- rpc
    # ------------------------------------------------------- rpc executor
    def _wake_thread(self):
        """Start the supervisor if needed and nudge it so the call runs now."""
        if self._rpc_thread is None or not self._rpc_thread.is_alive():
            self._rpc_thread = threading.Thread(target=self._rpc_supervisor,
                                                name="hp-rpc", daemon=True)
            self._rpc_thread.start()
        self._wake.set()

    def _submit(self, func, *args):
        """Remember the wanted action; the supervisor performs it (never blocks)."""
        if func == self._do_clear:
            self._desired = ("clear", None)
        elif func == self._do_push and args:
            self._desired = ("push", args)
        elif func is not None:
            self._desired = ("call", (func, args))
        self._wake_thread()

    def _rpc_supervisor(self):
        """Owns the connection: one action at a time, every call time-boxed."""
        while not self._rpc_stop.is_set():
            action, payload = self._desired
            if action == "none":
                self._wake.wait(0.25)
                self._wake.clear()
                continue
            if action == "push" and time.time() < self._next_push_at:
                # respect the rate-limit backoff, but keep the payload queued
                self._desired = (action, payload)
                time.sleep(0.3)
                continue
            if action == "push" and self._retry_count >= 2:
                # two failures in a row: rebuild the connection from scratch
                self._retry_count = 0
                self._hard_reset()
                continue
            self._desired = ("none", None)
            try:
                if action == "clear":
                    self._run_with_deadline(self._do_clear)
                elif action == "push":
                    self._run_with_deadline(self._do_push, *payload)
                else:
                    self._run_with_deadline(payload[0], *payload[1])
            except Exception as error:
                self._mark_dead(error)
                if action == "push":
                    self._retry_count += 1
                    self._desired = (action, payload)     # retry after the backoff
            time.sleep(0.02)

    def _run_with_deadline(self, func, *args, timeout=None):
        """Run the Discord call and notice when it stalls (2.3.0.1).

        Blocking here is deliberate: an abandoned pypresence call kept holding
        the IPC pipe, so every later call timed out and only a restart helped
        (1.0.3 regression). The UI thread never calls this.

        A call that takes longer than RPC_STALL means Discord stopped answering
        mid-call (client restart, sleep, wedged pipe). The update may even have
        been applied, but the socket cannot be trusted any more: raise so the
        supervisor marks the connection dead and the next push reconnects,
        instead of leaving the card frozen for minutes.
        """
        name = getattr(func, "__name__", "call")
        started = time.time()
        func(*args)
        elapsed = time.time() - started
        if elapsed > RPC_STALL:
            debug_log("rpc %s stalled for %.1fs - reconnecting" % (name, elapsed))
            raise RuntimeError("rpc stalled for %.1fs" % elapsed)
        if elapsed > 1.0:
            debug_log("rpc %s took %.1fs" % (name, elapsed))

    def _rpc_alive(self):
        """Best-effort check that the IPC socket still works.

        pypresence has no health check, and a Discord restart closes the pipe
        without telling us; without this the card stayed missing until the next
        keepalive reconnected.
        """
        presence = self.rpc
        if presence is None:
            return False
        writer = getattr(presence, "sock_writer", None)
        if writer is None:
            return False
        try:
            return not writer.is_closing()
        except Exception:
            return True

    def _mark_dead(self, error):
        """Drop the connection so the next action reconnects from scratch."""
        debug_log("rpc marked dead: %s" % error)
        self.last_error = "rpc: %s" % error
        lowered = str(error).lower()
        self._next_push_at = time.time() + (60.0 if "rate" in lowered else 3.0)
        # the card most likely went away with the socket: send it again as soon
        # as the connection is back instead of waiting for the keepalive
        self._pushed_identity = None
        self._pushed_status = None
        self._card_shown = False
        self._last_sent = 0.0
        presence, self.rpc = self.rpc, None
        if presence is not None:
            self._close_async(presence)

    def _lock(self, timeout=None):
        """Never wait on the rpc lock forever - a wedged call could hold it."""
        limit = RPC_LOCK_TIMEOUT if timeout is None else timeout
        if not self._rpc_lock.acquire(timeout=limit):
            self._mark_dead("rpc lock stuck")
            return False
        return True

    def _close_async(self, presence):
        """Closing a wedged socket may block too: never do it on our thread."""
        def closer():
            try:
                presence.close()
            except Exception:
                pass
        threading.Thread(target=closer, name="hp-rpc-close", daemon=True).start()

    def wake_for_new_settings(self):
        """Nothing to push: new templates are rendered by the next keepalive.

        Discord allows 5 activity updates per 20 s, so pressing Save must not
        burn one of them.
        """
        self._wake.set()

    def reset_presence(self):
        """Throw the RPC connection away and force a fresh push on the next tick."""
        with self._rpc_lock:
            old = self.rpc
            self.rpc = None
        self._pushed_identity = None
        self._pushed_status = None
        self._status_candidate = None
        self._next_push_at = 0.0
        self._last_sent = 0.0
        self.last_error = ""
        try:
            self._close_async(old)
        except Exception:
            pass
        thread = getattr(self, "_rpc_thread", None)
        if thread is None or not thread.is_alive():
            # the supervisor died with the old socket: bring it back
            self._start_rpc_thread() if hasattr(self, "_start_rpc_thread") else None
        self._wake.set()

    def connect(self):
        if not self.client_id:
            return False
        try:
            from pypresence import Presence
            # NOTE: never hold the lock while calling pypresence - a dead pipe
            # blocks forever and would keep the lock for the rest of the run.
            old = self.rpc
            self.rpc = None
            if old is not None:
                self._close_async(old)
            presence = Presence(self.client_id)
            presence.connect()
            self.rpc = presence
            return True
        except Exception as error:
            self.last_error = str(error)
            self.rpc = None
            return False

    def _clear(self):
        self._submit(self._do_clear)

    def _disable_job(self):
        """Worker thread: make sure there is a connection, then remove the card."""
        if not self.rpc and not self.connect():
            return
        self._do_clear()

    def _do_clear(self):
        # a dead connection must not silently swallow the clear
        if not self.rpc and not self.connect():
            self.last_error = "rpc: cannot reach Discord to clear the card"
            return
        presence = self.rpc
        if presence is None:
            return
        try:
            presence.clear()
            self._card_shown = False
            # the card is gone, so the next tick has to send it again even if the
            # game and the status did not change (it used to wait for KEEPALIVE,
            # which is why the profile stayed empty for up to 40 s)
            self._pushed_identity = None
            self._pushed_status = None
            self.last_error = ""
        except Exception as error:
            # retried by the next tick while no game is running
            self.last_error = "rpc: clear failed: %s" % error
            self._close_async(presence)
            if self.rpc is presence:
                self.rpc = None

    # ---------------------------------------------------------------- clock
    @staticmethod
    def _folder_of(game):
        return os.path.dirname((game or {}).get("exe") or "").lower()

    def _same_folder_running(self, folder):
        for candidate in self.games:
            exe = candidate.get("exe") or ""
            if exe and self._folder_of(candidate) == folder and self.pids_for_exe(exe):
                return True
        return False

    def _game_by_key(self, key):
        """The game dict that belongs to a session key, if it still exists."""
        if key is None:
            return None
        game = self._session_games.get(key)
        if game is not None:
            return game
        for candidate in self.games:
            if self._game_key(candidate) == key:
                self._session_games[key] = candidate
                return candidate
        return None

    def _session_store(self, key, seconds, missing_since=None):
        """Remember a game's session so switching back continues it."""
        if key is None:
            return
        self._session_memory[key] = [float(seconds or 0.0), missing_since]

    def _session_forget(self, key):
        if key is None:
            return
        self._session_memory.pop(key, None)
        self._session_games.pop(key, None)

    def _expire_sessions(self, now):
        """Drop the sessions of games that stayed closed for SESSION_GRACE.

        A session is only dropped once its process is really gone and has been
        gone for the whole grace window, so a restart inside the window (or a
        launcher handing over to the engine) keeps the same session while a real
        close starts a fresh one.
        """
        for key in list(self._session_memory):
            entry = self._session_memory[key]
            game = self._session_games.get(key)
            if entry[1] is None:
                if game is None:
                    self._session_forget(key)
                    continue
                if self.pids_for_game(game):
                    continue
                entry[1] = now          # it just exited: start the grace window
            if now - entry[1] > SESSION_GRACE:
                debug_log("session dropped: %s after %.1fs closed"
                          % (key[0], now - entry[1]))
                self._session_forget(key)

    def _same_game(self, first, second):
        """True when both entries are the same game (e.g. launcher -> engine)."""
        if not first or not second:
            return False
        title_a = (first.get("original") or first.get("title") or "").strip()
        title_b = (second.get("original") or second.get("title") or "").strip()
        if title_a and title_a == title_b:
            return True
        folder_a = self._folder_of(first)
        folder_b = self._folder_of(second)
        return bool(folder_a) and folder_a == folder_b

    @staticmethod
    # ------------------------------------------------------- idle timer
    @staticmethod
    def _clamp_idle(value):
        """Accept anything, return a sane number of seconds."""
        try:
            seconds = int(float(value))
        except (TypeError, ValueError):
            return IDLE_SECONDS_DEFAULT
        return max(IDLE_SECONDS_MIN, min(IDLE_SECONDS_MAX, seconds))

    def set_idle_seconds(self, value):
        """Apply a new idle timeout; the next tick uses it."""
        seconds = self._clamp_idle(value)
        if seconds == self.idle_seconds:
            return seconds
        self.idle_seconds = seconds
        debug_log("idle threshold now %ss" % seconds)
        # the status may be Idle for a while: push it on the next tick
        self._pushed_status = None
        self.wake_for_new_settings()
        self._notify()
        return seconds

    @staticmethod
    def _game_key(game):
        """Stable identity of a game for session bookkeeping."""
        return (game.get("exe") or "", game.get("vndb_id") or "",
                game.get("title") or game.get("original") or "")

    def _apply_clock(self, game, status, now):
        """Move the session clock to `game`, banking what the last one earned.

        Rules (the behaviour 2.x is supposed to have):
        - switching between two open games never restarts either session, the
          one you leave is remembered and continues when you come back;
        - the time played before the switch is banked into that game's total and
          into stats.db (it used to be dropped, because the previous game was
          looked up by exe string while the session key is a tuple);
        - a closed game keeps its session for SESSION_GRACE seconds only, so a
          restart inside 8 s continues it and a later restart starts at zero;
        - if the previous exe is gone and the new one is the same game (a game
          renaming its own exe, or a launcher handing over to the engine) the
          session simply continues.
        """
        key = self._game_key(game)
        if self._session_key != key:
            previous_key = self._session_key
            previous_game = self._game_by_key(previous_key)
            if self._reading_start is not None:
                # bank the stretch that is still running before switching away
                start = self._reading_start
                segment = max(0.0, now - start)
                self._reading_start = None
                self._session_accumulated += segment
                if previous_game is not None:
                    previous_game["total_seconds"] = \
                        previous_game.get("total_seconds", 0) + segment
                    self._record_segment(previous_game, start, now)
            handover = False
            if previous_key is not None and previous_key != key:
                previous_gone = (previous_game is None
                                 or not self.pids_for_game(previous_game))
                handover = previous_gone and self._same_game(previous_game, game)
            if handover:
                # same game under a new identity: keep the seconds
                seconds = self._session_accumulated
                self._session_forget(previous_key)
                debug_log("session handover: %s -> %s secs=%.1f"
                          % (previous_key[0] if previous_key else "",
                             game.get("exe"), seconds))
            elif previous_key is not None:
                # a different game is starting: remember where the last one was
                still_open = (previous_game is not None
                              and bool(self.pids_for_game(previous_game)))
                self._session_store(previous_key, self._session_accumulated,
                                    None if still_open else now)
                seconds = None
            else:
                seconds = None
            self._session_key = key
            self._session_games[key] = game
            if seconds is None:
                entry = self._session_memory.pop(key, None)
                if entry and (entry[1] is None or now - entry[1] <= SESSION_GRACE):
                    seconds = entry[0]
                else:
                    seconds = 0.0
            self._session_accumulated = seconds
            self._reading_start = None
            self.session_seconds = self._session_accumulated
            self.total_seconds = game.get("total_seconds", 0)
        if status == "Reading":
            if self._reading_start is None:
                self._reading_start = now
            return
        if self._reading_start is None:
            return
        start = self._reading_start
        stop = now
        if status == "Idle":
            # 1.x: the clock stops at the last real input, not at the moment
            # we noticed the user was away, so AFK time never reaches the
            # session, the total or stats.db.
            from .winapi import get_idle_seconds
            stop = max(start, now - float(get_idle_seconds()))
        segment = max(0.0, stop - start)
        self._session_accumulated += segment
        self._reading_start = None
        game["total_seconds"] = game.get("total_seconds", 0) + segment
        # the true interval, so a long AFK stretch is not shifted into the
        # next day of stats.db
        self._record_segment(game, start, stop)

    # ------------------------------------------------------- stats writing
    def _record_segment(self, game, start, end):
        """Accumulate short stretches so nothing under 5 s is lost."""
        length = max(0.0, end - start)
        if length <= 0 or self.stats is None:
            return
        if self._stat_buffer and self._stat_buffer_game is not game:
            self._write_buffer(end)
        self._stat_buffer_game = game
        self._stat_buffer += length
        if self._stat_buffer >= 5:
            self._write_buffer(end)

    def _write_buffer(self, end):
        if not self._stat_buffer or self._stat_buffer_game is None:
            return
        length = self._stat_buffer
        game = self._stat_buffer_game
        self._stat_buffer = 0.0
        try:
            self.stats.add(game.get("vndb_id", ""),
                           game.get("original") or game.get("title") or "",
                           Path(game.get("exe", "")).name,
                           end - length, end, length, min_seconds=0)
        except Exception as error:
            debug_log("stats write failed: %s" % error)

    # ------------------------------------------------------------- routes
    # A route is a named bucket of playtime inside one game, and the time in it
    # is typed by hand: the app never guesses where a chapter ends. Nothing here
    # touches the session clock, the Discord card or stats.db.
    def _routes(self, game):
        """The game's route list, created on first use."""
        routes = game.get("routes")
        if not isinstance(routes, list):
            routes = []
            game["routes"] = routes
        return routes

    def _route_entry(self, game, name, create=False):
        for entry in self._routes(game):
            if (entry.get("name") or "") == name:
                return entry
        if not create:
            return None
        entry = {"name": name, "seconds": 0.0}
        self._routes(game).append(entry)
        return entry

    def save_games_now(self):
        """Persist games.json through the hook MainWindow installs."""
        if not self.on_save:
            return
        try:
            self.on_save()
        except Exception as error:
            debug_log("games save failed: %s" % error)

    def routes(self, game):
        """The game's routes as plain dicts, for the tables in the UI.

        Every entry carries the time spent in that route ("seconds") and the
        playtime reached when the route ends ("acc"). Old games.json files only
        know "seconds", so the running total is rebuilt from them on the fly.
        """
        if not game:
            return []
        rows = []
        acc = 0.0
        for entry in self._routes(game):
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            seconds = max(0.0, float(entry.get("seconds") or 0.0))
            stored = entry.get("acc_seconds")
            acc = max(acc, float(stored)) if stored is not None else acc + seconds
            rows.append({"name": name, "seconds": seconds, "acc": acc})
        return rows

    def route_names(self, game):
        return [entry["name"] for entry in self.routes(game)]

    def route_seconds(self, game, name):
        if not game or not name:
            return 0.0
        entry = self._route_entry(game, name)
        return float((entry or {}).get("seconds") or 0.0)

    def route_total(self, game):
        rows = self.routes(game)
        return rows[-1]["acc"] if rows else 0.0

    def add_route(self, game, name, seconds=0.0, acc=None):
        name = (name or "").strip()
        if not game or not name or self._route_entry(game, name) is not None:
            return False
        rows = self.routes(game)
        seconds = max(0.0, float(seconds or 0.0))
        if acc is None:
            acc = (rows[-1]["acc"] if rows else 0.0) + seconds
        entry = self._route_entry(game, name, create=True)
        entry["seconds"] = seconds
        entry["acc_seconds"] = max(0.0, float(acc))
        self.save_games_now()
        return True

    def rename_route(self, game, old, new, seconds=None, acc=None):
        """Rename a route and set its times in one step (Edit uses both)."""
        old, new = (old or "").strip(), (new or "").strip()
        if not game or not old or not new:
            return False
        entry = self._route_entry(game, old)
        if entry is None:
            return False
        if new != old and self._route_entry(game, new) is not None:
            return False
        entry["name"] = new
        if seconds is not None:
            entry["seconds"] = max(0.0, float(seconds))
        if acc is not None:
            entry["acc_seconds"] = max(0.0, float(acc))
        self.save_games_now()
        return True

    def set_all_routes(self, game, rows):
        """Rewrite the whole route list, in display order.

        rows is [(name, seconds, acc)]. The editor hands its rows over after
        every edit, so the running total stays consistent even when a route in
        the middle changes.
        """
        if not game:
            return False
        entries = self._routes(game)
        by_name = {(entry.get("name") or ""): entry for entry in entries}
        wanted = []
        for name, seconds, acc in rows:
            name = (name or "").strip()
            if not name:
                continue
            if any(other["name"] == name for other in wanted):
                return False
            entry = by_name.get(name)
            if entry is None:
                entry = {"name": name}
                by_name[name] = entry
            entry["name"] = name
            entry["seconds"] = max(0.0, float(seconds or 0.0))
            entry["acc_seconds"] = max(0.0, float(acc or 0.0))
            wanted.append(entry)
        entries[:] = wanted
        self.save_games_now()
        return True

    def remove_route(self, game, name):
        name = (name or "").strip()
        if not game or not name:
            return False
        routes = self._routes(game)
        for index, entry in enumerate(routes):
            if (entry.get("name") or "") == name:
                del routes[index]
                self.save_games_now()
                return True
        return False

    # ----------------------------------------------------------------- tick
    def tick(self):
        """Re-entrancy guard: the focus hook and the UI timer share this."""
        if self._tick_busy:
            return
        self._tick_busy = True
        try:
            self._tick_once()
        finally:
            self._tick_busy = False

    def ensure_presence(self):
        """Reconnect and republish when the card went stale - never on the UI thread."""
        if not self.presence_enabled or self.game is None or self.status is None:
            return False
        if time.time() - self._last_sent < KEEPALIVE + 15 or self._watchdog_busy:
            return False
        self._watchdog_busy = True
        self._submit(self._watchdog_job)
        return True

    def _watchdog_job(self):
        """Republish without dropping a healthy connection.

        This used to close the socket first, so the card disappeared and came
        back every time the watchdog ran (~30 s) - the "disconnect" the user saw.
        """
        try:
            debug_log("watchdog: last_sent %.0fs ago, rpc=%s"
                      % (time.time() - self._last_sent,
                         "open" if self.rpc else "closed"))
            if self.rpc is None:
                self._last_sent = 0.0
            if self.game is not None and self.status is not None:
                self._push(self.game, self.status)
        finally:
            self._watchdog_busy = False

    def _tick_once(self):
        try:
            self._expire_sessions(time.time())
            game, pids = self.scan()
            if not game or not pids or not self._pids_alive(pids):
                if self.game is not None:
                    now = time.time()
                    if self._missing_since is None:
                        self._missing_since = now
                    if now - self._missing_since < MISSING_GRACE:
                        # a single snapshot without the game proves nothing: a
                        # game that swapped its exe is back within a few hundred
                        # milliseconds, and clearing here wiped the card
                        debug_log("game missing for %.1fs, waiting for %.1fs"
                                  % (now - self._missing_since, MISSING_GRACE))
                        return
                    folder = self._folder_of(self.game)
                    title = (self.game.get("original")
                             or self.game.get("title") or "").strip()
                    self._flush()
                    # the session survives SESSION_GRACE seconds, so a game that
                    # restarts itself (or swaps its exe) continues where it was
                    self._session_store(self._session_key,
                                        self._session_accumulated, time.time())
                    self._session_key = None
                    self._session_accumulated = 0.0
                    self._reading_start = None
                    self.session_seconds = 0.0
                    self.game = None
                    self.status = None
                    self.preview = {}
                    self._clear()
                    self._notify()
                elif self._card_shown and self.presence_enabled:
                    # the transition was missed (or the clear failed): keep asking
                    self._clear()
                return
            if self.pinned_exe:
                pinned = next((g for g in self.games
                               if g.get("exe") == self.pinned_exe), None)
                pinned_pids = self.pids_for_exe(self.pinned_exe)
                if pinned is not None and pinned_pids:
                    game, pids = pinned, pinned_pids
                else:
                    self.pinned_exe = None
            else:
                focused = self._focused_library_game()
                if focused is not None and focused is not game:
                    focused_pids = self.pids_for_exe(focused.get("exe"))
                    if focused_pids:
                        game, pids = focused, focused_pids
                elif focused is None and self.game is not None:
                    # the foreground belongs to no game (browser, Discord, ...):
                    # keep tracking the game we already have instead of falling
                    # back to whatever scan() scores highest
                    current_pids = self.pids_for_game(self.game)
                    if current_pids:
                        game, pids = self.game, current_pids
            status = self._status_for(game, pids)
            self._ensure_metadata(game)
            now = time.time()
            self._missing_since = None      # the game is back, cancel the wait
            self._apply_clock(game, status, now)
            self._arm_exit_watch(game, pids)
            current = (now - self._reading_start) if self._reading_start else 0.0
            self.session_seconds = self._session_accumulated + current
            self.total_seconds = game.get("total_seconds", 0) + current
            self.game = game
            identity = (game.get("exe"), game.get("vndb_id"))
            # A status change has to survive a moment before it reaches Discord:
            # focus flapping used to push Reading/Paused/Reading in a second and
            # burn the whole 5-per-20s budget.
            candidate = getattr(self, "_status_candidate", None)
            if candidate is None or candidate[0] != status:
                candidate = (status, now)
                self._status_candidate = candidate
            first_push = self._pushed_identity is None and self._pushed_status is None
            stable = (now - candidate[1]) >= STATUS_DEBOUNCE
            identity_changed = identity != self._pushed_identity
            status_changed = status != self._pushed_status
            if status != self.status:
                debug_log("status %s -> %s (candidate, push in %.1fs)"
                          % (self.status, status,
                             max(0.0, STATUS_DEBOUNCE - (now - candidate[1]))))
            self.status = status
            self.preview = self._build_preview(game, status)
            now_i = int(now)
            if now_i - getattr(self, "_clock_log_at", 0) >= 5:
                self._clock_log_at = now_i
                try:
                    debug_log("clock st=%s sess=%.0f acc=%.0f reading_start=%s "
                              "key=%s pushed_st=%s"
                              % (status, float(self.session_seconds or 0),
                                 float(self._session_accumulated or 0),
                                 "yes" if self._reading_start else "no",
                                 (self._session_key or ("",))[0],
                                 self._pushed_status))
                except Exception:
                    pass
            if status_changed and not (stable or first_push):
                debug_log("status %s waiting: %.1fs of %.1fs settled"
                          % (status, now - candidate[1], STATUS_DEBOUNCE))
            should_push = (identity_changed
                           or not self._card_shown
                           or (status_changed and (stable or first_push))
                           or now - self._last_sent >= KEEPALIVE)
            if should_push and not (status_changed and not (stable or first_push)):
                if self.presence_enabled:
                    sent = self._push(game, status)
                    if sent:
                        debug_log("status %s pushed after %.1fs"
                                  % (status, now - candidate[1]))
                    if sent:
                        self._pushed_identity = identity
                        self._pushed_status = status
                    else:
                        # nothing reached Discord: try again on the next tick
                        self._pushed_status = None
            self._notify()
        except Exception as error:
            self.last_error = "tick: %s" % error
            debug_log(self.last_error)

    def _flush(self):
        game = self.game
        if game and self._reading_start is not None:
            now = time.time()
            segment = max(0.0, now - self._reading_start)
            start = self._reading_start
            self._reading_start = None
            self._session_accumulated += segment
            game["total_seconds"] = game.get("total_seconds", 0) + segment
            self._record_segment(game, start, now)
            self._write_buffer(now)

    def _var_map(self, game, status):
        """Every {token} a template or a hover text may use."""
        opts = self.opts or {}
        # VNDB leaves the Bayesian number empty until a title has enough votes;
        # show the raw average instead of "N/A" for the weighted slot then.
        average_text = _rating_text(game.get("rating_average"))
        weighted_text = _rating_text(game.get("rating_weighted"))
        if weighted_text == "N/A" and average_text != "N/A":
            weighted_text = average_text
        return {
            "title": game.get("original") or game.get("title") or "",
            "romanized_title": game.get("romanized") or game.get("title") or "",
            "developer": game.get("developer") or "Unknown",
            "year": game.get("year") or "????",
            "status": status,
            "session_time": format_time(self.session_seconds,
                                        opts.get("session_time_format") or SMART_TIME_FORMAT),
            "total_time": format_time(self.total_seconds,
                                      opts.get("total_time_format") or SMART_TIME_FORMAT),
            "rating_average": average_text,
            "rating_weighted": weighted_text,
            "vndb": game.get("vndb_id") or "",
        }

    def _build_preview(self, game, status):
        mapping = self._var_map(game, status)
        opts = self.opts or {}
        template = self.templates.get(status) or DEFAULT_TEMPLATES.get(status) or {}
        def render(text):
            return _subst(text, mapping)
        details = render(template.get("details") or "") \
            if template.get("details_enabled", True) else ""
        state = render(template.get("state") or "") \
            if template.get("state_enabled", True) else ""
        custom_large = (opts.get("custom_large_image") or "")
        use_custom_large = (opts.get("large_image_mode") == "custom"
                            and custom_large)
        small = (opts.get("custom_small_image") or ""
                 if opts.get("small_image_mode") == "custom" else "")
        return {
            "title": _clip(render(template.get("name") or "{title}"), 128),
            "details": _clip(details, 128),
            "state": _clip(state, 128),
            "status": status,
            "start": int(time.time() - self.session_seconds) if status == "Reading" else None,
            "image": custom_large if use_custom_large else game.get("image") or "",
            "large_image": custom_large if use_custom_large else "",
            "small_image": small,
            "large_text": _clip(render(opts.get("large_text") or ""), 128),
            "small_text": _clip(render(opts.get("small_text") or ""), 128),
            "vars": mapping,
            "vndb_id": game.get("vndb_id") or "",
        }

    def _push(self, game, status):
        """Compose the payload here (cheap) and send it on the worker thread."""
        preview = self.preview
        now = time.time()
        if not preview or now < self._next_push_at:
            return False
        if self._last_sent and now - self._last_sent < MIN_PUSH_INTERVAL:
            debug_log("push throttled: %.2fs since the last send"
                      % (now - self._last_sent))
            return False
        if now - getattr(self, "_last_push_begin", 0.0) < 0.3:
            return False
        sent_times = [stamp for stamp in getattr(self, "_sent_log", [])
                      if now - stamp < PUSH_WINDOW]
        self._sent_log = sent_times
        if len(sent_times) >= PUSH_BURST:
            debug_log("push throttled: %d updates in the last %.0fs"
                      % (len(sent_times), PUSH_WINDOW))
            return False
        self._last_push_begin = now
        try:
            kwargs = {
                "name": _clip(preview["title"], 128),
                "details": _clip(preview["details"], 128) or None,
                "state": _clip(preview["state"], 128) or None,
            }
            opts = self.opts or {}
            mapping = preview.get("vars") or self._var_map(game, status)
            mode = opts.get("large_image_mode", "vndb")
            if mode == "custom" and opts.get("custom_large_image"):
                kwargs["large_image"] = opts["custom_large_image"]
            elif game.get("image"):
                kwargs["large_image"] = game["image"]
            large_text = _clip(_subst(opts.get("large_text") or "", mapping), 128)
            if large_text:
                kwargs["large_text"] = large_text
            if opts.get("small_image_mode") == "custom" and opts.get("custom_small_image"):
                kwargs["small_image"] = opts["custom_small_image"]
            small_text = _clip(_subst(opts.get("small_text") or "", mapping), 128)
            if small_text:
                kwargs["small_text"] = small_text
            if opts.get("button_enabled", True) and game.get("vndb_id"):
                label = _subst(opts.get("button_label") or "View on VNDB", mapping)
                url = _subst(opts.get("button_url") or "https://vndb.org/{vndb}",
                             mapping)
                if url.startswith(("http://", "https://")):
                    kwargs["buttons"] = [{"label": _clip(label, 32), "url": url}]
            if preview.get("start") and opts.get("show_timer", True):
                kwargs["start"] = preview["start"]
            kwargs = {k: v for k, v in kwargs.items() if v is not None}
            self._sent_log = getattr(self, "_sent_log", [])
            self._sent_log.append(now)
            self._push_token += 1
            self._submit(self._do_push, kwargs, game.get("image"), self._push_token)
            return True
        except Exception as error:
            self.last_error = "compose: %s" % error
            return False

    def _do_push(self, kwargs, cover, token=None):
        started_at = time.time()
        debug_log("push start state=%s" % kwargs.get("state"))
        try:
            return self._do_push_inner(kwargs, cover, token, started_at)
        finally:
            debug_log("push done in %.0f ms" % ((time.time() - started_at) * 1000.0))

    def _do_push_inner(self, kwargs, cover, token, started_at):
        debug_log("connecting: rpc=%s" % ("open" if self.rpc else "closed"))
        """Worker thread: connect if needed, send, fall back, close on failure."""
        if self.rpc is not None and not self._rpc_alive():
            debug_log("rpc socket is closed, reconnecting")
            dead, self.rpc = self.rpc, None
            self._close_async(dead)
        if not self.rpc and not self.connect():
            return
        presence = self.rpc
        if presence is None:
            return
        if token is not None and token < self._push_token:
            return                  # a newer state is already queued
        try:
            try:
                presence.update(**kwargs)
            except Exception:
                # a bad custom large image is the usual suspect: fall back to
                # the VNDB cover and try once more
                if cover and kwargs.get("large_image") != cover:
                    kwargs = dict(kwargs, large_image=cover)
                    presence.update(**kwargs)
                    debug_log("large image fell back to the VNDB cover")
                else:
                    raise
            self._last_sent = time.time()
            self._card_shown = True
            self._next_push_at = 0.0
            self._retry_count = 0
        except Exception as error:
            self.last_error = "rpc: %s" % error
            debug_log("update failed: %s" % error)
            self._next_push_at = time.time() + MIN_PUSH_INTERVAL
            self._pushed_status = None
            self._close_async(presence)
            if self.rpc is presence:
                self.rpc = None

    def set_presence_enabled(self, enabled):
        self.presence_enabled = bool(enabled)
        if not self.presence_enabled:
            self._submit(self._disable_job)
            self.status = None
        else:
            self._last_sent = 0.0
        self._notify()

    def flush_open_segment(self):
        """Write the Running segment to stats.db without stopping the clock."""
        if self._reading_start is None or not self.game:
            return
        now = time.time()
        start = self._reading_start
        segment = max(0.0, now - start)
        self._reading_start = now
        self._session_accumulated += segment
        self._record_segment(self.game, start, now)

    # ------------------------------------------------------- exit waiters
    def _arm_exit_watch(self, game, pids):
        key = game.get("exe", "")
        pids = set(pids or ())
        if not key or not pids:
            return
        entry = self._exit_watch.get(key)
        if entry and entry.get("pids") == pids:
            return
        if entry is not None:
            try:
                entry["thread"].cancel()
            except Exception:
                pass
        # NOTE: watchers of other games stay armed - a game can be closed while a
        # different game is being tracked, and that must still clear its session.
        thread = wait_for_process_exit(min(pids), lambda: self._on_exit(key, pids))
        if thread:
            self._exit_watch[key] = {"pids": pids, "thread": thread}

    def _disarm_exit_watch(self):
        for entry in self._exit_watch.values():
            try:
                entry["thread"].cancel()
            except Exception:
                pass
        self._exit_watch.clear()

    def _on_exit(self, key, pids):
        self._exit_watch.pop(key, None)
        for pid in pids:
            try:
                import psutil
                if psutil.pid_exists(pid):
                    return
            except Exception:
                continue
        self._scan_cache_game = None
        self._scan_cache_time = 0.0
        tracked = bool(self.game) and (self.game.get("exe") or "") == key
        if not tracked:
            # A game that is not on the profile closed: either one you switched
            # away from, or the old exe of a handover (a game renaming itself).
            # The card belongs to another game, so clearing it here made the
            # status vanish while you were playing something else.
            debug_log("exit watch: %s is not the tracked game (%s), card kept"
                      % (key, (self.game or {}).get("exe")))
            self._expire_sessions(time.time())
            self._notify()
            return
        # Another game may still be running: the next tick switches the card
        # straight over to it, so blanking the profile here would make Discord
        # show "nothing" for a moment before the other game appears.
        try:
            others = [g for g in self.running_games()
                      if (g.get("exe") or "") != key]
        except Exception:
            others = []
        if others:
            debug_log("exit watch: %s closed, %d other game(s) still running: "
                      "switching without clearing" % (key, len(others)))
            self._flush()
            self._expire_sessions(time.time())
            self._notify()
            return
        # Do not blank the card yet: a game that hands its window over to an
        # engine exe (sayagatari_chs.exe -> SiglusEngine.exe) closes the old
        # process and opens the new one a moment later, and clearing here made
        # Discord drop and re-add the card in the same second. The tick below
        # still clears once the game stayed away for MISSING_GRACE.
        if self._missing_since is None:
            self._missing_since = time.time()
        debug_log("exit watch: %s closed, card kept for %.1fs in case of a "
                  "handover" % (key, MISSING_GRACE))
        self._notify()

    def _notify(self):
        if self.on_change:
            try:
                self.on_change(self)
            except Exception:
                pass

    # ------------------------------------------------------- focus hook
    def start_focus_hook(self, on_focus):
        """WinEvent foreground hook (same idea as 1.0.4): status flips in ~2 ms."""
        self._hook_stop = threading.Event()
        self._hook_show = None
        self._hook_on_focus = on_focus

        def hook_thread():
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            ole32 = ctypes.windll.ole32
            try:
                ole32.CoInitialize(0)
            except Exception:
                pass
            EVENT_SYSTEM_FOREGROUND = 0x0003
            EVENT_OBJECT_SHOW = 0x8002
            WINEVENT_OUTOFCONTEXT = 0x0000
            WINEVENT_SKIPOWNPROCESS = 0x0002
            PM_REMOVE = 1
            QS_ALLINPUT = 0x04FF

            def timer_proc(hWinEventHook, event, hwnd, idObject, idChild,
                           dwEventThread, dwmsEventTime):
                # EVENT_OBJECT_SHOW fires for every child control too; only a
                # top level window (idObject 0, no child id) means a game may
                # have just started, and a tooltip must not wake the engine.
                if event == EVENT_OBJECT_SHOW:
                    if idObject != 0 or idChild != 0:
                        return
                try:
                    # the window handle lets the idle path check "is this a
                    # game window?" instead of guessing from the foreground
                    self._hook_on_focus(hwnd if event == EVENT_OBJECT_SHOW else None)
                except TypeError:
                    try:
                        self._hook_on_focus()
                    except Exception:
                        pass
                except Exception:
                    pass

            proc_type = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD,
                                           wintypes.HWND, wintypes.LONG, wintypes.LONG,
                                           wintypes.DWORD, wintypes.DWORD)
            callback = proc_type(timer_proc)
            self._hook_callback = callback        # keep alive
            flags = WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS
            hook = user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
                                          0, callback, 0, 0, flags)
            # A game that starts in the background (windowed launcher, another
            # monitor) never takes the foreground, so also listen for windows
            # appearing: this is what lets the idle tick go from 1 s to 10 s.
            self._hook_show = user32.SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW,
                                                     0, callback, 0, 0, flags)
            if not hook and not self._hook_show:
                return
            try:
                user32.MsgWaitForMultipleObjectsEx.restype = wintypes.DWORD
                user32.MsgWaitForMultipleObjectsEx.argtypes = [
                    wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                    wintypes.DWORD, wintypes.DWORD]
            except Exception:
                pass
            message = wintypes.MSG()
            while not self._hook_stop.is_set():
                user32.MsgWaitForMultipleObjectsEx(0, None, 250, QS_ALLINPUT, 0)
                while user32.PeekMessageW(ctypes.byref(message), 0, 0, 0, PM_REMOVE):
                    user32.TranslateMessage(ctypes.byref(message))
                    user32.DispatchMessageW(ctypes.byref(message))
                    if self._hook_stop.is_set():
                        break
            try:
                user32.UnhookWinEvent(hook)
            except Exception:
                pass
            try:
                user32.UnhookWinEvent(self._hook_show)
            except Exception:
                pass
            try:
                ole32.CoUninitialize()
            except Exception:
                pass

        self._hook_thread = threading.Thread(target=hook_thread, daemon=True,
                                             name="focus-hook")
        self._hook_thread.start()

    def stop_focus_hook(self):
        stop = getattr(self, "_hook_stop", None)
        if stop:
            stop.set()
        self._hook_thread = None

    def close(self):
        try:
            self._rpc_stop.set()
        except Exception:
            pass
        self.stop_focus_hook()
        self._disarm_exit_watch()
        self._clear()
        with self._rpc_lock:
            if self.rpc:
                try:
                    self.rpc.close()
                except Exception:
                    pass
            self.rpc = None
