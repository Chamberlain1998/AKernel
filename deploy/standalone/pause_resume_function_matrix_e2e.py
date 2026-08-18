#!/usr/bin/env python3
"""Run the standalone RRT pause/resume functional matrix with JSON evidence."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
import traceback
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import pause_resume_e2e as base
import pause_resume_stress_e2e as stress


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--node-container", default="akernel-node")
    parser.add_argument("--cpu", type=int, default=1000)
    parser.add_argument("--memory", type=int, default=4096)
    parser.add_argument("--create-timeout", type=int, default=240)
    parser.add_argument(
        "--host-checkpoint-root",
        type=Path,
        default=Path(__file__).resolve().parent
        / "data"
        / "sandboxd"
        / "root"
        / "checkpoints",
    )
    args = parser.parse_args()
    for name in ("YR_SERVER_ADDRESS", "YR_GATEWAY_ADDRESS", "YR_TOKEN"):
        if not os.environ.get(name, "").strip():
            parser.error(f"{name} is required")

    from yr_sandbox import Sandbox

    started = time.time()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "result": "failed",
        "runtime": "RRT/Rust Runtime",
        "sandboxBackend": "runsc",
        "publicDataPlane": "SandboxRouter",
        "startedAtUnix": int(started),
        "matrix": {
            "sdk-baseline": [],
            "pause-resume-continuity": [],
            "pause-delete-without-resume": [],
        },
    }
    managed: list[Any] = []
    watch_process, watch_stream = base._start_etcd_watch(
        args.node_container, args.evidence_dir / "etcd-watch.jsonl"
    )
    upstream_server, upstream_thread, upstream_url = _start_upstream_server()

    def step(group: str, name: str, operation: Callable[[], Any]) -> Any:
        step_started = time.perf_counter()
        try:
            value = operation()
        except Exception as exc:
            report["matrix"][group].append(
                {
                    "name": name,
                    "result": "failed",
                    "durationSeconds": round(time.perf_counter() - step_started, 6),
                    "errorType": type(exc).__name__,
                    "error": str(exc),
                }
            )
            raise
        report["matrix"][group].append(
            {
                "name": name,
                "result": "passed",
                "durationSeconds": round(time.perf_counter() - step_started, 6),
            }
        )
        print(f"[PASS] {group}: {name}", flush=True)
        return value

    baseline_views = stress._checkpoint_views(
        args.node_container, args.host_checkpoint_root
    )
    stress._assert_checkpoint_views_agree(baseline_views)
    report["checkpointBaseline"] = baseline_views
    report["containerCheckpointImages"] = baseline_views["container"]
    report["hostCheckpointImages"] = baseline_views["host"]
    idle_resources = stress._resource_view(args.node_container)
    capacity = idle_resources["capacity"]
    stress._assert_allocatable(idle_resources, capacity["CPU"], capacity["Memory"])
    report["idleResourceView"] = idle_resources

    primary: Any = None
    primary_deleted = False
    delete_case: Any = None
    delete_case_deleted = False
    primary_public_url = ""
    delete_public_url = ""
    primary_winner_container = ""

    try:
        stamp = int(started)
        primary_port = 18200
        primary_body = "akernel-function-matrix-public-ok"
        primary = step(
            "sdk-baseline",
            "create RRT sandbox",
            lambda: Sandbox(
                name=f"akernel-functional-{stamp}",
                runtime="runsc",
                cpu=args.cpu,
                memory=args.memory,
                create_timeout=args.create_timeout,
                schedule_timeout=180,
                port_forwardings=[primary_port],
                upstream=upstream_url,
            ),
        )
        managed.append(primary)
        report["primarySandboxId"] = primary.id
        step(
            "sdk-baseline",
            "sandbox get_info and is_running",
            lambda: _assert_sandbox_running(primary),
        )
        running_resources, running_convergence = stress._await_resources(
            args.node_container,
            capacity["CPU"] - args.cpu,
            capacity["Memory"] - args.memory,
        )
        report["primaryRunningResourceView"] = running_resources
        report["primaryRunningResourceConvergenceSeconds"] = running_convergence

        step(
            "sdk-baseline",
            "foreground command stdout stderr exit",
            lambda: _assert_foreground_command(primary),
        )
        step(
            "sdk-baseline",
            "command environment and working directory",
            lambda: _assert_command_environment_and_cwd(primary),
        )
        step(
            "sdk-baseline",
            "background process list and kill",
            lambda: _assert_background_process(primary),
        )
        step(
            "sdk-baseline",
            "filesystem text binary metadata rename copy remove",
            lambda: _assert_filesystem_matrix(primary),
        )
        step(
            "sdk-baseline",
            "PTY input resize and independent sessions",
            lambda: _assert_pty_matrix(primary),
        )
        step(
            "sdk-baseline",
            "reverse tunnel request",
            lambda: _assert_command_stdout(
                primary.commands.run(f"curl -fsS {primary.get_tunnel_url()}"),
                _UpstreamHandler.response_body.decode(),
            ),
        )

        marker_path = "/tmp/akernel-functional-marker"
        marker_value = "functional-continuity"
        binary_path = "/tmp/akernel-functional-binary"
        binary_value = bytes(range(256)) * 4
        primary.files.write(marker_path, marker_value)
        primary.files.write(binary_path, binary_value)
        stdin_handle = primary.commands.run(
            "read value; printf 'continued:%s' \"$value\"",
            background=True,
            stdin=True,
        )
        memory_handle, memory_before = step(
            "sdk-baseline",
            "start and mutate 32 MiB anonymous memory workload",
            lambda: _start_memory_state_process(primary),
        )
        report["primaryMemoryBeforePause"] = memory_before
        _start_public_server(primary, primary_port, primary_body)
        primary_public_url = primary.get_port_url(primary_port)
        step(
            "sdk-baseline",
            "SandboxRouter public port before pause converges",
            lambda: base._fetch_public_eventually(primary_public_url, primary_body),
        )
        source = base._capture_authority(
            args.node_container,
            primary.id,
            "functional-source-running",
            args.evidence_dir,
        )
        base._assert_running_authority(source)
        source_instance = source["instance"]["value"]
        source_container = source_instance["containerID"]
        report["primarySource"] = {
            "containerId": source_container,
            "runtimeId": source_instance["runtimeID"],
            "functionProxyId": source_instance["functionProxyID"],
            "portMappings": base._port_mappings_from_instance(source_instance),
        }

        pause_result = step(
            "pause-resume-continuity",
            "pause sandbox",
            lambda: primary.pause(ttl_seconds=1800),
        )
        report["primaryPause"] = asdict(pause_result)
        paused = base._capture_authority(
            args.node_container,
            primary.id,
            "functional-paused",
            args.evidence_dir,
        )
        step(
            "pause-resume-continuity",
            "PAUSED authority owner snapshot route and cleared identity",
            lambda: base._assert_paused_authority(
                paused, pause_result.snapshot_id, source_instance
            ),
        )
        step(
            "pause-resume-continuity",
            "source sandboxd physical fact released",
            lambda: base._assert_equal(
                base._inspect_sandboxd(
                    args.node_container,
                    source_container,
                    args.evidence_dir / "sandboxd-functional-source-after-pause.json",
                ),
                None,
            ),
        )
        paused_resources, paused_resource_convergence = stress._await_resources(
            args.node_container, capacity["CPU"], capacity["Memory"]
        )
        report["primaryPausedResourceView"] = paused_resources
        report["primaryPausedResourceConvergenceSeconds"] = paused_resource_convergence
        paused_views = stress._checkpoint_views(
            args.node_container, args.host_checkpoint_root, primary.id
        )
        report["primaryCheckpointWhilePaused"] = paused_views
        step(
            "pause-resume-continuity",
            "PAUSED data plane rejects file exec PTY and public port",
            lambda: _assert_paused_data_plane(primary, primary_public_url),
        )

        resume_result = step(
            "pause-resume-continuity", "resume sandbox", primary.resume
        )
        report["primaryResume"] = asdict(resume_result)
        immediate = step(
            "pause-resume-continuity",
            "first file exec PTY and public requests after resume",
            lambda: _assert_first_requests_after_resume(
                primary,
                marker_path,
                marker_value,
                primary_public_url,
                primary_body,
            ),
        )
        report["firstRequestsAfterResumeSeconds"] = immediate
        step(
            "pause-resume-continuity",
            "binary file continuity",
            lambda: base._assert_equal(
                primary.files.read(binary_path, format="bytes"), binary_value
            ),
        )
        step(
            "pause-resume-continuity",
            "reverse tunnel after resume",
            lambda: _assert_command_stdout(
                primary.commands.run(f"curl -fsS {primary.get_tunnel_url()}"),
                _UpstreamHandler.response_body.decode(),
            ),
        )
        step(
            "pause-resume-continuity",
            "stdin-blocked process continuity",
            lambda: _complete_stdin_process(stdin_handle),
        )
        memory_after = step(
            "pause-resume-continuity",
            "anonymous memory PID counter checksum and sentinel continuity",
            lambda: _complete_memory_state_process(
                primary, memory_handle, memory_before
            ),
        )
        report["primaryMemoryAfterResume"] = memory_after
        winner = base._capture_authority(
            args.node_container,
            primary.id,
            "functional-winner-running",
            args.evidence_dir,
        )
        step(
            "pause-resume-continuity",
            "RUNNING winner and exact snapshot cleanup",
            lambda: _assert_winner(
                args.node_container,
                args.evidence_dir,
                winner,
                resume_result,
                pause_result.snapshot_id,
            ),
        )
        winner_instance = winner["instance"]["value"]
        primary_winner_container = winner_instance["containerID"]
        report["primaryWinner"] = {
            "containerId": primary_winner_container,
            "runtimeId": winner_instance["runtimeID"],
            "functionProxyId": winner_instance["functionProxyID"],
            "portMappings": base._port_mappings_from_instance(winner_instance),
            "sourcePortsMayBeReused": True,
        }
        resumed_resources, resumed_resource_convergence = stress._await_resources(
            args.node_container,
            capacity["CPU"] - args.cpu,
            capacity["Memory"] - args.memory,
        )
        report["primaryResumedResourceView"] = resumed_resources
        report["primaryResumedResourceConvergenceSeconds"] = resumed_resource_convergence
        resumed_views = stress._checkpoint_views(
            args.node_container, args.host_checkpoint_root, primary.id
        )
        if resumed_views["container"]:
            raise AssertionError(
                f"checkpoint.img remains after committed resume: {resumed_views!r}"
            )
        report["primaryCheckpointAfterResume"] = resumed_views

        step("pause-resume-continuity", "delete resumed sandbox", primary.kill)
        managed.remove(primary)
        primary_deleted = True
        step(
            "pause-resume-continuity",
            "resumed sandbox ETCD sandboxd and public route cleanup",
            lambda: _assert_deleted(
                args,
                primary.id,
                primary_winner_container,
                primary_public_url,
                "primary-after-delete",
            ),
        )
        stress._await_resources(
            args.node_container, capacity["CPU"], capacity["Memory"]
        )

        delete_port = 18201
        delete_body = "akernel-pause-delete-public-ok"
        delete_case = step(
            "pause-delete-without-resume",
            "create delete-case RRT sandbox",
            lambda: Sandbox(
                name=f"akernel-pause-delete-{stamp}",
                runtime="runsc",
                cpu=args.cpu,
                memory=args.memory,
                create_timeout=args.create_timeout,
                schedule_timeout=180,
                port_forwardings=[delete_port],
            ),
        )
        managed.append(delete_case)
        _start_public_server(delete_case, delete_port, delete_body)
        delete_public_url = delete_case.get_port_url(delete_port)
        base._fetch_public_eventually(delete_public_url, delete_body)
        delete_source = base._capture_authority(
            args.node_container,
            delete_case.id,
            "pause-delete-source-running",
            args.evidence_dir,
        )
        base._assert_running_authority(delete_source)
        delete_source_instance = delete_source["instance"]["value"]
        delete_source_container = delete_source_instance["containerID"]
        delete_pause = step(
            "pause-delete-without-resume",
            "pause delete-case sandbox",
            lambda: delete_case.pause(ttl_seconds=1800),
        )
        report["pauseDeletePause"] = asdict(delete_pause)
        delete_paused = base._capture_authority(
            args.node_container,
            delete_case.id,
            "pause-delete-paused",
            args.evidence_dir,
        )
        step(
            "pause-delete-without-resume",
            "verify delete-case PAUSED authority",
            lambda: base._assert_paused_authority(
                delete_paused, delete_pause.snapshot_id, delete_source_instance
            ),
        )
        report["pauseDeleteCheckpointWhilePaused"] = stress._checkpoint_views(
            args.node_container, args.host_checkpoint_root, delete_case.id
        )
        step(
            "pause-delete-without-resume",
            "delete directly from PAUSED",
            delete_case.kill,
        )
        managed.remove(delete_case)
        delete_case_deleted = True
        step(
            "pause-delete-without-resume",
            "PAUSED delete cleans ETCD sandboxd route snapshot and checkpoint",
            lambda: _assert_deleted(
                args,
                delete_case.id,
                delete_source_container,
                delete_public_url,
                "pause-delete-after-delete",
            ),
        )
        final_resources, final_resource_convergence = stress._await_resources(
            args.node_container, capacity["CPU"], capacity["Memory"]
        )
        report["finalResourceView"] = final_resources
        report["finalResourceViewConvergenceSeconds"] = final_resource_convergence
        final_views = stress._checkpoint_views(
            args.node_container, args.host_checkpoint_root
        )
        stress._assert_checkpoint_views_agree(final_views)
        report["checkpointFinal"] = final_views
        report["containerCheckpointImages"] = final_views["container"]
        report["hostCheckpointImages"] = final_views["host"]
        _assert_no_new_checkpoint_images(baseline_views, final_views)
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
        if primary is not None and not primary_deleted:
            report["primaryCleanupAttempted"] = True
        if delete_case is not None and not delete_case_deleted:
            report["pauseDeleteCleanupAttempted"] = True
        upstream_server.shutdown()
        upstream_server.server_close()
        upstream_thread.join(timeout=5)
        base._stop_etcd_watch(watch_process, watch_stream)
        report["finishedAtUnix"] = int(time.time())
        report["durationSeconds"] = round(time.time() - started, 6)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    if report["result"] != "passed":
        print(json.dumps({"result": "failed", "error": report.get("error")}), flush=True)
        return 1
    print(json.dumps({"result": "passed", "report": str(args.report)}), flush=True)
    return 0


class _UpstreamHandler(BaseHTTPRequestHandler):
    response_body = b"akernel-reverse-tunnel-ok"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.response_body)))
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def _start_upstream_server() -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address, port = server.server_address
    return server, thread, f"http://{address}:{port}"


def _assert_command_stdout(result: Any, expected: str) -> None:
    if result.exit_code != 0 or result.stdout != expected:
        raise AssertionError(
            f"expected rc=0 stdout={expected!r}, got "
            f"rc={result.exit_code} stdout={result.stdout!r} stderr={result.stderr!r}"
        )


def _assert_sandbox_running(sandbox: Any) -> None:
    info = sandbox.get_info()
    if info.state != "running" or not sandbox.is_running():
        raise AssertionError(f"sandbox is not running: {info!r}")


def _assert_foreground_command(sandbox: Any) -> None:
    result = sandbox.commands.run("printf stdout-ok; printf stderr-ok >&2; exit 7")
    if result.exit_code != 7 or result.stdout != "stdout-ok" or result.stderr != "stderr-ok":
        raise AssertionError(f"foreground command result mismatch: {result!r}")


def _assert_command_environment_and_cwd(sandbox: Any) -> None:
    sandbox.files.make_dir("/tmp/akernel-functional-cwd")
    result = sandbox.commands.run(
        "printf '%s:%s' \"$FUNCTION_MATRIX_ENV\" \"$PWD\"",
        envs={"FUNCTION_MATRIX_ENV": "env-ok"},
        cwd="/tmp/akernel-functional-cwd",
    )
    _assert_command_stdout(result, "env-ok:/tmp/akernel-functional-cwd")


def _assert_background_process(sandbox: Any) -> None:
    handle = sandbox.commands.run("sleep 300", background=True)
    processes = sandbox.commands.list()
    match = next((item for item in processes if item.pid == handle.pid), None)
    if match is None or not match.running or "sleep 300" not in match.command:
        raise AssertionError(f"background process missing from list: {processes!r}")
    if not handle.kill():
        raise AssertionError("background process kill returned false")


def _assert_filesystem_matrix(sandbox: Any) -> None:
    root = "/tmp/akernel-functional-files"
    sandbox.files.make_dir(root)
    text_path = f"{root}/text.txt"
    binary_path = f"{root}/binary.bin"
    binary = bytes(range(256)) * 8
    sandbox.files.write(text_path, "text-ok")
    sandbox.files.write(binary_path, binary)
    base._assert_equal(sandbox.files.read(text_path), "text-ok")
    base._assert_equal(sandbox.files.read(binary_path, format="bytes"), binary)
    if not sandbox.files.exists(text_path):
        raise AssertionError("written text file does not exist")
    info = sandbox.files.get_info(binary_path)
    if info.type != "file" or info.size != len(binary):
        raise AssertionError(f"binary metadata mismatch: {info!r}")
    entries = sandbox.files.list(root, depth=2)
    if {entry.name for entry in entries}.isdisjoint({"text.txt", "binary.bin"}):
        raise AssertionError(f"filesystem list omitted files: {entries!r}")
    renamed_path = f"{root}/renamed.txt"
    sandbox.files.rename(text_path, renamed_path)
    if sandbox.files.exists(text_path) or not sandbox.files.exists(renamed_path):
        raise AssertionError("filesystem rename did not update existence")

    with tempfile.TemporaryDirectory() as temporary:
        local_root = Path(temporary)
        upload = local_root / "upload.bin"
        upload.write_bytes(b"copy-from-local\x00ok")
        remote_upload = f"{root}/upload.bin"
        sandbox.files.copy_from_local(str(upload), remote_upload)
        base._assert_equal(
            sandbox.files.read(remote_upload, format="bytes"), upload.read_bytes()
        )
        download = local_root / "download.bin"
        sandbox.files.copy_to_local(remote_upload, str(download))
        base._assert_equal(download.read_bytes(), upload.read_bytes())

        directory = local_root / "tree"
        directory.mkdir()
        (directory / "nested.txt").write_text("directory-copy-ok")
        remote_directory = f"{root}/tree"
        sandbox.files.copy_from_local(str(directory), remote_directory)
        base._assert_equal(
            sandbox.files.read(f"{remote_directory}/nested.txt"),
            "directory-copy-ok",
        )
        downloaded_directory = local_root / "downloaded-tree"
        sandbox.files.copy_to_local(remote_directory, str(downloaded_directory))
        base._assert_equal(
            (downloaded_directory / "nested.txt").read_text(),
            "directory-copy-ok",
        )

    sandbox.files.remove(renamed_path)
    if sandbox.files.exists(renamed_path):
        raise AssertionError("filesystem remove left the renamed file")


def _run_pty(sandbox: Any, marker: bytes, exit_code: int) -> bytes:
    output = bytearray()
    with sandbox.pty.create(on_data=output.extend) as session:
        session.resize(rows=41, cols=121)
        session.send_stdin(b"printf '" + marker + b"\\n'\n")
        session.send_stdin(f"exit {exit_code}\n".encode())
        observed = session.wait(timeout=30)
        if observed != exit_code:
            raise AssertionError(f"PTY exit mismatch: expected {exit_code}, got {observed}")
    if marker not in output:
        raise AssertionError(f"PTY output omitted {marker!r}: {bytes(output)!r}")
    return bytes(output)


def _assert_pty_matrix(sandbox: Any) -> None:
    _run_pty(sandbox, b"PTY_BASELINE", 3)
    first_output = bytearray()
    second_output = bytearray()
    with (
        sandbox.pty.create(on_data=first_output.extend) as first,
        sandbox.pty.create(on_data=second_output.extend) as second,
    ):
        first.send_stdin(b"printf 'PTY_FIRST\\n'\nexit 4\n")
        second.send_stdin(b"printf 'PTY_SECOND\\n'\nexit 5\n")
        if first.wait(timeout=30) != 4 or second.wait(timeout=30) != 5:
            raise AssertionError("independent PTY exit codes mismatch")
    if b"PTY_FIRST" not in first_output or b"PTY_SECOND" in first_output:
        raise AssertionError(f"first PTY output leaked: {bytes(first_output)!r}")
    if b"PTY_SECOND" not in second_output or b"PTY_FIRST" in second_output:
        raise AssertionError(f"second PTY output leaked: {bytes(second_output)!r}")


def _start_public_server(sandbox: Any, port: int, body: str) -> None:
    ready = f"/tmp/akernel-functional-public-{port}.ready"
    command = rf'''perl -MSocket -e '$|=1; socket(S,PF_INET,SOCK_STREAM,getprotobyname("tcp")); setsockopt(S,SOL_SOCKET,SO_REUSEADDR,1); bind(S,sockaddr_in({port},INADDR_ANY)) or die $!; listen(S,10); open(F, ">", "{ready}") or die $!; print F "ready"; close F; while(accept(C,S)){{ print C "HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n{body}"; close C; }}' '''
    sandbox.commands.run(command, background=True)
    result = sandbox.commands.run(
        f"while [ ! -f {ready} ]; do sleep 0.05; done; printf ready"
    )
    _assert_command_stdout(result, "ready")


def _assert_paused_error(operation: Callable[[], Any], name: str) -> None:
    try:
        operation()
    except Exception as exc:
        message = str(exc).lower()
        if "paused" in message or "409" in message:
            return
        raise AssertionError(f"{name} did not return PAUSED: {type(exc).__name__}: {exc}") from exc
    raise AssertionError(f"{name} unexpectedly succeeded while PAUSED")


def _assert_paused_data_plane(sandbox: Any, public_url: str) -> None:
    _assert_paused_error(lambda: sandbox.files.read("/tmp/akernel-functional-marker"), "file")
    _assert_paused_error(lambda: sandbox.commands.run("printf forbidden"), "exec")
    _assert_paused_error(
        lambda: sandbox.pty.create(command=["/bin/sh", "-c", "exit 0"], timeout=10),
        "PTY",
    )
    base._assert_public_paused_unavailable_once(public_url)


def _timed(operation: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    value = operation()
    return value, round(time.perf_counter() - started, 6)


def _assert_first_requests_after_resume(
    sandbox: Any,
    marker_path: str,
    marker_value: str,
    public_url: str,
    public_body: str,
) -> dict[str, float]:
    marker, file_seconds = _timed(lambda: sandbox.files.read(marker_path))
    base._assert_equal(marker, marker_value)
    command, exec_seconds = _timed(lambda: sandbox.commands.run("printf immediate-exec-ok"))
    _assert_command_stdout(command, "immediate-exec-ok")
    _, pty_seconds = _timed(lambda: _run_pty(sandbox, b"PTY_AFTER_RESUME", 6))
    public_result = base._fetch_public_eventually(public_url, public_body)
    public_seconds = float(public_result["durationSeconds"])
    return {
        "file": file_seconds,
        "exec": exec_seconds,
        "pty": pty_seconds,
        "public": public_seconds,
    }


def _complete_stdin_process(handle: Any) -> None:
    handle.send_stdin("matrix\n", eof=True)
    _assert_command_stdout(handle.wait(timeout=90), "continued:matrix")


_MEMORY_STATE_SCRIPT = r'''#!/usr/bin/perl
use strict;
use warnings;

my $state_file = "/tmp/akernel-memory-state.tsv";
my $ready_file = "/tmp/akernel-memory-state.ready";
my $bytes = 32 * 1024 * 1024;
my $offset = 17 * 1024 * 1024 + 19;
my $blob = "0123456789abcdef" x ($bytes / 16);
my $counter = 41;
my $sequence = 0;

sub publish_state {
    my $temporary = "$state_file.tmp";
    open(my $output, ">", $temporary) or die "open state: $!";
    my $checksum = unpack("%32C*", $blob);
    my $sentinel = ord(substr($blob, $offset, 1));
    print $output join("\t", $sequence, $$, $counter, length($blob), $checksum, $sentinel), "\n";
    close($output) or die "close state: $!";
    rename($temporary, $state_file) or die "rename state: $!";
}

open(my $ready, ">", $ready_file) or die "open ready: $!";
print $ready "ready\n";
close($ready) or die "close ready: $!";

while (my $line = <STDIN>) {
    chomp($line);
    last if $line eq "quit";
    if ($line eq "mutate") {
        $counter += 1;
        substr($blob, $offset, 1) = chr(90);
    } elsif ($line ne "report") {
        die "unknown command: $line";
    }
    $sequence += 1;
    publish_state();
}
'''


def _parse_memory_state(payload: str) -> dict[str, int]:
    fields = payload.strip().split("\t")
    if len(fields) != 6:
        raise AssertionError(f"invalid memory state payload: {payload!r}")
    values = [int(field) for field in fields]
    return {
        "sequence": values[0],
        "pid": values[1],
        "counter": values[2],
        "length": values[3],
        "checksum": values[4],
        "sentinelByte": values[5],
    }


def _await_memory_state(sandbox: Any, sequence: int) -> dict[str, int]:
    state_path = "/tmp/akernel-memory-state.tsv"
    command = sandbox.commands.run(
        "i=0; "
        f"while [ ! -f {state_path} ] || "
        f"[ \"$(cut -f1 {state_path} 2>/dev/null)\" != \"{sequence}\" ]; do "
        "i=$((i + 1)); [ \"$i\" -ge 600 ] && exit 124; sleep 0.05; done; "
        "printf ready"
    )
    _assert_command_stdout(command, "ready")
    return _parse_memory_state(sandbox.files.read(state_path))


def _start_memory_state_process(sandbox: Any) -> tuple[Any, dict[str, int]]:
    script_path = "/tmp/akernel-memory-state.pl"
    sandbox.files.write(script_path, _MEMORY_STATE_SCRIPT)
    handle = sandbox.commands.run(
        f"perl {script_path}", background=True, stdin=True
    )
    ready = sandbox.commands.run(
        "i=0; while [ ! -f /tmp/akernel-memory-state.ready ]; do "
        "i=$((i + 1)); [ \"$i\" -ge 600 ] && exit 124; sleep 0.05; done; printf ready"
    )
    _assert_command_stdout(ready, "ready")
    handle.send_stdin("mutate\n")
    state = _await_memory_state(sandbox, 1)
    expected = {
        "sequence": 1,
        "counter": 42,
        "length": 32 * 1024 * 1024,
        "sentinelByte": 90,
    }
    for key, value in expected.items():
        if state[key] != value:
            raise AssertionError(
                f"memory workload initialization mismatch for {key}: {state!r}"
            )
    return handle, state


def _assert_memory_state_continuity(
    before: dict[str, int], after: dict[str, int]
) -> None:
    expected_after = {**before, "sequence": before["sequence"] + 1}
    if after != expected_after:
        raise AssertionError(
            "memory process identity/state changed across resume: "
            f"before={before!r} after={after!r}"
        )


def _complete_memory_state_process(
    sandbox: Any, handle: Any, before: dict[str, int]
) -> dict[str, int]:
    handle.send_stdin("report\n")
    after = _await_memory_state(sandbox, before["sequence"] + 1)
    _assert_memory_state_continuity(before, after)
    handle.send_stdin("quit\n", eof=True)
    _assert_command_stdout(handle.wait(timeout=90), "")
    return after


def _assert_winner(
    node_container: str,
    evidence_dir: Path,
    winner: dict[str, Any],
    resume_result: Any,
    snapshot_id: str,
) -> None:
    base._assert_running_authority(winner)
    base._assert_snapshot_cleaned(winner, snapshot_id)
    instance = winner["instance"]["value"]
    mappings = base._port_mappings_from_instance(instance)
    base._assert_equal(base._normalize_port_mappings(resume_result.port_mappings), mappings)
    physical = base._inspect_sandboxd(
        node_container,
        instance["containerID"],
        evidence_dir / "sandboxd-functional-winner-running.json",
    )
    if physical is None:
        raise AssertionError("sandboxd has no winner physical fact")
    base._assert_equal(base._port_mappings_from_sandboxd(physical), mappings)


def _assert_deleted(
    args: argparse.Namespace,
    sandbox_id: str,
    physical_id: str,
    public_url: str,
    phase: str,
) -> None:
    cleanup_dir = args.evidence_dir / phase
    cleanup_dir.mkdir(parents=True, exist_ok=True)
    base._verify_cleanup(
        args.node_container,
        sandbox_id,
        physical_id,
        cleanup_dir,
    )
    base._assert_public_missing_eventually(public_url)
    views = stress._checkpoint_views(
        args.node_container, args.host_checkpoint_root, sandbox_id
    )
    if views["container"]:
        raise AssertionError(f"deleted sandbox retains checkpoint.img: {views!r}")


def _assert_no_new_checkpoint_images(
    baseline: dict[str, list[dict[str, Any]]],
    final: dict[str, list[dict[str, Any]]],
) -> None:
    def facts(views: dict[str, list[dict[str, Any]]]) -> set[tuple[str, int]]:
        return {
            (str(item["relativePath"]), int(item["size"]))
            for item in views["container"]
        }

    new_facts = facts(final) - facts(baseline)
    if new_facts:
        raise AssertionError(f"new checkpoint.img files remain: {sorted(new_facts)!r}")


if __name__ == "__main__":
    raise SystemExit(main())
