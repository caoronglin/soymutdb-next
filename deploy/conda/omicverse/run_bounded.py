"""Linux qualification command runner; not a production job executor."""

import argparse
import json
import os
import pathlib
import resource
import signal
import subprocess
import sys
import time

THREAD_KEYS = (
    "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS",
    "UV_CONCURRENT_DOWNLOADS", "UV_CONCURRENT_BUILDS", "RAYON_NUM_THREADS",
    "LOKY_MAX_CPU_COUNT", "PYTHON_CPU_COUNT", "VECLIB_MAXIMUM_THREADS",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--seconds", required=True, type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command or args.seconds <= 0:
        parser.error("a command and positive timeout are required")
    root = args.output.absolute()
    root.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(dict.fromkeys(THREAD_KEYS, "1"))
    for key, sub in (
        ("UV_CACHE_DIR", "uv-cache"), ("UV_PYTHON_INSTALL_DIR", "python"),
        ("MPLCONFIGDIR", "mpl"), ("XDG_CACHE_HOME", "xdg"), ("HOME", "home"),
        ("TMPDIR", "tmp"), ("NUMBA_CACHE_DIR", "numba"),
    ):
        directory = root / sub
        directory.mkdir()
        env[key] = str(directory)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["UV_PYTHON_DOWNLOADS"] = "never"
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)

    def limits():
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
        resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (args.seconds, args.seconds + 5))

    child = None

    def stop_group(signum, frame):
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_group)
    signal.signal(signal.SIGINT, stop_group)
    start = time.monotonic()
    rc = 1
    error = None
    with (root / "command.log").open("x") as log:
        try:
            child = subprocess.Popen(
                command, stdout=log, stderr=subprocess.STDOUT, env=env,
                # This standalone stdlib runner never starts threads before fork.
                preexec_fn=limits, start_new_session=True,  # noqa: PLW1509
            )
            rc = child.wait(timeout=args.seconds)
        except subprocess.TimeoutExpired:
            rc = 124
        except KeyboardInterrupt:
            rc = 130
        except OSError as exc:
            error = str(exc)
        finally:
            # Also remove descendants left behind by a failed or normally exited leader.
            if child is not None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
    record = {
        "command": command, "exit_code": rc, "error": error,
        "elapsed_seconds": time.monotonic() - start,
        "max_child_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        "timeout_seconds": args.seconds, "address_space_limit_bytes": 8 * 1024**3,
        "thread_limit": 1,
    }
    (root / "command.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record))
    return rc if rc >= 0 else 128 - rc


if __name__ == "__main__":
    sys.exit(main())
