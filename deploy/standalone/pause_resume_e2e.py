#!/usr/bin/env python3
"""Run the standalone RRT pause/resume acceptance test and write JSON evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--memory", type=int, default=4096)
    parser.add_argument("--create-timeout", type=int, default=240)
    args = parser.parse_args()

    for name in ("YR_SERVER_ADDRESS", "YR_TOKEN"):
        if not os.environ.get(name, "").strip():
            parser.error(f"{name} is required")

    from yr_sandbox import Sandbox

    started = time.time()
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "startedAtUnix": int(started),
        "result": "failed",
        "steps": [],
    }
    sandbox: Any = None

    def step(name: str, operation: Callable[[], Any]) -> Any:
        step_started = time.monotonic()
        try:
            value = operation()
        except Exception as exc:
            report["steps"].append(
                {
                    "name": name,
                    "result": "failed",
                    "durationSeconds": round(time.monotonic() - step_started, 3),
                    "errorType": type(exc).__name__,
                    "error": str(exc),
                }
            )
            raise
        report["steps"].append(
            {
                "name": name,
                "result": "passed",
                "durationSeconds": round(time.monotonic() - step_started, 3),
            }
        )
        print(f"[PASS] {name}", flush=True)
        return value

    marker_path = "/tmp/akernel-pause-resume-marker.txt"
    marker_value = "akernel-rrt-pause-resume-v1"
    try:
        sandbox = step(
            "create RRT sandbox",
            lambda: Sandbox(
                name=f"akernel-pause-resume-{int(started)}",
                runtime="runsc",
                cpu=1000,
                memory=args.memory,
                create_timeout=args.create_timeout,
                schedule_timeout=180,
            ),
        )
        report["sandboxId"] = sandbox.id

        step("write marker through RRT", lambda: sandbox.files.write(marker_path, marker_value))
        step(
            "read marker before pause",
            lambda: _assert_equal(sandbox.files.read(marker_path), marker_value),
        )
        step(
            "execute command before pause",
            lambda: _assert_command(sandbox.commands.run("printf pre-pause-ok"), "pre-pause-ok"),
        )
        handle = step(
            "start stdin-blocked process",
            lambda: sandbox.commands.run(
                "read value; printf 'resumed:%s' \"$value\"",
                background=True,
                stdin=True,
            ),
        )

        pause_result = step("pause sandbox", lambda: sandbox.pause(ttl_seconds=1800))
        report["pause"] = asdict(pause_result)
        report["snapshotId"] = pause_result.snapshot_id
        step(
            "observe paused state",
            lambda: _assert_equal(sandbox.get_info().state, "paused"),
        )

        resume_result = step("resume sandbox", sandbox.resume)
        report["resume"] = asdict(resume_result)
        step(
            "observe running state",
            lambda: _assert_equal(sandbox.get_info().state, "running"),
        )
        step(
            "read marker after resume",
            lambda: _assert_equal(sandbox.files.read(marker_path), marker_value),
        )
        step("send stdin after resume", lambda: handle.send_stdin("continuity\n", eof=True))
        step(
            "verify process continuity",
            lambda: _assert_command(handle.wait(timeout=90), "resumed:continuity"),
        )
        step(
            "verify direct route remains active",
            lambda: _assert_equal(sandbox._client._direct_disabled, False),
        )
        report["result"] = "passed"
    except Exception as exc:
        report["errorType"] = type(exc).__name__
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
    finally:
        if sandbox is not None:
            try:
                sandbox.kill()
                report["cleanup"] = "passed"
            except Exception as exc:
                report["cleanup"] = "failed"
                report["cleanupError"] = f"{type(exc).__name__}: {exc}"
                report["result"] = "failed"
        report["finishedAtUnix"] = int(time.time())
        report["durationSeconds"] = round(time.time() - started, 3)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    if report["result"] != "passed":
        print(json.dumps({"result": report["result"], "error": report.get("error")}), file=sys.stderr)
        return 1
    print(json.dumps({"result": "passed", "report": str(args.report)}))
    return 0


def _assert_equal(actual: Any, expected: Any) -> None:
    if actual != expected:
        raise AssertionError(f"expected {expected!r}, got {actual!r}")


def _assert_command(result: Any, expected_stdout: str) -> None:
    if result.exit_code != 0 or result.stdout != expected_stdout:
        raise AssertionError(
            f"expected rc=0 stdout={expected_stdout!r}, "
            f"got rc={result.exit_code} stdout={result.stdout!r} stderr={result.stderr!r}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
