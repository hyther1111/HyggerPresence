"""Hygger Presence 1.0.4 - Detector"""
from .core import *          # stdlib / third-party handles + constants + helpers
from .winapi import *        # ctypes layer: foreground window, idle, process snapshot


class DetectorMixin:
    def _resolved(self, path_str):
        """Path.resolve() with a cache.

        1.0.3: resolve() is a GetFinalPathNameByHandle syscall and measured
        ~140 µs here — the single most expensive thing the old scan did, since it
        ran once per (game × process). Existing paths are cached for good, misses
        for 30 s so a path that appears later is still picked up.
        """
        try:
            key = str(path_str)
        except Exception:
            key = ""
        hit = _resolve_cache.get(key)
        if hit is not None:
            value, is_real, stamp = hit
            if is_real or (time.monotonic() - stamp) < 30.0:
                return value
        try:
            value = Path(path_str).resolve()
        except Exception:
            try:
                value = Path(path_str)
            except Exception:
                return None
        try:
            is_real = value.exists()
        except Exception:
            is_real = False
        if key:
            if len(_resolve_cache) > 4096:
                _resolve_cache.clear()
            _resolve_cache[key] = (value, is_real, time.monotonic())
        return value

    def _proc_exe(self, pid):
        """Resolved image path of one pid (None when unreadable)."""
        try:
            raw = psutil.Process(pid).exe()
            return self._resolved(raw) if raw else None
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            return None
        except Exception:
            return None

    def get_game_pids(self, game):
        """Match running processes to a library entry.

        Priority:
          1) Full resolved path of game["exe"]
          2) Same filename + same parent folder (handles some path quirks)
          3) Extra process_names (Locale Emulator helpers, etc.)
          4) Any other .exe that runs from the game's own folder
          5) Bare filename ONLY if that filename is unique in the library

        1.0.3: driven by one Toolhelp snapshot (see snapshot_processes) and the
        exe path is read only for processes whose name can match.
        """
        target_path = self._resolved(game.get("exe", ""))
        target_name = Path(game.get("exe", "")).name.lower() if game.get("exe") else ""
        target_parent = target_path.parent if target_path else None
        extra_names = {
            n.strip().lower()
            for n in game.get("process_names", [])
            if n.strip()
        }
        allow_name_match = self._allow_name_match(target_name)
        folder = self._game_folder(game)
        folder_ok = bool(folder) and self._folder_exclusive(game, folder)
        hint = folder_exe_names(folder) if folder_ok else frozenset()

        pids = set()
        for pid, _ppid, pname in snapshot_processes():
            if not pname:
                continue
            if pname in extra_names:          # helper names: no path needed
                pids.add(pid)
                continue
            if not target_name or pname != target_name:
                # 1.0.3: a differently named exe started from the game's folder
                # (patched exe / bundled engine) still belongs to this entry.
                if folder_ok and pname in hint:
                    pexe = self._proc_exe(pid)
                    if self._exe_in_game_folder(game, pexe):
                        pids.add(pid)
                continue
            pexe = self._proc_exe(pid)
            if pexe and target_path and pexe == target_path:
                pids.add(pid)
            elif pexe and target_parent and pexe.parent == target_parent:
                pids.add(pid)
            elif pname in hint and self._exe_in_game_folder(game, pexe):
                pids.add(pid)
            elif allow_name_match:
                pids.add(pid)
        return pids

    def _game_folder(self, game):
        """Folder the library exe lives in (works even if the file is gone)."""
        path = self._resolved(game.get("exe", ""))
        return path.parent if path else None

    def _folder_exclusive(self, game, folder):
        """True when no *other* library entry lives under this folder.

        Keeps the folder rule safe for people who keep games flat in one
        directory (D:\\VN\\a.exe, D:\\VN\\b.exe): there the folder says nothing
        about which game a process belongs to.
        """
        if not folder:
            return False
        prefix = str(folder).lower().rstrip("\\/") + os.sep
        for other in self.games:
            if other is game:
                continue
            other_path = self._resolved(other.get("exe", ""))
            if other_path and str(other_path).lower().startswith(prefix):
                return False
        return True

    def _exe_in_game_folder(self, game, pexe):
        """`pexe` is an exe running from this game's own folder."""
        if not pexe:
            return False
        folder = self._game_folder(game)
        if not folder or not is_under(pexe, folder):
            return False
        return self._folder_exclusive(game, folder)

    def is_game_running(self, game):
        return len(self.get_game_pids(game)) > 0

    def find_active_game(self):
        """One process snapshot → best matching library game + its PIDs.

        Score: path=100, same folder+name=90, process_names=70,
               other exe from the game folder=60, unique filename=10.
        Returns (game, pids) or (None, set()).
        """
        procs = snapshot_processes()

        # name -> [pid] so each library entry only has to look at the handful of
        # processes that could match it (the old shape compared every game
        # against every process on every scan).
        by_name, name_of, name_counts = {}, {}, {}
        for pid, _ppid, pname in procs:
            if pname:
                by_name.setdefault(pname, []).append(pid)
                name_of[pid] = pname
        for g in self.games:
            n = Path(g.get("exe", "")).name.lower() if g.get("exe") else ""
            if n:
                name_counts[n] = name_counts.get(n, 0) + 1

        exe_of = {}

        def exe_path(pid):
            if pid not in exe_of:
                exe_of[pid] = self._proc_exe(pid)
            return exe_of[pid]

        best, best_score, best_pids = None, -1, set()
        for g in self.games:
            target_path = self._resolved(g.get("exe", ""))
            target_name = Path(g.get("exe", "")).name.lower() if g.get("exe") else ""
            target_parent = target_path.parent if target_path else None
            extra_names = {n.strip().lower() for n in g.get("process_names", []) if n.strip()}
            same_name = name_counts.get(target_name, 0)

            candidate_pids = set(by_name.get(target_name, ())) if target_name else set()
            for extra in extra_names:
                candidate_pids.update(by_name.get(extra, ()))

            score, pids = 0, set()
            for pid in candidate_pids:
                pname = name_of.get(pid, "")
                pexe = exe_path(pid)
                hit = False
                if target_path and pexe and pexe == target_path:
                    score, hit = max(score, 100), True
                elif (target_path and pexe and target_name
                      and pname == target_name
                      and target_parent and pexe.parent == target_parent):
                    score, hit = max(score, 90), True
                elif pname in extra_names:
                    score, hit = max(score, 70), True
                elif target_name and pname == target_name and same_name <= 1:
                    score, hit = max(score, 10), True
                if hit:
                    pids.add(pid)
            if score > best_score:
                best, best_score, best_pids = g, score, pids

        # ── 1.0.3: other executables inside each game's own folder ──────────
        # Only when nothing stronger was found, and only for folders that belong
        # to exactly one library entry. This is what removes the need for the
        # user to discover and type "process_names" themselves.
        if best_score < 60:
            folder_entries, hint_union = [], set()
            for g in self.games:
                folder = self._game_folder(g)
                if not folder or not self._folder_exclusive(g, folder):
                    continue
                names = folder_exe_names(folder)
                if not names:
                    continue
                folder_entries.append((g, folder, names))
                hint_union |= names
            if folder_entries:
                folder_pids = {}
                for pid, _ppid, pname in procs:
                    if pname not in hint_union:
                        continue
                    pexe = exe_path(pid)
                    if not pexe:
                        continue
                    for g, folder, names in folder_entries:
                        if pname in names and is_under(pexe, folder):
                            folder_pids.setdefault(id(g), (g, set()))[1].add(pid)
                for g, hits in folder_pids.values():
                    if hits and 60 > best_score:
                        best, best_score, best_pids = g, 60, hits

        return (best, best_pids) if best_score > 0 else (None, set())

    def _allow_name_match(self, target_name):
        """Bare-filename matching is only safe while that name is unique here."""
        if not target_name:
            return False
        same = sum(1 for g in self.games
                   if Path(g.get("exe", "")).name.lower() == target_name)
        return same <= 1

    def _library_names(self):
        """Every exe name the library can match (used by the focus hook).

        Includes the executables found inside each game's folder, so launching a
        differently named game exe still triggers the fast snapshot refresh.
        Cached until the library changes.
        """
        signature = tuple(g.get("exe", "") for g in self.games)
        if getattr(self, "_lib_names_sig", None) == signature:
            return self._lib_names_cache
        names = set()
        for g in self.games:
            name = Path(g.get("exe", "")).name.lower() if g.get("exe") else ""
            if name:
                names.add(name)
            for extra in g.get("process_names", []):
                extra = extra.strip().lower()
                if extra:
                    names.add(extra)
            folder = self._game_folder(g)
            if folder:
                names |= folder_exe_names(folder)
        self._lib_names_sig = signature
        self._lib_names_cache = names
        return names

    def _pid_matches_game(self, pid, game):
        """True when one pid looks like `game` — same rules as get_game_pids().

        1.0.3: one handle (exe) instead of two; the name comes from the exe
        basename, or from the cached snapshot when the handle is denied.
        """
        pexe = self._proc_exe(pid)
        pname = pexe.name.lower() if pexe else _proc_cache["names"].get(pid, "")
        if not pexe and not pname:
            return False

        target_path = self._resolved(game.get("exe", ""))
        target_name = Path(game.get("exe", "")).name.lower() if game.get("exe") else ""
        extra_names = {n.strip().lower() for n in game.get("process_names", []) if n.strip()}

        if target_path and pexe and pexe == target_path:
            return True
        if (target_path and target_name and pexe and target_name
                and pexe.name.lower() == target_name and pexe.parent == target_path.parent):
            return True
        if pname and pname in extra_names:
            return True
        # 1.0.3: the window belongs to a differently named exe from the game's own
        # folder (patched exe / bundled engine) — same rule as find_active_game.
        if pexe and self._exe_in_game_folder(game, pexe):
            return True
        if pname and target_name and pname == target_name and self._allow_name_match(target_name):
            return True
        return False

    def resolve_focus(self, game, pids):
        """Does the foreground window belong to this game?

        Returns ("focused" | "paused" | "unknown", reason).

        1.0.3 fix: 1.0.2 asked only `fg in pids`. That is true only when the exe
        stored in the library is itself the process that owns the window. Any game
        started through Locale Emulator / GalFC / AlphaROMdiE / a stub launcher
        runs as a *child* of the detected process, so the window owner was never
        in `pids` → status locked on "Paused" → Session 0s (the stopwatch only
        runs while Reading). Now the process tree is taken into account.
        """
        fg = get_foreground_pid()
        self._last_fg = fg
        if not fg:
            # Cannot tell (fullscreen switch, lock screen, other desktop...).
            # Better than guessing "paused": keep the game's time running and let
            # the idle threshold decide, instead of freezing at 0s forever.
            return "unknown", "no-foreground-window"
        if fg in pids:
            return "focused", "foreground-is-matched-pid"
        # The matched process is a launcher/wrapper and the window belongs to a
        # child of it (Locale Emulator, GalFC, bootstrapper, game relaunching).
        for ancestor in get_ancestor_pids(fg):
            if ancestor in pids:
                return "focused", f"foreground-child-of-{ancestor}"
        # Only a helper (process_names) was matched, or the stored exe path is
        # stale (folder moved, re-patched exe...): judge by the window owner.
        if self._pid_matches_game(fg, game):
            return "focused", "foreground-looks-like-game"
        return "paused", f"foreground-pid={fg}"

    def get_status(self, game, pids=None):
        if pids is None:
            pids = self.get_game_pids(game)
        if not pids:
            return "Idle"
        focus, why = self.resolve_focus(game, pids)
        if focus == "paused":
            if DEBUG_LOG_ENABLED:
                fg_desc = ""
                if getattr(self, "_last_fg", None):
                    fg_desc = " fg=" + self._describe_pid(self._last_fg)
                self._debug(
                    f"status=Paused game={Path(game.get('exe', '')).name} "
                    f"reason={why}{fg_desc} pids={sorted(pids)} games={len(self.games)}"
                )
            return "Paused"
        if get_idle_seconds() >= IDLE_THRESHOLD:
            self._debug(f"status=Idle game={Path(game.get('exe', '')).name} reason={why}")
            return "Idle"
        self._debug(f"status=Reading game={Path(game.get('exe', '')).name} reason={why}")
        return "Reading"
