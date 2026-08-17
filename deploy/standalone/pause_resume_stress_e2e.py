#!/usr/bin/env python3
"""Exercise repeated and interleaved RRT pause/resume with resource evidence."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

import pause_resume_e2e as base


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--node-container", default="akernel-node")
    parser.add_argument(
        "--host-checkpoint-root",
        type=Path,
        default=Path(__file__).resolve().parent
        / "data"
        / "sandboxd"
        / "root"
        / "checkpoints",
    )
    parser.add_argument("--loop-count", type=int, default=5)
    parser.add_argument("--instance-count", type=int, default=3)
    parser.add_argument("--cpu", type=int, default=1000)
    parser.add_argument("--memory", type=int, default=4096)
    parser.add_argument("--create-timeout", type=int, default=240)
    args = parser.parse_args()
    if args.loop_count < 2 or args.instance_count < 3:
        parser.error("loop-count must be >=2 and instance-count must be >=3")
    for name in ("YR_SERVER_ADDRESS", "YR_GATEWAY_ADDRESS", "YR_TOKEN"):
        if not os.environ.get(name, "").strip():
            parser.error(f"{name} is required")

    from yr_sandbox import Sandbox

    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "result": "failed",
        "runtime": "RRT/Rust Runtime",
        "publicDataPlane": "SandboxRouter",
        "startedAtUnix": int(time.time()),
        "loopCount": args.loop_count,
        "instanceCount": args.instance_count,
        "single-instance-loop": {},
        "multi-instance-interleaved": {},
    }
    managed: list[Any] = []
    baseline_checkpoint_views = _checkpoint_views(
        args.node_container, args.host_checkpoint_root
    )
    report["checkpointBaseline"] = baseline_checkpoint_views
    report["containerCheckpointImages"] = baseline_checkpoint_views["container"]
    report["hostCheckpointImages"] = baseline_checkpoint_views["host"]

    try:
        idle = _resource_view(args.node_container)
        capacity = idle["capacity"]
        _assert_allocatable(idle, capacity["CPU"], capacity["Memory"])
        report["idleResourceView"] = idle

        single = _run_single_loop(Sandbox, args, capacity, managed)
        report["single-instance-loop"] = single

        interleaved = _run_interleaved(Sandbox, args, capacity, managed)
        report["multi-instance-interleaved"] = interleaved

        final_resources, convergence = _await_resources(
            args.node_container, capacity["CPU"], capacity["Memory"]
        )
        report["finalResourceView"] = final_resources
        report["finalResourceViewConvergenceSeconds"] = convergence
        final_checkpoint_views = _checkpoint_views(
            args.node_container, args.host_checkpoint_root
        )
        report["checkpointFinal"] = final_checkpoint_views
        report["containerCheckpointImages"] = final_checkpoint_views["container"]
        report["hostCheckpointImages"] = final_checkpoint_views["host"]
        baseline_facts = {
            (item["relativePath"], item["size"])
            for item in baseline_checkpoint_views["container"]
        }
        new_files = [
            item
            for item in final_checkpoint_views["container"]
            if (item["relativePath"], item["size"]) not in baseline_facts
        ]
        report["newCheckpointImages"] = new_files
        if new_files:
            raise AssertionError(f"new checkpoint.img cache files remain: {new_files!r}")
        report["performanceSummary"] = _performance_summary(single, interleaved)
        report["result"] = "passed"
    except Exception as exc:
        report["errorType"] = type(exc).__name__
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
    finally:
        for sandbox in reversed(managed):
            try:
                sandbox.kill()
            except Exception:
                pass
        report["finishedAtUnix"] = int(time.time())
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    if report["result"] != "passed":
        print(json.dumps({"result": "failed", "error": report.get("error")}), file=sys.stderr)
        return 1
    print(json.dumps({"result": "passed", "report": str(args.report)}))
    return 0


def _timed(operation: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    value = operation()
    return value, round(time.perf_counter() - started, 6)


def _create_sandbox(Sandbox: Any, args: argparse.Namespace, name: str, port: int) -> Any:
    return Sandbox(
        name=name,
        runtime="runsc",
        cpu=args.cpu,
        memory=args.memory,
        create_timeout=args.create_timeout,
        schedule_timeout=180,
        port_forwardings=[port],
    )


def _start_workload(sandbox: Any, marker: str, port: int, body: str) -> str:
    sandbox.files.write(marker, "initial")
    sandbox.commands.run(
        "sh -c 'echo $$ > /tmp/akernel-loop-process.pid; while :; do sleep 60; done'",
        background=True,
    )
    ready = f"/tmp/akernel-public-{port}-ready"
    server = rf'''perl -MSocket -e '$|=1; socket(S,PF_INET,SOCK_STREAM,getprotobyname("tcp")); setsockopt(S,SOL_SOCKET,SO_REUSEADDR,1); bind(S,sockaddr_in({port},INADDR_ANY)) or die $!; listen(S,10); open(F, ">", "{ready}") or die $!; print F "ready"; close F; while(accept(C,S)){{ print C "HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n{body}"; close C; }}' '''
    sandbox.commands.run(server, background=True)
    result = sandbox.commands.run(f"while [ ! -f {ready} ]; do sleep 0.05; done; printf ready")
    base._assert_command(result, "ready")
    public_url = sandbox.get_port_url(port)
    base._assert_equal(base._fetch_public_once(public_url), body)
    return public_url


def _run_single_loop(
    Sandbox: Any,
    args: argparse.Namespace,
    capacity: dict[str, int],
    managed: list[Any],
) -> dict[str, Any]:
    started = int(time.time())
    marker = "/tmp/akernel-loop-marker"
    public_port = 18081
    public_body = "akernel-loop-ok"
    sandbox, create_seconds = _timed(
        lambda: _create_sandbox(Sandbox, args, f"akernel-loop-{started}", public_port)
    )
    managed.append(sandbox)
    public_url = _start_workload(sandbox, marker, public_port, public_body)
    running_resources, create_convergence = _await_resources(
        args.node_container,
        capacity["CPU"] - args.cpu,
        capacity["Memory"] - args.memory,
    )
    result: dict[str, Any] = {
        "sandboxId": sandbox.id,
        "createSeconds": create_seconds,
        "createResourceViewConvergenceSeconds": create_convergence,
        "runningResourceView": running_resources,
        "cycles": [],
    }

    for cycle in range(1, args.loop_count + 1):
        marker_value = f"loop-cycle-{cycle}"
        sandbox.files.write(marker, marker_value)
        source = base._capture_authority(
            args.node_container,
            sandbox.id,
            f"loop-{cycle}-source-running",
            args.evidence_dir,
        )
        base._assert_running_authority(source)

        pause_result, pause_seconds = _timed(lambda: sandbox.pause(ttl_seconds=1800))
        paused = base._capture_authority(
            args.node_container, sandbox.id, f"loop-{cycle}-paused", args.evidence_dir
        )
        base._assert_paused_authority(paused, pause_result.snapshot_id, source["instance"]["value"])
        paused_resources, paused_convergence = _await_resources(
            args.node_container, capacity["CPU"], capacity["Memory"]
        )
        paused_images = _checkpoint_views(
            args.node_container, args.host_checkpoint_root, sandbox.id
        )
        base._assert_public_paused_once(public_url)

        resume_result, resume_seconds = _timed(sandbox.resume)
        marker_after, first_file_seconds = _timed(lambda: sandbox.files.read(marker))
        base._assert_equal(marker_after, marker_value)
        exec_after, first_exec_seconds = _timed(
            lambda: sandbox.commands.run(
                "kill -0 $(cat /tmp/akernel-loop-process.pid) && printf loop-running"
            )
        )
        base._assert_command(exec_after, "loop-running")
        public_after, first_public_seconds = _timed(lambda: base._fetch_public_once(public_url))
        base._assert_equal(public_after, public_body)

        winner = base._capture_authority(
            args.node_container,
            sandbox.id,
            f"loop-{cycle}-winner-running",
            args.evidence_dir,
        )
        base._assert_running_authority(winner)
        base._assert_snapshot_cleaned(winner, pause_result.snapshot_id)
        winner_mappings = base._port_mappings_from_instance(winner["instance"]["value"])
        base._assert_equal(base._normalize_port_mappings(resume_result.port_mappings), winner_mappings)
        running_resources, running_convergence = _await_resources(
            args.node_container,
            capacity["CPU"] - args.cpu,
            capacity["Memory"] - args.memory,
        )
        resumed_images = _checkpoint_views(
            args.node_container, args.host_checkpoint_root, sandbox.id
        )
        if resumed_images["container"]:
            raise AssertionError(
                f"cycle {cycle} retains checkpoint.img after successful resume: {resumed_images!r}"
            )
        result["cycles"].append(
            {
                "cycle": cycle,
                "snapshotId": pause_result.snapshot_id,
                "pauseSeconds": pause_seconds,
                "resumeSeconds": resume_seconds,
                "firstFileSeconds": first_file_seconds,
                "firstExecSeconds": first_exec_seconds,
                "firstPublicSeconds": first_public_seconds,
                "resourceViewConvergenceSeconds": {
                    "paused": paused_convergence,
                    "running": running_convergence,
                },
                "pausedResourceView": paused_resources,
                "runningResourceView": running_resources,
                "checkpointImagesWhilePaused": paused_images,
                "checkpointImagesAfterResume": resumed_images,
                "portMappings": winner_mappings,
            }
        )

    _, delete_seconds = _timed(sandbox.kill)
    managed.remove(sandbox)
    _, cleanup_convergence = _await_resources(
        args.node_container, capacity["CPU"], capacity["Memory"]
    )
    result["deleteSeconds"] = delete_seconds
    result["cleanupResourceViewConvergenceSeconds"] = cleanup_convergence
    result["checkpointImagesAfterDelete"] = _checkpoint_views(
        args.node_container, args.host_checkpoint_root, sandbox.id
    )
    if result["checkpointImagesAfterDelete"]["container"]:
        raise AssertionError("single loop left checkpoint.img after delete")
    return result


def _run_interleaved(
    Sandbox: Any,
    args: argparse.Namespace,
    capacity: dict[str, int],
    managed: list[Any],
) -> dict[str, Any]:
    stamp = int(time.time())
    sandboxes: list[Any] = []
    metadata: list[dict[str, Any]] = []
    for index in range(args.instance_count):
        port = 18100 + index
        body = f"akernel-interleaved-{index}"
        sandbox, create_seconds = _timed(
            lambda index=index, port=port: _create_sandbox(
                Sandbox, args, f"akernel-cross-{stamp}-{index}", port
            )
        )
        sandboxes.append(sandbox)
        managed.append(sandbox)
        marker = f"/tmp/akernel-cross-{index}-marker"
        public_url = _start_workload(sandbox, marker, port, body)
        sandbox.files.write(marker, f"cross-{index}")
        metadata.append(
            {
                "sandbox": sandbox,
                "marker": marker,
                "body": body,
                "publicURL": public_url,
                "createSeconds": create_seconds,
                "state": "running",
            }
        )
        _await_resources(
            args.node_container,
            capacity["CPU"] - args.cpu * (index + 1),
            capacity["Memory"] - args.memory * (index + 1),
        )

    actions = [
        ("pause", 0),
        ("pause", 1),
        ("resume", 0),
        ("pause", 2),
        ("resume", 1),
        ("resume", 2),
    ]
    action_evidence: list[dict[str, Any]] = []
    for ordinal, (operation, index) in enumerate(actions, start=1):
        item = metadata[index]
        sandbox = item["sandbox"]
        evidence: dict[str, Any] = {"ordinal": ordinal, "operation": operation, "index": index}
        if operation == "pause":
            source = base._capture_authority(
                args.node_container,
                sandbox.id,
                f"cross-{ordinal}-{index}-source-running",
                args.evidence_dir,
            )
            pause_result, elapsed = _timed(lambda: sandbox.pause(ttl_seconds=1800))
            paused = base._capture_authority(
                args.node_container,
                sandbox.id,
                f"cross-{ordinal}-{index}-paused",
                args.evidence_dir,
            )
            base._assert_paused_authority(
                paused, pause_result.snapshot_id, source["instance"]["value"]
            )
            base._assert_public_paused_once(item["publicURL"])
            item["state"] = "paused"
            item["snapshotId"] = pause_result.snapshot_id
            evidence["snapshotId"] = pause_result.snapshot_id
            evidence["pauseSeconds"] = elapsed
            evidence["checkpointImages"] = _checkpoint_views(
                args.node_container, args.host_checkpoint_root, sandbox.id
            )
        else:
            resume_result, elapsed = _timed(sandbox.resume)
            marker_value, first_file = _timed(lambda: sandbox.files.read(item["marker"]))
            base._assert_equal(marker_value, f"cross-{index}")
            exec_result, first_exec = _timed(lambda: sandbox.commands.run("printf cross-running"))
            base._assert_command(exec_result, "cross-running")
            public_body, first_public = _timed(
                lambda: base._fetch_public_once(item["publicURL"])
            )
            base._assert_equal(public_body, item["body"])
            winner = base._capture_authority(
                args.node_container,
                sandbox.id,
                f"cross-{ordinal}-{index}-winner-running",
                args.evidence_dir,
            )
            base._assert_running_authority(winner)
            base._assert_snapshot_cleaned(winner, item["snapshotId"])
            base._assert_equal(
                base._normalize_port_mappings(resume_result.port_mappings),
                base._port_mappings_from_instance(winner["instance"]["value"]),
            )
            item["state"] = "running"
            evidence.update(
                {
                    "resumeSeconds": elapsed,
                    "firstFileSeconds": first_file,
                    "firstExecSeconds": first_exec,
                    "firstPublicSeconds": first_public,
                    "checkpointImages": _checkpoint_views(
                        args.node_container, args.host_checkpoint_root, sandbox.id
                    ),
                }
            )
            if evidence["checkpointImages"]["container"]:
                raise AssertionError(
                    f"interleaved resume {index} retains checkpoint.img: {evidence['checkpointImages']!r}"
                )

        running_count = sum(item["state"] == "running" for item in metadata)
        resources, convergence = _await_resources(
            args.node_container,
            capacity["CPU"] - args.cpu * running_count,
            capacity["Memory"] - args.memory * running_count,
        )
        evidence["runningCount"] = running_count
        evidence["resourceView"] = resources
        evidence["resourceViewConvergenceSeconds"] = convergence
        action_evidence.append(evidence)

    for index, item in enumerate(metadata):
        sandbox = item["sandbox"]
        base._assert_equal(sandbox.files.read(item["marker"]), f"cross-{index}")
        sandbox.kill()
        managed.remove(sandbox)
        remaining = args.instance_count - index - 1
        _await_resources(
            args.node_container,
            capacity["CPU"] - args.cpu * remaining,
            capacity["Memory"] - args.memory * remaining,
        )
        if _checkpoint_views(
            args.node_container, args.host_checkpoint_root, sandbox.id
        )["container"]:
            raise AssertionError(f"interleaved sandbox {index} left checkpoint.img after delete")

    return {
        "instances": [
            {key: value for key, value in item.items() if key != "sandbox"} for item in metadata
        ],
        "actions": action_evidence,
    }


def _resource_view(node_container: str) -> dict[str, Any]:
    address = base._node_ip(node_container)
    response = base._docker_exec(
        node_container,
        "curl",
        "-fsS",
        f"http://{address}:22770/global-scheduler/resources",
    )
    payload = json.loads(response.stdout)
    resource = payload["resource"]

    def values(section: str) -> dict[str, int]:
        entries = resource[section]["resources"]
        return {
            name: int(entries.get(name, {}).get("scalar", {}).get("value", 0))
            for name in ("CPU", "Memory", "storage")
        }

    return {
        "requestID": payload.get("requestID"),
        "revision": int(resource.get("revision", 0)),
        "capacity": values("capacity"),
        "allocatable": values("allocatable"),
        "actualUse": values("actualUse"),
    }


def _assert_allocatable(view: dict[str, Any], cpu: int, memory: int) -> None:
    actual = view["allocatable"]
    if actual["CPU"] != cpu or actual["Memory"] != memory:
        raise AssertionError(
            f"resource view mismatch: expected CPU={cpu} Memory={memory}, got {view!r}"
        )


def _await_resources(
    node_container: str, cpu: int, memory: int, timeout: float = 5.0
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    last = _resource_view(node_container)
    while last["allocatable"]["CPU"] != cpu or last["allocatable"]["Memory"] != memory:
        if time.perf_counter() - started >= timeout:
            _assert_allocatable(last, cpu, memory)
        time.sleep(0.05)
        last = _resource_view(node_container)
    return last, round(time.perf_counter() - started, 6)


def _container_checkpoint_images(
    node_container: str, instance_id: str = ""
) -> list[dict[str, Any]]:
    result = base._docker_exec(
        node_container,
        "find",
        "/home/akernel/sandboxd/root/checkpoints",
        "-type",
        "f",
        "-name",
        "checkpoint.img",
        "-printf",
        "%p\t%s\n",
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"checkpoint cache scan failed: {result.stderr}")
    images: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        path, size = line.rsplit("\t", 1)
        if instance_id and instance_id not in path:
            continue
        relative = path.removeprefix("/home/akernel/sandboxd/root/checkpoints/")
        images.append({"path": path, "relativePath": relative, "size": int(size)})
    return sorted(images, key=lambda item: item["relativePath"])


def _host_checkpoint_images(
    host_checkpoint_root: Path, instance_id: str = ""
) -> list[dict[str, Any]]:
    if not host_checkpoint_root.exists():
        return []
    images: list[dict[str, Any]] = []
    for path in host_checkpoint_root.rglob("checkpoint.img"):
        relative = path.relative_to(host_checkpoint_root).as_posix()
        if instance_id and instance_id not in relative:
            continue
        images.append(
            {
                "path": str(path),
                "relativePath": relative,
                "size": path.stat().st_size,
            }
        )
    return sorted(images, key=lambda item: item["relativePath"])


def _assert_checkpoint_views_agree(views: dict[str, list[dict[str, Any]]]) -> None:
    def facts(name: str) -> set[tuple[str, int]]:
        return {
            (str(item["relativePath"]), int(item["size"]))
            for item in views[name]
        }

    container_facts = facts("container")
    host_facts = facts("host")
    if container_facts != host_facts:
        raise AssertionError(
            "checkpoint bind-mount views disagree: "
            f"container={sorted(container_facts)!r} host={sorted(host_facts)!r}"
        )


def _checkpoint_views(
    node_container: str, host_checkpoint_root: Path, instance_id: str = ""
) -> dict[str, list[dict[str, Any]]]:
    views = {
        "container": _container_checkpoint_images(node_container, instance_id),
        "host": _host_checkpoint_images(host_checkpoint_root, instance_id),
    }
    _assert_checkpoint_views_agree(views)
    return views


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "count": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "p95": _percentile(values, 0.95),
        "max": max(values),
        "mean": statistics.fmean(values),
    }


def _performance_summary(single: dict[str, Any], interleaved: dict[str, Any]) -> dict[str, Any]:
    cycles = single["cycles"]
    actions = interleaved["actions"]
    return {
        "singleLoop": {
            name: _summary([float(cycle[name]) for cycle in cycles])
            for name in (
                "pauseSeconds",
                "resumeSeconds",
                "firstFileSeconds",
                "firstExecSeconds",
                "firstPublicSeconds",
            )
        },
        "interleavedPause": _summary(
            [float(action["pauseSeconds"]) for action in actions if "pauseSeconds" in action]
        ),
        "interleavedResume": _summary(
            [float(action["resumeSeconds"]) for action in actions if "resumeSeconds" in action]
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
