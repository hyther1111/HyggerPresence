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
from .winapi import wait_for_process_exit

MAX_LINE = 128
RPC_CALL_TIMEOUT = 10.0      # a single Discord call may not take longer
RPC_LOCK_TIMEOUT = 5.0       # nor may waiting for the rpc lock
KEEPALIVE = 55.0             # 1.0.3 pushed every 55 s; Discord allows 5 per 20 s
STATUS_DEBOUNCE = 0.5        # a new status must hold this long before it is pushed


def _clip(value, limit=MAX_LINE):
    """Discord rejects name / details / state longer than 128 characters."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"

POLL_INTERVAL = 1.0
SCAN_INTERVAL = 3.0          # 1.0.3 used 3 s; the tick itself is ~0.04 ms
IDLE_THRESHOLD = 60

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
                 presence=None):
        self.games = []
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
        self._session_memory = {}      # exe -> seconds kept while still open
        self._grace = None             # (deadline, folder, seconds)
        self._session_exe = None
        self._card_shown = False       # True while a card is on the profile
        self._last_sent = 0.0
        self._exit_watch = {}

    # ---------------------------------------------------------------- detection
    def scan(self, force=False):
        now = time.time()
        # while nothing is tracked, look again on every tick: this is what makes a
        # freshly launched game show up immediately instead of up to 3 s later
        if self._scan_cache_game is None:
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
            "rating_average": info.get("rating_average") or "N/A",
            "rating_weighted": info.get("rating_weighted") or "N/A",
        })
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
        """Running pids that belong to this library entry."""
        if not game:
            return set()
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
        """[(game, running exe name)] for every library entry running right now."""
        import psutil
        by_pid = {}
        for process in psutil.process_iter(["pid", "name"]):
            try:
                by_pid[process.info["pid"]] = process.info.get("name") or ""
            except Exception:
                continue
        alive = []
        for game in self.games:
            names = self._names_of(game)
            folder = Path(game.get("exe", "")).parent if game.get("exe") else None
            hit = ""
            for process in psutil.process_iter(["pid", "name"]):
                try:
                    name = process.info.get("name") or ""
                    try:
                        path = process.exe()
                    except Exception:
                        path = None
                    if self.process_matches(game, name, path):
                        if (name or "").lower() in names:
                            hit = name
                            break
                        hit = hit or name
                except Exception:
                    continue
            if hit:
                alive.append((game, hit))
        return alive

    def set_pin(self, exe_path):
        self.pinned_exe = exe_path or None

    def _focused_library_game(self):
        """The library game that owns the foreground window, if any."""
        try:
            from .winapi import get_foreground_pid
            import psutil
            pid = get_foreground_pid()
            if not pid:
                return None
            name = (psutil.Process(pid).name() or "").lower()
        except Exception:
            return None
        if not name:
            return None
        try:
            path = psutil.Process(pid).exe()
        except Exception:
            path = None
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
        if get_idle_seconds() >= IDLE_THRESHOLD:
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
        """Run the Discord call to completion on this thread (1.0.3 behaviour).

        The old version started a helper thread and gave up after 10 s; the
        abandoned call kept holding the IPC pipe, so every later call timed out
        and only a restart helped. Blocking here cannot freeze the UI: the UI
        thread never calls this.
        """
        started = time.time()
        try:
            func(*args)
        finally:
            elapsed = time.time() - started
            if elapsed > 1.0:
                debug_log("rpc %s took %.1fs"
                          % (getattr(func, "__name__", "call"), elapsed))

    def _mark_dead(self, error):
        """Drop the connection so the next action reconnects from scratch."""
        self.last_error = "rpc: %s" % error
        lowered = str(error).lower()
        self._next_push_at = time.time() + (60.0 if "rate" in lowered else 3.0)
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

    def _grace_resume(self, game):
        grace = getattr(self, "_grace", None)
        if not grace:
            return False
        started, folder, title, accumulated = grace[:4]
        gone_exe = grace[4] if len(grace) > 4 else None
        now = time.time()
        same_exe = bool(gone_exe) and game.get("exe") == gone_exe
        # a game often blinks for a second (its own restart); a real close leaves
        # the exe away for much longer
        window = 8.0 if same_exe else 15.0
        if now - started > window:
            debug_log("grace expired: after %.1fs (same_exe=%s)"
                      % (now - started, same_exe))
            self._grace = None
            return False
        same_folder = bool(folder) and self._folder_of(game) == folder
        title_now = (game.get("original") or game.get("title") or "").strip()
        same_title = bool(title) and bool(title_now) and title == title_now
        if not (same_folder or same_title):
            debug_log("grace dropped: new=%s folder=%s title=%s held=%s/%s"
                      % (game.get("exe"), self._folder_of(game),
                         (game.get("original") or game.get("title")),
                         folder, title))
            return False
        self._session_accumulated = max(self._session_accumulated, accumulated)
        debug_log("session resumed: exe=%s secs=%.1f held=%s/%s"
                  % (game.get("exe"), self._session_accumulated, folder, title))
        self._grace = None
        return True

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

    def _apply_clock(self, game, status, now):
        """1.0.4 behaviour: session belongs to the current game, nothing remembered."""
        if self._session_exe != game.get("exe"):
            previous = self._session_exe
            if self._reading_start is not None:
                # bank the stretch that is still running before switching away
                start = self._reading_start
                segment = max(0.0, now - start)
                self._reading_start = None
                self._session_accumulated += segment
                previous_game = next((g for g in self.games
                                      if g.get("exe") == previous), None)
                if previous_game is not None:
                    previous_game["total_seconds"] = \
                        previous_game.get("total_seconds", 0) + segment
                    self._record_segment(previous_game, start, now)
            exe = game.get("exe")
            previous_game = next((g for g in self.games
                                  if g.get("exe") == previous), None)
            handover = self._same_game(previous_game, game) or self._grace_resume(game)
            if handover:
                # the game swapped its own executable: the session continues
                self._session_memory.pop(previous, None)
                self._grace = None
                self._session_exe = exe
                self._reading_start = None
                self.session_seconds = self._session_accumulated
                self.total_seconds = game.get("total_seconds", 0)
            else:
                if previous is not None:
                    still_open = bool(self.pids_for_game(previous_game)) \
                        if previous_game else False
                    if still_open:
                        self._session_memory[previous] = self._session_accumulated
                    else:
                        self._session_memory.pop(previous, None)
                self._session_exe = exe
                self._session_accumulated = self._session_memory.pop(exe, 0.0)
            self._reading_start = None
            self.session_seconds = self._session_accumulated
            self.total_seconds = game.get("total_seconds", 0)
        if status == "Reading":
            if self._reading_start is None:
                self._reading_start = now
            return
        if self._reading_start is None:
            return
        segment = max(0.0, now - self._reading_start)
        if status == "Idle":
            # 1.x: stop at the last real input, not at the moment we noticed
            from .winapi import get_idle_seconds
            segment = max(0.0, (now - get_idle_seconds()) - self._reading_start)
        start = self._reading_start
        self._session_accumulated += segment
        self._reading_start = None
        game["total_seconds"] = game.get("total_seconds", 0) + segment
        # only the counted part: the idle stretch must not reach stats.db
        self._record_segment(game, now - segment, now)

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
        if time.time() - self._last_sent < 30 or self._watchdog_busy:
            return False
        self._watchdog_busy = True
        self._submit(self._watchdog_job)
        return True

    def _watchdog_job(self):
        try:
            with self._rpc_lock:
                if self.rpc is not None:
                    try:
                        self.rpc.close()
                    except Exception:
                        pass
                self.rpc = None
            self._last_sent = 0.0
            if self.game is not None and self.status is not None:
                self._push(self.game, self.status)
        finally:
            self._watchdog_busy = False

    def _tick_once(self):
        try:
            game, pids = self.scan()
            if not game or not pids or not self._pids_alive(pids):
                if self.game is not None:
                    folder = self._folder_of(self.game)
                    title = (self.game.get("original")
                             or self.game.get("title") or "").strip()
                    self._flush()
                    # keep the seconds for a moment: the game may swap its own exe
                    # (launcher -> engine) with a gap of a second or two, and that
                    # must not restart the session
                    if self._session_accumulated > 0:
                        self._grace = (time.time(), folder, title,
                                       self._session_accumulated,
                                       self._session_exe)
                        debug_log("session held: exe=%s folder=%s title=%s secs=%.1f"
                                  % (self._session_exe, folder, title,
                                     self._session_accumulated))
                    else:
                        self._grace = None
                    # closing the game resets its session (switching does not)
                    if self._session_exe is not None:
                        self._session_memory.pop(self._session_exe, None)
                    self._session_exe = None
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
                debug_log("status %s -> %s (candidate)" % (self.status, status))
            self.status = status
            self.preview = self._build_preview(game, status)
            should_push = (identity_changed
                           or (status_changed and (stable or first_push))
                           or now - self._last_sent >= KEEPALIVE)
            if should_push and not (status_changed and not (stable or first_push)):
                if self.presence_enabled:
                    debug_log("status %s accepted after %.1fs" % (status, now - candidate[1]))
                    self._push(game, status)
                    self._pushed_identity = identity
                    self._pushed_status = status
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

    def _build_preview(self, game, status):
        mapping = {
            "title": game.get("original") or game.get("title") or "",
            "romanized_title": game.get("romanized") or game.get("title") or "",
            "developer": game.get("developer") or "Unknown",
            "year": game.get("year") or "????",
            "status": status,
            "session_time": format_time(self.session_seconds,
                                        self.opts.get("session_time_format") or SMART_TIME_FORMAT),
            "total_time": format_time(self.total_seconds,
                                      self.opts.get("total_time_format") or SMART_TIME_FORMAT),
            "rating_average": game.get("rating_average") or "N/A",
            "rating_weighted": game.get("rating_weighted") or "N/A",
            "vndb": game.get("vndb_id") or "",
        }
        template = self.templates.get(status) or DEFAULT_TEMPLATES.get(status) or {}
        def render(text):
            for key, value in mapping.items():
                text = text.replace("{%s}" % key, str(value))
            return _clip(text, 128)
        details = render(template.get("details") or "") \
            if template.get("details_enabled", True) else ""
        state = render(template.get("state") or "") \
            if template.get("state_enabled", True) else ""
        return {
            "title": _clip(render(template.get("name") or "{title}"), 128),
            "details": _clip(details, 128),
            "state": _clip(state, 128),
            "status": status,
            "start": int(time.time() - self.session_seconds) if status == "Reading" else None,
            "image": (self.opts.get("custom_large_image")
                      if (self.opts.get("large_image_mode") == "custom"
                          and self.opts.get("custom_large_image"))
                      else game.get("image") or ""),
            "vndb_id": game.get("vndb_id") or "",
        }

    def _push(self, game, status):
        """Compose the payload here (cheap) and send it on the worker thread."""
        preview = self.preview
        if not preview or time.time() < self._next_push_at:
            return
        try:
            kwargs = {
                "name": _clip(preview["title"], 128),
                "details": _clip(preview["details"], 128) or None,
                "state": _clip(preview["state"], 128) or None,
            }
            opts = self.opts or {}
            mode = opts.get("large_image_mode", "vndb")
            if mode == "custom" and opts.get("custom_large_image"):
                kwargs["large_image"] = opts["custom_large_image"]
            elif game.get("image"):
                kwargs["large_image"] = game["image"]
            large_text = _clip((opts.get("large_text") or "").replace(
                "{title}", preview["title"]), 128)
            if large_text:
                kwargs["large_text"] = large_text
            if opts.get("small_image_mode") == "custom" and opts.get("custom_small_image"):
                kwargs["small_image"] = opts["custom_small_image"]
            if opts.get("small_text"):
                kwargs["small_text"] = _clip(opts["small_text"], 128)
            if opts.get("button_enabled", True) and game.get("vndb_id"):
                label = (opts.get("button_label") or "View on VNDB").replace(
                    "{vndb}", game["vndb_id"])
                url = (opts.get("button_url") or "https://vndb.org/{vndb}").replace(
                    "{vndb}", game["vndb_id"])
                if url.startswith(("http://", "https://")):
                    kwargs["buttons"] = [{"label": label[:32], "url": url}]
            if preview.get("start") and opts.get("show_timer", True):
                kwargs["start"] = preview["start"]
            kwargs = {k: v for k, v in kwargs.items() if v is not None}
            self._push_token += 1
            self._submit(self._do_push, kwargs, game.get("image"), self._push_token)
        except Exception as error:
            self.last_error = "compose: %s" % error

    def _do_push(self, kwargs, cover, token=None):
        started_at = time.time()
        debug_log("push start state=%s" % kwargs.get("state"))
        try:
            return self._do_push_inner(kwargs, cover, token, started_at)
        finally:
            debug_log("push done in %.0f ms" % ((time.time() - started_at) * 1000.0))

    def _do_push_inner(self, kwargs, cover, token, started_at):
        """Worker thread: connect if needed, send, fall back, close on failure."""
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
            # Discord rate limits activity updates: wait before trying again
            lowered = str(error).lower()
            self._next_push_at = time.time() + (60.0 if "rate" in lowered else 3.0)
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
        self._clear()
        self._scan_cache_game = None
        self._scan_cache_time = 0.0
        self._session_memory.pop(key, None)
        if self.game and self.game.get("exe") == key:
            folder = self._folder_of(self.game)
            title = (self.game.get("original")
                     or self.game.get("title") or "").strip()
            self._flush()
            # the game may be handing over to another exe of its own (launcher ->
            # engine): keep the seconds for a moment so the session can continue
            if self._session_accumulated > 0:
                self._grace = (time.time(), folder, title,
                               self._session_accumulated, key)
                debug_log("session held (exit watch): exe=%s folder=%s title=%s "
                          "secs=%.1f" % (key, folder, title,
                                         self._session_accumulated))
            # the process watcher noticed the exit first: clear the session here too,
            # otherwise tick() sees game=None and never resets it
            self._session_exe = None
            self._session_accumulated = 0.0
            self._reading_start = None
            self.session_seconds = 0.0
            self.total_seconds = 0.0
            self.game = None
            self.status = None
            self.preview = {}
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
            WINEVENT_OUTOFCONTEXT = 0x0000
            PM_REMOVE = 1
            QS_ALLINPUT = 0x04FF

            def timer_proc(hWinEventHook, event, hwnd, idObject, idChild,
                           dwEventThread, dwmsEventTime):
                try:
                    self._hook_on_focus()
                except Exception:
                    pass

            proc_type = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD,
                                           wintypes.HWND, wintypes.LONG, wintypes.LONG,
                                           wintypes.DWORD, wintypes.DWORD)
            callback = proc_type(timer_proc)
            self._hook_callback = callback        # keep alive
            hook = user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
                                          0, callback, 0, 0, WINEVENT_OUTOFCONTEXT)
            if not hook:
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
