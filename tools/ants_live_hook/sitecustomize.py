"""Live frames for the Studio: tee the frames ASPIRE already encodes into its video.

Only ever on `PYTHONPATH` when the Studio console (`ants.studio.live_view.enable`) started the
process, with `ANTS_LIVE_DIR` set; without that variable this module does nothing, so every other
command behaves as before. It covers `cap-harness` run directly and through
`tools/aspire_launch.py`, because it wraps `cap_harness.artifacts.RunRecorder` when that module is
imported.

`ants_live_mirror.py` beside this file adds the 3D Live mirror's data the same way: read-only, from
state the simulator has already computed.

It renders nothing and never touches the simulator or a random generator: it receives the arrays
the recorder has already rendered for `media/videos`, after the original method has run. Files are
replaced atomically, so a reader never sees half a frame. Any error here switches the tee off and
never reaches the rollout.
"""

from __future__ import annotations

import os

LIVE_DIR = os.environ.get("ANTS_LIVE_DIR")


def _argv_info(argv: list[str]) -> dict:
    """Seed, program and perturbation of this rollout, read from its own command line."""
    import json
    from pathlib import Path

    def value(flag: str) -> str | None:
        return argv[argv.index(flag) + 1] if flag in argv[:-1] else None

    info: dict = {"seed": value("--seed"), "program": value("--program"), "perturbation": {}}
    if "--" in argv and argv.index("--") >= 2:  # tools/aspire_launch.py <spec.json> -- run ...
        spec = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        keys = ("pose", "physics", "camera", "lighting", "actuation", "scale")
        info["perturbation"] = {k: spec[k] for k in keys if spec.get(k)}
    return info


class _Tee:
    """Writes `<camera>.jpg` and `status.json` at most `fps` times a second."""

    def __init__(self, folder: str, fps: float = 8.0) -> None:
        import atexit
        import json
        import sys
        import time
        from pathlib import Path

        from PIL import Image

        self._json, self._time, self._image = json, time, Image
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        for pattern in ("*.jpg", "mirror_*"):  # a previous rollout's data must never look current
            for old in self.dir.glob(pattern):
                old.unlink(missing_ok=True)
        self.period = 1.0 / fps
        self.last = 0.0
        self.frames = 0
        self.status = {"pid": os.getpid(), "started": time.time(), "ended": False, "cameras": []}
        try:
            self.status.update(_argv_info(sys.argv))
        except (OSError, ValueError, IndexError):
            pass
        self._write_status()
        atexit.register(self.close)

    def _write_status(self) -> None:
        tmp = self.dir / f".status.{os.getpid()}.tmp"
        tmp.write_text(self._json.dumps(self.status), encoding="utf-8")
        os.replace(tmp, self.dir / "status.json")

    def frame(self, cameras: dict, step: int) -> None:
        now = self._time.monotonic()
        if now - self.last < self.period:
            return
        self.last = now
        if _SIM["sim"] is not None and not _SIM["dead"]:
            try:  # before the frames, so a reader sees state at least as new as the status
                import ants_live_mirror

                ants_live_mirror.write(_SIM["sim"], self.dir, step, _SIM)
                self.status["mirror"] = _SIM.get("mirror_id")
            except Exception:  # noqa: BLE001 -- losing the 3D view must not lose the frames
                _SIM["dead"] = True
        for name, camera in cameras.items():
            tmp = self.dir / f".{name}.{os.getpid()}.tmp"
            self._image.fromarray(camera.rgb).save(tmp, format="JPEG", quality=70)
            os.replace(tmp, self.dir / f"{name}.jpg")
        self.frames += 1
        self.status.update(
            cameras=sorted(cameras), step=step, frames=self.frames, frame_time=self._time.time()
        )
        self._write_status()

    def close(self) -> None:
        try:
            self.status["ended"] = True
            self._write_status()
        except OSError:
            pass


_SIM: dict = {"sim": None, "dead": False}  # the simulator of this rollout, read-only


def _install_sim(module) -> None:
    sim_class = module.MjSim
    original = sim_class.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        _SIM["sim"] = self  # a rebuilt scene replaces the old simulator

    sim_class.__init__ = init


def _install(module) -> None:
    recorder = module.RunRecorder
    original = recorder._encode_video_frame
    state: dict = {"tee": None, "dead": False}

    def encode_video_frame(self, observation, step):
        original(self, observation, step)
        if state["dead"]:
            return
        try:
            if state["tee"] is None:
                state["tee"] = _Tee(LIVE_DIR)
            state["tee"].frame(observation.cameras, step)
        except Exception:  # noqa: BLE001 -- the live view never affects a rollout
            state["dead"] = True

    recorder._encode_video_frame = encode_video_frame


if LIVE_DIR:
    import importlib.abc
    import importlib.util
    import sys

    _TARGETS = {"cap_harness.artifacts": _install, "robosuite.utils.binding_utils": _install_sim}

    class _Finder(importlib.abc.MetaPathFinder):
        """Runs the matching `_install*` right after its module is imported."""

        def find_spec(self, name, path=None, target=None):
            install = _TARGETS.get(name)
            if install is None:
                return None
            sys.meta_path.remove(self)
            try:
                spec = importlib.util.find_spec(name)
            finally:
                sys.meta_path.insert(0, self)
            if spec is None or spec.loader is None:
                return spec
            exec_module = spec.loader.exec_module

            def wrapped(module):
                exec_module(module)
                try:
                    install(module)
                except Exception:  # noqa: BLE001 -- the live view never affects a rollout
                    pass

            spec.loader.exec_module = wrapped
            return spec

    sys.meta_path.insert(0, _Finder())
