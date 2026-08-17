#!/usr/bin/env python3
"""Run the standalone RRT pause/resume acceptance test and write JSON evidence."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--node-container", default="akernel-node")
    parser.add_argument("--memory", type=int, default=4096)
    parser.add_argument("--create-timeout", type=int, default=240)
    parser.add_argument("--proxy-restart-timeout", type=int, default=180)
    args = parser.parse_args()

    for name in ("YR_SERVER_ADDRESS", "YR_GATEWAY_ADDRESS", "YR_TOKEN"):
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
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    report["evidenceDirectory"] = str(args.evidence_dir)
    report["nodeContainer"] = args.node_container
    sandbox: Any = None
    deleted = False
    public_url = ""
    watch_process, watch_stream = _start_etcd_watch(
        args.node_container, args.evidence_dir / "etcd-watch.jsonl"
    )

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
    public_port = 18080
    public_body = "akernel-sandboxrouter-resume-ok"
    public_ready = "/tmp/akernel-public-http-ready"
    public_server = rf'''perl -MSocket -e '$|=1; socket(S,PF_INET,SOCK_STREAM,getprotobyname("tcp")); setsockopt(S,SOL_SOCKET,SO_REUSEADDR,1); bind(S,sockaddr_in({public_port},INADDR_ANY)) or die $!; listen(S,10); open(F, ">", "{public_ready}") or die $!; print F "ready"; close F; while(accept(C,S)){{ print C "HTTP/1.1 200 OK\r\nContent-Length: {len(public_body)}\r\nConnection: close\r\n\r\n{public_body}"; close C; }}' '''
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
                port_forwardings=[public_port],
            ),
        )
        report["sandboxId"] = sandbox.id
        report["runtime"] = "RRT/Rust Runtime"
        report["sandboxBackend"] = "runsc"
        report["gatewayAddress"] = os.environ["YR_GATEWAY_ADDRESS"]

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
        step(
            "start public HTTP server",
            lambda: sandbox.commands.run(public_server, background=True),
        )
        step(
            "observe public HTTP process readiness",
            lambda: _assert_command(
                sandbox.commands.run(
                    f"while [ ! -f {public_ready} ]; do sleep 0.05; done; printf ready"
                ),
                "ready",
            ),
        )
        public_url = sandbox.get_port_url(public_port)
        report["publicPort"] = public_port
        report["publicURL"] = public_url
        step(
            "public HTTP before pause uses SandboxRouter",
            lambda: _assert_equal(_fetch_public_once(public_url), public_body),
        )
        source_authority = step(
            "capture RUNNING source authority",
            lambda: _capture_authority(
                args.node_container, sandbox.id, "source-running", args.evidence_dir
            ),
        )
        step(
            "verify source RUNNING ETCD authority",
            lambda: _assert_running_authority(source_authority),
        )
        source_instance = source_authority["instance"]["value"]
        source_runtime_id = source_instance["runtimeID"]
        source_container_id = source_instance["containerID"]
        source_mappings = _port_mappings_from_instance(source_instance)
        report["source"] = {
            "runtimeId": source_runtime_id,
            "containerId": source_container_id,
            "functionProxyId": source_instance["functionProxyID"],
            "portMappings": source_mappings,
        }
        source_inspect = step(
            "capture source sandboxd physical fact",
            lambda: _inspect_sandboxd(
                args.node_container,
                source_container_id,
                args.evidence_dir / "sandboxd-source-running.json",
            ),
        )
        step(
            "verify source mappings match sandboxd physical fact",
            lambda: _assert_equal(
                _port_mappings_from_sandboxd(source_inspect), source_mappings
            ),
        )
        source_proxy_pid = _function_proxy_pid(args.node_container)
        source_registration_count = _function_proxy_registration_count(args.node_container)
        report["source"]["functionProxyPid"] = source_proxy_pid
        report["source"]["registrationCount"] = source_registration_count

        pause_result = step("pause sandbox", lambda: sandbox.pause(ttl_seconds=1800))
        report["pause"] = asdict(pause_result)
        report["snapshotId"] = pause_result.snapshot_id
        step(
            "observe paused state",
            lambda: _assert_equal(sandbox.get_info().state, "paused"),
        )
        paused_authority = step(
            "capture PAUSED authority",
            lambda: _capture_authority(
                args.node_container, sandbox.id, "paused", args.evidence_dir
            ),
        )
        step(
            "verify PAUSED ETCD authority",
            lambda: _assert_paused_authority(
                paused_authority, pause_result.snapshot_id, source_instance
            ),
        )
        released_source = step(
            "verify source runtime physical fact released",
            lambda: _inspect_sandboxd(
                args.node_container,
                source_container_id,
                args.evidence_dir / "sandboxd-source-after-pause.json",
            ),
        )
        _assert_equal(released_source, None)
        step(
            "SandboxRouter rejects public data while paused",
            lambda: _assert_public_paused_once(public_url),
        )
        target_proxy_pid = step(
            "terminate source FunctionProxy after PAUSED commit",
            lambda: _restart_function_proxy(
                args.node_container,
                source_proxy_pid,
                source_registration_count,
                args.proxy_restart_timeout,
            ),
        )
        report["sourceProxyExit"] = {
            "sourcePid": source_proxy_pid,
            "targetPid": target_proxy_pid,
            "proven": target_proxy_pid != source_proxy_pid,
        }

        resume_result = step("resume sandbox", sandbox.resume)
        report["resume"] = asdict(resume_result)
        if str(public_port) not in resume_result.port_mappings:
            raise AssertionError(
                "resume result is missing the public port mapping for "
                f"container port {public_port}: {resume_result.port_mappings!r}"
            )
        step(
            "observe running state",
            lambda: _assert_equal(sandbox.get_info().state, "running"),
        )
        step(
            "first file request after resume",
            lambda: _assert_equal(sandbox.files.read(marker_path), marker_value),
        )
        step(
            "first exec request after resume",
            lambda: _assert_command(sandbox.commands.run("printf post-resume-ok"), "post-resume-ok"),
        )
        step(
            "first public request after resume uses SandboxRouter",
            lambda: _assert_equal(_fetch_public_once(public_url), public_body),
        )
        winner_authority = step(
            "capture RUNNING winner authority",
            lambda: _capture_authority(
                args.node_container, sandbox.id, "winner-running", args.evidence_dir
            ),
        )
        step(
            "verify RUNNING winner ETCD authority",
            lambda: _assert_running_authority(winner_authority),
        )
        winner_instance = winner_authority["instance"]["value"]
        winner_mappings = _port_mappings_from_instance(winner_instance)
        step(
            "verify resume mappings match ETCD winner",
            lambda: _assert_equal(
                _normalize_port_mappings(resume_result.port_mappings), winner_mappings
            ),
        )
        winner_runtime_id = winner_instance["runtimeID"]
        winner_container_id = winner_instance["containerID"]
        winner_inspect = step(
            "verify sandboxd physical fact after resume",
            lambda: _inspect_sandboxd(
                args.node_container,
                winner_container_id,
                args.evidence_dir / "sandboxd-winner-running.json",
            ),
        )
        if winner_inspect is None:
            raise AssertionError("sandboxd has no exact winner sandbox after resume")
        _assert_equal(_port_mappings_from_sandboxd(winner_inspect), winner_mappings)
        report["winner"] = {
            "runtimeId": winner_runtime_id,
            "containerId": winner_container_id,
            "functionProxyId": winner_instance["functionProxyID"],
            "functionProxyPid": target_proxy_pid,
            "portMappings": winner_mappings,
            "sourcePortsMayBeReused": True,
        }
        step(
            "verify exact snapshot cleanup",
            lambda: _assert_snapshot_cleaned(winner_authority, pause_result.snapshot_id),
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
        step("delete sandbox", sandbox.kill)
        deleted = True
        cleanup_authority = step(
            "verify ETCD and sandboxd cleanup",
            lambda: _verify_cleanup(
                args.node_container,
                sandbox.id,
                winner_container_id,
                args.evidence_dir,
            ),
        )
        report["cleanupAuthority"] = cleanup_authority
        step(
            "SandboxRouter returns missing after delete",
            lambda: _assert_public_missing_once(public_url),
        )
        report["cleanup"] = "passed"
        report["result"] = "passed"
    except Exception as exc:
        report["errorType"] = type(exc).__name__
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
    finally:
        if sandbox is not None and not deleted:
            try:
                sandbox.kill()
                report["cleanup"] = "passed"
            except Exception as exc:
                report["cleanup"] = "failed"
                report["cleanupError"] = f"{type(exc).__name__}: {exc}"
                report["result"] = "failed"
        _stop_etcd_watch(watch_process, watch_stream)
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


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, text=True, capture_output=True)
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
        )
    return completed


def _docker_exec(node_container: str, *command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["docker", "exec", node_container, *command], check=check)


def _node_ip(node_container: str) -> str:
    result = _run(
        [
            "docker",
            "inspect",
            "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            node_container,
        ]
    )
    address = result.stdout.strip()
    if not address:
        raise RuntimeError(f"container {node_container} has no bridge address")
    return address


def _etcdctl_command(node_container: str, *arguments: str) -> list[str]:
    endpoint = f"http://{_node_ip(node_container)}:2379"
    return [
        "docker",
        "exec",
        "-e",
        "ETCDCTL_API=3",
        node_container,
        "/home/yuanrong/third_party/etcd/etcdctl",
        f"--endpoints={endpoint}",
        *arguments,
    ]


def _start_etcd_watch(
    node_container: str, evidence_path: Path
) -> tuple[subprocess.Popen[bytes], Any]:
    stream = evidence_path.open("wb")
    process = subprocess.Popen(
        _etcdctl_command(node_container, "watch", "/", "--prefix", "--write-out=json"),
        stdout=stream,
        stderr=subprocess.STDOUT,
    )
    return process, stream


def _stop_etcd_watch(process: subprocess.Popen[bytes], stream: Any) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    stream.close()


def _decode_etcd_records(raw: str) -> list[dict[str, Any]]:
    payload = json.loads(raw)
    records: list[dict[str, Any]] = []
    for item in payload.get("kvs", []):
        key = base64.b64decode(item["key"]).decode(errors="replace")
        value_text = base64.b64decode(item["value"]).decode(errors="replace")
        try:
            value: Any = json.loads(value_text)
        except json.JSONDecodeError:
            value = value_text
        records.append(
            {
                "key": key,
                "value": value,
                "createRevision": item.get("create_revision"),
                "modRevision": item.get("mod_revision"),
                "version": item.get("version"),
            }
        )
    return records


def _capture_authority(
    node_container: str, sandbox_id: str, phase: str, evidence_dir: Path
) -> dict[str, Any]:
    completed = _run(
        _etcdctl_command(node_container, "get", "/", "--prefix", "--write-out=json")
    )
    records = _decode_etcd_records(completed.stdout)
    matching = [
        record
        for record in records
        if isinstance(record["value"], dict)
        and record["value"].get("instanceID") == sandbox_id
    ]
    instance = next(
        (record for record in matching if "/sn/instance/" in record["key"]), None
    )
    route = next((record for record in matching if "/yr/route/" in record["key"]), None)
    authority = {
        "phase": phase,
        "sandboxId": sandbox_id,
        "instance": instance,
        "route": route,
        "matchingRecords": matching,
    }
    (evidence_dir / f"etcd-{phase}.json").write_text(
        json.dumps(authority, indent=2, sort_keys=True) + "\n"
    )
    return authority


def _state_code(record: dict[str, Any]) -> int:
    return int(record.get("instanceStatus", {}).get("code", 0))


def _assert_running_authority(authority: dict[str, Any]) -> None:
    if authority["instance"] is None or authority["route"] is None:
        raise AssertionError(f"RUNNING authority is incomplete: {authority!r}")
    instance = authority["instance"]["value"]
    route = authority["route"]["value"]
    if _state_code(instance) != 3 or _state_code(route) != 3:
        raise AssertionError(f"expected RUNNING(3), got instance={instance!r} route={route!r}")
    owner = instance.get("functionProxyID", "")
    if not owner or owner == "InstanceManagerOwner" or route.get("functionProxyID") != owner:
        raise AssertionError(f"RUNNING owner/route mismatch: instance={instance!r} route={route!r}")
    for field in ("runtimeID", "functionAgentID", "containerID", "proxyGrpcAddress"):
        if not instance.get(field):
            raise AssertionError(f"RUNNING winner is missing {field}: {instance!r}")
    if route.get("proxyGrpcAddress") != instance.get("proxyGrpcAddress"):
        raise AssertionError("RUNNING route does not publish the winner proxyGrpcAddress")
    if not _port_mappings_from_instance(instance):
        raise AssertionError("RUNNING authority has no target portForward mapping")


def _assert_paused_authority(
    authority: dict[str, Any], snapshot_id: str, source: dict[str, Any]
) -> None:
    if authority["instance"] is None or authority["route"] is None:
        raise AssertionError(f"PAUSED authority is incomplete: {authority!r}")
    instance = authority["instance"]["value"]
    route = authority["route"]["value"]
    if _state_code(instance) != 13 or _state_code(route) != 13:
        raise AssertionError(f"expected PAUSED(13), got instance={instance!r} route={route!r}")
    if instance.get("functionProxyID") != "InstanceManagerOwner":
        raise AssertionError(f"PAUSED instance owner is not InstanceManagerOwner: {instance!r}")
    if route.get("functionProxyID") != "InstanceManagerOwner":
        raise AssertionError(f"PAUSED route owner is not InstanceManagerOwner: {route!r}")
    physical_fields = (
        "runtimeID",
        "runtimeAddress",
        "functionAgentID",
        "containerID",
        "containerIP",
        "unitID",
        "proxyGrpcAddress",
    )
    for record_name, record in (("instance", instance), ("route", route)):
        stale = {field: record.get(field) for field in physical_fields if record.get(field)}
        if stale:
            raise AssertionError(f"PAUSED {record_name} retains physical identity: {stale!r}")
    if "portForward" in instance.get("extensions", {}):
        raise AssertionError("PAUSED instance retains the source portForward extension")
    snapshot = instance.get("snapshotInfo", {})
    if snapshot.get("status") not in (1, "SNAPSHOT_READY"):
        raise AssertionError(f"PAUSED snapshot is not READY: {snapshot!r}")
    if snapshot.get("checkpointID") != snapshot_id:
        raise AssertionError(
            f"PAUSED snapshot id mismatch: expected {snapshot_id!r}, got {snapshot!r}"
        )
    for field in ("checkpointID", "storage", "sha256"):
        if not snapshot.get(field):
            raise AssertionError(f"PAUSED READY SnapshotInfo is missing {field}: {snapshot!r}")
    if int(snapshot.get("size", 0)) <= 0:
        raise AssertionError(f"PAUSED READY SnapshotInfo has no size: {snapshot!r}")
    for field in ("instanceID", "requestID", "tenantID", "function"):
        if instance.get(field) != source.get(field):
            raise AssertionError(f"PAUSED changed logical field {field}")
    if int(instance.get("version", 0)) <= int(source.get("version", 0)):
        raise AssertionError("PAUSED version did not advance through CAS")


def _port_mappings_from_instance(instance: dict[str, Any]) -> dict[str, int]:
    encoded = instance.get("extensions", {}).get("portForward")
    if not encoded:
        return {}
    entries = json.loads(encoded)
    mappings: dict[str, int] = {}
    for entry in entries:
        parts = str(entry).split(":")
        if len(parts) != 3:
            raise AssertionError(f"invalid canonical portForward entry: {entry!r}")
        mappings[str(int(parts[2]))] = int(parts[1])
    return mappings


def _port_mappings_from_sandboxd(sandbox: dict[str, Any] | None) -> dict[str, int]:
    if sandbox is None:
        return {}
    mappings: dict[str, int] = {}
    for entry in sandbox.get("ports", []):
        parts = str(entry).split(":")
        if len(parts) != 3:
            raise AssertionError(f"invalid sandboxd physical port fact: {entry!r}")
        mappings[str(int(parts[2]))] = int(parts[1])
    return mappings


def _normalize_port_mappings(mappings: Any) -> dict[str, int]:
    return {str(int(container)): int(host) for container, host in dict(mappings).items()}


def _inspect_sandboxd(
    node_container: str, runtime_id: str, evidence_path: Path
) -> dict[str, Any] | None:
    completed = _docker_exec(
        node_container, "/usr/local/bin/sbox", "inspect", runtime_id, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"sandboxd inspect failed for {runtime_id}: {completed.stderr or completed.stdout}"
        )
    stdout = completed.stdout.strip()
    if not stdout:
        evidence = {
            "sandboxId": runtime_id,
            "found": False,
            "stderr": completed.stderr.strip(),
        }
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
        return None
    sandbox = json.loads(stdout)
    evidence_path.write_text(json.dumps(sandbox, indent=2, sort_keys=True) + "\n")
    return sandbox


def _function_proxy_pid(node_container: str) -> int:
    result = _docker_exec(node_container, "pidof", "function_proxy", check=False)
    pids = [int(value) for value in result.stdout.split() if value.isdigit()]
    if not pids:
        raise RuntimeError("function_proxy process is not running")
    return min(pids)


def _function_proxy_registration_count(node_container: str) -> int:
    result = _docker_exec(
        node_container,
        "bash",
        "-lc",
        "grep -ah 'succeed to register to local scheduler' "
        "/home/yuanrong/logs/*function_proxy*.log 2>/dev/null | wc -l",
    )
    return int(result.stdout.strip())


def _restart_function_proxy(
    node_container: str, source_pid: int, source_registration_count: int, timeout: int
) -> int:
    _docker_exec(node_container, "kill", "-TERM", str(source_pid))
    deadline = time.monotonic() + timeout
    target_pid = 0
    while time.monotonic() < deadline:
        try:
            observed = _function_proxy_pid(node_container)
        except RuntimeError:
            observed = 0
        if observed and observed != source_pid:
            target_pid = observed
            if _function_proxy_registration_count(node_container) > source_registration_count:
                return target_pid
        time.sleep(0.25)
    raise TimeoutError(
        f"FunctionProxy did not restart and re-register within {timeout}s "
        f"(source={source_pid}, last={target_pid})"
    )


def _assert_snapshot_cleaned(authority: dict[str, Any], snapshot_id: str) -> None:
    instance = authority["instance"]["value"]
    snapshot = instance.get("snapshotInfo", {})
    if snapshot.get("checkpointID") == snapshot_id or snapshot.get("status") in (
        1,
        "SNAPSHOT_READY",
    ):
        raise AssertionError(f"exact READY snapshot was not cleaned after resume: {snapshot!r}")
    for record in authority.get("matchingRecords", []):
        if snapshot_id and snapshot_id in json.dumps(record.get("value", {}), sort_keys=True):
            raise AssertionError(f"snapshot {snapshot_id} remains in ETCD winner state")


def _verify_cleanup(
    node_container: str,
    sandbox_id: str,
    winner_runtime_id: str,
    evidence_dir: Path,
    timeout: int = 60,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = _capture_authority(node_container, sandbox_id, "after-delete", evidence_dir)
        if last["instance"] is None and last["route"] is None:
            physical = _inspect_sandboxd(
                node_container,
                winner_runtime_id,
                evidence_dir / "sandboxd-winner-after-delete.json",
            )
            if physical is None:
                return last
        time.sleep(0.25)
    raise TimeoutError(f"delete cleanup did not converge: {last!r}")


def _fetch_public_once(url: str) -> str:
    """Issue exactly one public request; resume convergence must not need retries."""
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read().decode()


def _assert_public_paused_once(url: str) -> None:
    """Require one authoritative PAUSED response from SandboxRouter."""
    try:
        _fetch_public_once(url)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace").lower()
        if exc.code != 409 or "paused" not in body:
            raise AssertionError(
                f"expected HTTP 409 instance paused, got HTTP {exc.code}: {body!r}"
            ) from exc
        return
    raise AssertionError("expected SandboxRouter to reject the PAUSED sandbox")


def _assert_public_missing_once(url: str) -> None:
    """Require one authoritative missing response after exact cleanup."""
    try:
        _fetch_public_once(url)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            body = exc.read().decode(errors="replace")
            raise AssertionError(f"expected HTTP 404 after delete, got {exc.code}: {body!r}") from exc
        return
    raise AssertionError("expected SandboxRouter route to be absent after delete")


if __name__ == "__main__":
    raise SystemExit(main())
