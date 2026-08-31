# Copyright (c) 2026 Ant Group Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType, SimpleNamespace
from unittest.mock import MagicMock, patch

from akernel_sdk._addresses import Endpoint
from akernel_sdk._backends import (
    openyuanrong_sandbox,
    openyuanrong_sdk,
    registry,
)
from akernel_sdk._backends.base import BackendConfig, SandboxSpec
from akernel_sdk._backends.errors import (
    BackendNotInstalledError,
    BackendOperationError,
    InvalidBackendError,
    UnsupportedBackendFeatureError,
)
from akernel_sdk.commands import Commands as PublicCommands
from akernel_sdk.types import (
    CommandInfo,
    CommandResult,
    EntryInfo,
    HttpReverseTunnel,
    Mount,
    NetworkPolicy,
    S3Config,
)

_COLD_START_HANDLE_ERROR = (
    "pre-reload command handle was not restored after sandbox cold start"
)
_OPERATION_CONFLICT = "another sandbox operation is in flight"


def _blocking_native(result=None, error=None):
    entered = threading.Event()
    release = threading.Event()

    def operation(*_args, **_kwargs):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test did not release native operation")
        if error is not None:
            raise error
        return result

    return operation, entered, release


def _spec(**overrides):
    values = {
        "image": None,
        "rootfs": None,
        "runtime": "runsc",
        "cpu": 1000,
        "memory": 4096,
        "cpu_limit": 0,
        "mem_limit": 0,
        "idle_timeout": 300,
        "schedule_timeout": 30,
        "env": MappingProxyType({}),
        "name": None,
        "command_cwd": None,
        "port_forwardings": (),
        "mounts": (),
        "reverse_tunnel": None,
        "detached": False,
        "node_id": None,
        "xpu": None,
        "storage_mb": None,
        "network_policy": None,
        "failover": False,
        "extra_config": MappingProxyType({}),
    }
    values.update(overrides)
    return SandboxSpec(**values)


class RegistryTest(unittest.TestCase):
    def test_explicit_selection_wins_without_importing_backend(self):
        with (
            patch.dict(
                os.environ,
                {"AKERNEL_BACKEND": "openyuanrong-sdk"},
                clear=True,
            ),
            patch.object(registry, "_is_installed") as installed,
        ):
            self.assertEqual(registry._select_backend(), "openyuanrong-sdk")
        installed.assert_not_called()

    def test_sandbox_has_auto_detection_priority(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(registry, "_is_installed", return_value=True) as installed,
        ):
            self.assertEqual(registry._select_backend(), "openyuanrong-sandbox")
        installed.assert_called_once_with("openyuanrong-sandbox")

    def test_invalid_explicit_backend_fails_during_selection(self):
        with (
            patch.dict(os.environ, {"AKERNEL_BACKEND": "sandbox"}, clear=True),
            self.assertRaisesRegex(InvalidBackendError, "openyuanrong-sandbox"),
        ):
            registry._select_backend()

    def test_missing_default_backend_recommends_plain_install(self):
        error = registry._not_installed_error("openyuanrong-sandbox")
        self.assertIsInstance(error, BackendNotInstalledError)
        self.assertIn("pip install akernel-sdk", str(error))
        self.assertNotIn("[openyuanrong-sandbox]", str(error))

    def test_missing_actor_backend_recommends_named_extra(self):
        error = registry._not_installed_error("openyuanrong-sdk")
        self.assertIn("akernel-sdk[openyuanrong-sdk]", str(error))

    def test_loaded_backend_close_is_registered_for_process_exit(self):
        backend = MagicMock()
        backend_module = SimpleNamespace(
            create_backend=MagicMock(return_value=backend),
        )
        with (
            patch.object(registry, "_loaded_backend", None),
            patch.object(registry, "_selected_backend", "openyuanrong-sdk"),
            patch.object(registry, "_is_installed", return_value=True),
            patch.object(
                registry.importlib,
                "import_module",
                return_value=backend_module,
            ),
            patch.object(registry, "_config_from_env", return_value=MagicMock()),
            patch.object(registry.atexit, "register") as register,
        ):
            self.assertIs(registry.load_backend(), backend)

        register.assert_called_once_with(backend.close)


class OpenYuanRongSandboxBackendTest(unittest.TestCase):
    def setUp(self):
        self.config = BackendConfig(
            api_endpoint=Endpoint("api.example", 443, "https", True),
            gateway_endpoint=Endpoint("gateway.example", 80, "http", True),
            token="secret",
        )
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.backend = openyuanrong_sandbox.OpenYuanRongSandboxBackend(self.config)

    def _create_session(self, native):
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ):
            return self.backend.create(_spec())

    @staticmethod
    def _start(session, cmd="sleep 60", *, stdin=False):
        return session.commands.start(cmd, envs=None, cwd=None, stdin=stdin)

    def test_connection_config_maps_to_yr_environment(self):
        self.assertEqual(os.environ["YR_SERVER_ADDRESS"], "api.example:443")
        self.assertEqual(os.environ["YR_TLS"], "1")
        self.assertEqual(os.environ["YR_GATEWAY_ADDRESS"], "gateway.example:80")
        self.assertEqual(os.environ["YR_GATEWAY_TLS"], "0")
        self.assertEqual(os.environ["YR_TOKEN"], "secret")

    def test_runtime_identifier_without_explicit_rootfs_is_forwarded(self):
        native = MagicMock()
        native.id = "default-gvisor-next"
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            self.backend.create(_spec(runtime="gvisor-next"))

        # YuanRong applies this runtime as a configuration override to the
        # deployed default rootfs; the adapter does not build a filesystem
        # overlay.
        self.assertEqual(sandbox_type.call_args.kwargs["runtime"], "gvisor-next")
        self.assertIsNone(sandbox_type.call_args.kwargs["rootfs"])

    def test_runsc_without_explicit_rootfs_passes_runtime_config_override(self):
        native = MagicMock()
        native.id = "default-runsc"
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            self.backend.create(_spec())

        self.assertEqual(sandbox_type.call_args.kwargs["runtime"], "runsc")
        self.assertIsNone(sandbox_type.call_args.kwargs["rootfs"])

    def test_extra_config_is_forwarded_to_native_sdk(self):
        native = MagicMock()
        native.id = "default-custom-runtime"
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            self.backend.create(
                _spec(
                    runtime="custom-runtime",
                    extra_config=MappingProxyType({"featureFlag": True}),
                )
            )

        self.assertEqual(
            sandbox_type.call_args.kwargs["extra_config"],
            {"featureFlag": True},
        )

    def test_failover_is_forwarded_to_native_sandbox_sdk(self):
        native = MagicMock()
        native.id = "default-failover"
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            self.backend.create(_spec(failover=True))

        self.assertIs(sandbox_type.call_args.kwargs["failover"], True)

    def test_reload_cold_start_success_keeps_native_session_and_facades(self):
        native = MagicMock()
        native.id = "default-reload"
        native.reload.return_value = True
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ):
            session = self.backend.create(_spec())

        native_session = session._sandbox
        commands = session.commands
        files = session.files

        self.assertIs(session.reload(), True)
        self.assertIs(session._sandbox, native_session)
        self.assertIs(session.commands, commands)
        self.assertIs(session.files, files)
        native.reload.assert_called_once_with()

    def test_start_in_flight_makes_reload_fail_without_crossing_generation(self):
        native = MagicMock()
        native.id = "default-start-boundary"
        old_handle = MagicMock(pid=321)
        start_native, start_entered, start_release = _blocking_native(old_handle)
        native.commands.run.side_effect = start_native
        session = self._create_session(native)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                session.commands.start,
                "sleep 60",
                envs=None,
                cwd=None,
                stdin=False,
            )
            self.assertTrue(start_entered.wait(1))
            try:
                self.assertIs(session.reload(), False)
                native.reload.assert_not_called()
            finally:
                start_release.set()
            pid = future.result(timeout=1)

        self.assertEqual(pid.generation, 0)
        native.reload.return_value = True
        self.assertIs(session.reload(), True)
        old_handle.wait.side_effect = RuntimeError("old process missing")
        with self.assertRaisesRegex(
            BackendOperationError,
            _COLD_START_HANDLE_ERROR,
        ):
            session.commands.wait(pid, 30)

    def test_reload_in_flight_rejects_start_before_native_and_advances_once(self):
        native = MagicMock()
        native.id = "default-reload-boundary"
        reload_native, reload_entered, reload_release = _blocking_native(True)
        native.reload.side_effect = reload_native
        session = self._create_session(native)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(session.reload)
            self.assertTrue(reload_entered.wait(1))
            try:
                with self.assertRaisesRegex(
                    BackendOperationError,
                    _OPERATION_CONFLICT,
                ):
                    self._start(session, "printf new")
                native.commands.run.assert_not_called()
            finally:
                reload_release.set()
            self.assertIs(future.result(timeout=1), True)

        new_handle = MagicMock(pid=654)
        native.commands.run.return_value = new_handle
        new_pid = self._start(session, "printf new")
        self.assertEqual(new_pid.generation, 1)

    def test_wait_in_flight_makes_reload_fail_without_invalidating_generation(self):
        native = MagicMock()
        native.id = "default-wait-boundary"
        old_handle = MagicMock(pid=321)
        native.commands.run.return_value = old_handle
        wait_native, wait_entered, wait_release = _blocking_native(
            error=RuntimeError("opaque wait failure")
        )
        old_handle.wait.side_effect = wait_native
        session = self._create_session(native)

        pid = self._start(session)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(session.commands.wait, pid, 30)
            self.assertTrue(wait_entered.wait(1))
            try:
                self.assertIs(session.reload(), False)
                native.reload.assert_not_called()
            finally:
                wait_release.set()
            with self.assertRaisesRegex(
                BackendOperationError,
                "wait for process 321 failed: opaque wait failure",
            ):
                future.result(timeout=1)

        old_handle.wait.side_effect = None
        old_handle.wait.return_value = SimpleNamespace(
            stdout="still generation zero\n",
            stderr="",
            exit_code=0,
        )
        self.assertEqual(
            session.commands.wait(pid, 30),
            CommandResult("still generation zero\n", "", 0),
        )

    def test_wait_allows_concurrent_stdin_and_kill_to_finish_process(self):
        native = MagicMock()
        native.id = "default-command-readers"
        old_handle = MagicMock(pid=321)
        native.commands.run.return_value = old_handle
        wait_entered = threading.Event()
        stdin_called = threading.Event()
        kill_called = threading.Event()
        process_finished = threading.Event()

        def wait_native(_timeout):
            wait_entered.set()
            if not process_finished.wait(5):
                raise TimeoutError("test did not finish native process")
            return SimpleNamespace(stdout="finished\n", stderr="", exit_code=0)

        def send_stdin_native(*_args):
            stdin_called.set()

        def kill_native(_pid):
            kill_called.set()
            process_finished.set()
            return True

        old_handle.wait.side_effect = wait_native
        native.commands.send_stdin.side_effect = send_stdin_native
        native.commands.kill.side_effect = kill_native
        session = self._create_session(native)
        pid = self._start(session, "cat", stdin=True)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(session.commands.wait, pid, None)
            self.assertTrue(wait_entered.wait(1))
            try:
                try:
                    session.commands.send_stdin(pid, "input", False)
                    self.assertIs(session.commands.kill(pid), True)
                except BackendOperationError as error:
                    self.fail(f"concurrent command operation was rejected: {error}")
            finally:
                process_finished.set()
            result = future.result(timeout=1)

        self.assertTrue(stdin_called.is_set())
        self.assertTrue(kill_called.is_set())
        self.assertEqual(result, CommandResult("finished\n", "", 0))

    def test_reload_exception_clears_in_progress_flag(self):
        native = MagicMock()
        native.id = "default-reload-exception"
        reload_native, reload_entered, reload_release = _blocking_native(
            error=RuntimeError("reload failed")
        )
        native.reload.side_effect = reload_native
        session = self._create_session(native)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(session.reload)
            self.assertTrue(reload_entered.wait(1))
            try:
                with self.assertRaisesRegex(
                    BackendOperationError,
                    _OPERATION_CONFLICT,
                ):
                    self._start(session, "printf blocked")
                native.commands.run.assert_not_called()
            finally:
                reload_release.set()
            self.assertIs(future.result(timeout=1), False)

        native.commands.run.return_value = MagicMock(pid=654)
        pid = self._start(session, "printf after-failure")
        self.assertEqual(pid.generation, 0)
        native.reload.side_effect = None
        native.reload.return_value = True
        self.assertIs(session.reload(), True)

    def test_old_handle_native_failure_marks_generation_with_explicit_error(self):
        native = MagicMock()
        native.id = "default-cold-start-handle"
        native.reload.return_value = True
        old_handle = MagicMock()
        old_handle.pid = 321
        old_handle.wait.side_effect = RuntimeError("opaque native failure")
        native.commands.run.return_value = old_handle
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ):
            session = self.backend.create(_spec())

        pid = session.commands.start(
            "sleep 60", envs=None, cwd=None, stdin=False
        )
        self.assertIs(session.reload(), True)

        with self.assertRaisesRegex(
            BackendOperationError,
            "pre-reload command handle was not restored after sandbox cold start",
        ) as raised:
            session.commands.wait(pid, 30)

        self.assertNotIn("opaque native failure", str(raised.exception))

    def test_invalid_old_generation_fails_closed_without_pid_operations(self):
        native = MagicMock()
        native.id = "default-cold-start-generation"
        native.reload.return_value = True
        failed_handle = MagicMock(pid=321)
        failed_handle.wait.side_effect = RuntimeError("native process missing")
        second_handle = MagicMock(pid=654)
        native.commands.run.side_effect = [failed_handle, second_handle]
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ):
            session = self.backend.create(_spec())

        failed_pid = session.commands.start(
            "sleep 60", envs=None, cwd=None, stdin=False
        )
        second_pid = session.commands.start(
            "cat", envs=None, cwd=None, stdin=True
        )
        self.assertIs(session.reload(), True)
        with self.assertRaises(BackendOperationError):
            session.commands.wait(failed_pid, 30)

        with self.assertRaisesRegex(
            BackendOperationError,
            "pre-reload command handle was not restored after sandbox cold start",
        ):
            session.commands.kill(second_pid)
        with self.assertRaisesRegex(
            BackendOperationError,
            "pre-reload command handle was not restored after sandbox cold start",
        ):
            session.commands.send_stdin(second_pid, "input", False)

        native.commands.kill.assert_not_called()
        native.commands.send_stdin.assert_not_called()

    def test_new_generation_handle_works_after_old_generation_is_invalid(self):
        native = MagicMock()
        native.id = "default-new-generation"
        native.reload.return_value = True
        old_handle = MagicMock(pid=321)
        old_handle.wait.side_effect = RuntimeError("native process missing")
        new_handle = MagicMock(pid=321)
        new_handle.wait.return_value = SimpleNamespace(
            stdout="new runtime\n",
            stderr="",
            exit_code=0,
        )
        native.commands.run.side_effect = [old_handle, new_handle]
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ):
            session = self.backend.create(_spec())

        old_pid = session.commands.start(
            "sleep 60", envs=None, cwd=None, stdin=False
        )
        self.assertIs(session.reload(), True)
        with self.assertRaises(BackendOperationError):
            session.commands.wait(old_pid, 30)
        new_pid = session.commands.start(
            "printf new", envs=None, cwd=None, stdin=False
        )

        with self.assertRaisesRegex(
            BackendOperationError,
            "pre-reload command handle was not restored after sandbox cold start",
        ):
            session.commands.wait(old_pid, 30)
        self.assertEqual(
            session.commands.wait(new_pid, 30),
            CommandResult("new runtime\n", "", 0),
        )
        old_handle.wait.assert_called_once_with(30)
        new_handle.wait.assert_called_once_with(30)

    def test_snapshot_like_old_handle_native_success_remains_valid(self):
        native = MagicMock()
        native.id = "default-snapshot-handle"
        native.reload.return_value = True
        old_handle = MagicMock(pid=321)
        old_handle.wait.return_value = SimpleNamespace(
            stdout="restored\n",
            stderr="",
            exit_code=0,
        )
        native.commands.run.return_value = old_handle
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ):
            session = self.backend.create(_spec())

        pid = session.commands.start(
            "sleep 1", envs=None, cwd=None, stdin=False
        )
        self.assertIs(session.reload(), True)

        self.assertEqual(
            session.commands.wait(pid, 30),
            CommandResult("restored\n", "", 0),
        )

    def test_reload_false_does_not_advance_or_invalidate_handle_generation(self):
        native = MagicMock()
        native.id = "default-failed-reload-handle"
        native.reload.return_value = False
        old_handle = MagicMock(pid=321)
        old_handle.wait.return_value = SimpleNamespace(
            stdout="still running\n",
            stderr="",
            exit_code=0,
        )
        native.commands.run.return_value = old_handle
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ):
            session = self.backend.create(_spec())

        pid = session.commands.start(
            "sleep 1", envs=None, cwd=None, stdin=False
        )
        self.assertIs(session.reload(), False)

        self.assertEqual(
            session.commands.wait(pid, 30),
            CommandResult("still running\n", "", 0),
        )

    def test_public_command_handle_preserves_tracked_pid_token(self):
        native = MagicMock()
        native.id = "default-public-token"
        native.reload.return_value = True
        old_handle = MagicMock(pid=321)
        old_handle.wait.side_effect = RuntimeError("native process missing")
        native.commands.run.return_value = old_handle
        session = self._create_session(native)

        handle = PublicCommands(session.commands).run(
            "sleep 60", background=True
        )
        self.assertIsInstance(handle.pid, int)
        self.assertIsNot(type(handle.pid), int)
        self.assertIs(session.reload(), True)

        with self.assertRaisesRegex(
            BackendOperationError,
            _COLD_START_HANDLE_ERROR,
        ):
            handle.wait(30)

    def test_explicit_int_pid_uses_legacy_path_without_generation_claim(self):
        native = MagicMock()
        native.id = "default-legacy-pid"
        native.reload.return_value = True
        old_handle = MagicMock(pid=321)
        old_handle.wait.side_effect = RuntimeError("opaque legacy failure")
        native.commands.run.return_value = old_handle
        session = self._create_session(native)

        tracked_pid = self._start(session)
        self.assertIs(session.reload(), True)

        with self.assertRaisesRegex(
            BackendOperationError,
            "wait for process 321 failed: opaque legacy failure",
        ) as raised:
            session.commands.wait(int(tracked_pid), 30)
        self.assertNotIn("not restored after sandbox cold start", str(raised.exception))

    def test_old_generation_kill_false_does_not_invalidate(self):
        native = MagicMock()
        native.id = "default-old-kill-false"
        native.reload.return_value = True
        first_handle = MagicMock(pid=321)
        second_handle = MagicMock(pid=654)
        second_handle.wait.return_value = SimpleNamespace(
            stdout="snapshot preserved\n",
            stderr="",
            exit_code=0,
        )
        native.commands.run.side_effect = [first_handle, second_handle]
        native.commands.kill.return_value = False
        session = self._create_session(native)

        first_pid = self._start(session)
        second_pid = self._start(session, "printf restored")
        self.assertIs(session.reload(), True)

        self.assertIs(session.commands.kill(first_pid), False)
        self.assertEqual(
            session.commands.wait(second_pid, 30),
            CommandResult("snapshot preserved\n", "", 0),
        )

    def test_old_generation_kill_exception_invalidates_other_handles(self):
        native = MagicMock()
        native.id = "default-old-kill-exception"
        native.reload.return_value = True
        first_handle = MagicMock(pid=321)
        second_handle = MagicMock(pid=654)
        native.commands.run.side_effect = [first_handle, second_handle]
        native.commands.kill.side_effect = RuntimeError("opaque kill failure")
        session = self._create_session(native)

        first_pid = self._start(session)
        second_pid = self._start(session)
        self.assertIs(session.reload(), True)

        with self.assertRaisesRegex(
            BackendOperationError,
            _COLD_START_HANDLE_ERROR,
        ):
            session.commands.kill(first_pid)
        with self.assertRaisesRegex(
            BackendOperationError,
            _COLD_START_HANDLE_ERROR,
        ):
            session.commands.wait(second_pid, 30)
        second_handle.wait.assert_not_called()

    def test_old_generation_stdin_exception_invalidates_other_handles(self):
        native = MagicMock()
        native.id = "default-old-stdin-exception"
        native.reload.return_value = True
        first_handle = MagicMock(pid=321)
        second_handle = MagicMock(pid=654)
        native.commands.run.side_effect = [first_handle, second_handle]
        native.commands.send_stdin.side_effect = RuntimeError(
            "opaque stdin failure"
        )
        session = self._create_session(native)

        first_pid = self._start(session, "cat", stdin=True)
        second_pid = self._start(session)
        self.assertIs(session.reload(), True)

        with self.assertRaisesRegex(
            BackendOperationError,
            _COLD_START_HANDLE_ERROR,
        ):
            session.commands.send_stdin(first_pid, "input", False)
        with self.assertRaisesRegex(
            BackendOperationError,
            _COLD_START_HANDLE_ERROR,
        ):
            session.commands.wait(second_pid, 30)
        second_handle.wait.assert_not_called()

    def test_explicit_kata_image_is_forwarded_to_native_sdk(self):
        native = MagicMock()
        native.id = "default-kata-image"
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            self.backend.create(_spec(runtime="kata", image="ubuntu:24.04"))

        self.assertEqual(sandbox_type.call_args.kwargs["runtime"], "kata")
        self.assertEqual(sandbox_type.call_args.kwargs["image"], "ubuntu:24.04")

    def test_create_converts_inputs_and_preserves_akernel_outputs(self):
        native = MagicMock()
        native.id = "default-worker"
        native_info = SimpleNamespace(
            id="default-worker",
            state="running",
            cpu=2000,
            memory=8192,
            image=None,
        )
        native.get_info.return_value = native_info
        native.commands.run.return_value = SimpleNamespace(
            stdout="ok\n",
            stderr="",
            exit_code=0,
        )
        native.commands.list.return_value = [
            SimpleNamespace(pid=7, command="sleep 1", running=True)
        ]
        native.files.get_info.return_value = SimpleNamespace(
            name="a.txt",
            path="/tmp/a.txt",
            type="file",
            size=3,
            permissions="rw-r--r--",
            modified_time=1.0,
        )
        rootfs = S3Config("https://s3.example", "rootfs", "rootfs.img")
        mount = Mount(target="/tools", image_url="tools:v1")
        tunnel = HttpReverseTunnel("https://service.example")
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            session = self.backend.create(
                _spec(
                    rootfs=rootfs,
                    runtime="kata",
                    cpu=2000,
                    memory=8192,
                    name="worker",
                    command_cwd="/workspace",
                    port_forwardings=(8080,),
                    mounts=(mount,),
                    reverse_tunnel=tunnel,
                    detached=True,
                    node_id="node-1",
                )
            )

        kwargs = sandbox_type.call_args.kwargs
        self.assertIsInstance(
            kwargs["rootfs"],
            openyuanrong_sandbox.yr_sandbox.S3Config,
        )
        self.assertEqual(kwargs["runtime"], "kata")
        self.assertEqual(kwargs["cwd"], "/workspace")
        self.assertEqual(kwargs["port_forwardings"], [8080])
        self.assertEqual(kwargs["upstream"], "https://service.example")
        self.assertEqual(kwargs["create_timeout"], 60)
        self.assertEqual(kwargs["node_id"], "node-1")

        self.assertEqual(
            session.commands.run("echo ok", envs=None, cwd=None, timeout=60),
            CommandResult("ok\n", "", 0),
        )
        self.assertEqual(
            session.commands.list(),
            [CommandInfo(pid=7, command="sleep 1", running=True)],
        )
        self.assertEqual(
            session.files.get_info("/tmp/a.txt"),
            EntryInfo(
                name="a.txt",
                path="/tmp/a.txt",
                type="file",
                size=3,
                permissions="rw-r--r--",
                modified_time=1.0,
            ),
        )
        self.assertEqual(session.get_info().id, "default-worker")
        session.close()
        native.close.assert_called_once_with()
        native.kill.assert_not_called()

    def test_create_converts_network_policy_to_native_sdk_type(self):
        native = MagicMock()
        native.id = "default-worker"
        native.commands = MagicMock()
        native.files = MagicMock()
        policy = NetworkPolicy.deny_dns("github.com", "*.github.com")
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            session = self.backend.create(_spec(network_policy=policy))

        network = sandbox_type.call_args.kwargs["network"]
        self.assertIsInstance(network, openyuanrong_sandbox.yr_sandbox.NetworkPolicy)
        self.assertFalse(network.block_network)
        self.assertEqual(network.dns_blacklist, ("github.com", "*.github.com"))
        session.close()

    def test_terminate_forces_deletion_of_detached_native_sandbox(self):
        native = MagicMock()
        native.id = "default-worker"
        native.commands = MagicMock()
        native.files = MagicMock()
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            session = self.backend.create(_spec(detached=True))
            session.terminate()
            session.close()

        sandbox_type.delete.assert_called_once_with("default-worker")
        native.close.assert_called_once_with()
        native.kill.assert_not_called()

    def test_terminate_closes_native_resources_before_remote_delete(self):
        lifecycle = []
        native = MagicMock()
        native.id = "default-worker"
        native.commands = MagicMock()
        native.files = MagicMock()
        native.close.side_effect = lambda: lifecycle.append("close")
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            sandbox_type.delete.side_effect = lambda _sandbox_id: lifecycle.append(
                "delete"
            )
            session = self.backend.create(_spec())
            session.terminate()

        self.assertEqual(lifecycle, ["close", "delete"])

    def test_detached_delete_failure_still_allows_local_cleanup(self):
        native = MagicMock()
        native.id = "default-worker"
        native.commands = MagicMock()
        native.files = MagicMock()
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            sandbox_type.delete.side_effect = [
                RuntimeError("remote delete failed"),
                None,
            ]
            session = self.backend.create(_spec(detached=True))
            with self.assertRaisesRegex(
                BackendOperationError, "remote delete failed"
            ):
                try:
                    session.terminate()
                finally:
                    session.close()
            session.terminate()
            session.terminate()

        self.assertEqual(sandbox_type.delete.call_count, 2)
        sandbox_type.delete.assert_called_with("default-worker")
        native.close.assert_called_once_with()
        native.kill.assert_not_called()

    def test_terminate_then_close_does_not_issue_second_native_delete(self):
        native = MagicMock()
        native.id = "default-anonymous"
        native.commands = MagicMock()
        native.files = MagicMock()
        native.kill.side_effect = RuntimeError("redundant DELETE failed")
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            session = self.backend.create(_spec())
            session.terminate()
            session.close()

        sandbox_type.delete.assert_called_once_with("default-anonymous")
        native.close.assert_called_once_with()
        native.kill.assert_not_called()

    def test_non_detached_termination_uses_retryable_id_delete(self):
        native = MagicMock()
        native.id = "default-anonymous"
        native.commands = MagicMock()
        native.files = MagicMock()
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            sandbox_type.delete.side_effect = [RuntimeError("temporary failure"), None]
            session = self.backend.create(_spec())
            with self.assertRaisesRegex(BackendOperationError, "temporary failure"):
                session.terminate()
            session.terminate()
            session.terminate()

        self.assertEqual(sandbox_type.delete.call_count, 2)
        sandbox_type.delete.assert_called_with("default-anonymous")
        native.kill.assert_not_called()

    def test_custom_reverse_tunnel_ports_are_forwarded(self):
        native = MagicMock()
        native.id = "default-anonymous"
        native.commands = MagicMock()
        native.files = MagicMock()
        tunnel = HttpReverseTunnel(
            "https://service.example",
            reverse_port=9000,
            listen_port=9001,
        )
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ) as sandbox_type:
            session = self.backend.create(_spec(reverse_tunnel=tunnel))
            session.close()

        self.assertEqual(sandbox_type.call_args.kwargs["proxy_port"], 9001)

    def test_non_consecutive_reverse_tunnel_ports_are_rejected(self):
        tunnel = HttpReverseTunnel(
            "https://service.example",
            reverse_port=9000,
            listen_port=9002,
        )
        with self.assertRaisesRegex(
            UnsupportedBackendFeatureError,
            "listen_port - 1",
        ):
            self.backend.create(_spec(reverse_tunnel=tunnel))

    def test_named_delete_uses_deterministic_sid(self):
        with patch.object(
            openyuanrong_sandbox.yr_sandbox.Sandbox,
            "delete",
        ) as delete:
            self.backend.delete_named("worker")
        delete.assert_called_once_with("default-worker")

    def test_checkpoint_delegates_to_reusable_snapshot_api(self):
        native = MagicMock()
        native.id = "default-source"
        native.commands = MagicMock()
        native.files = MagicMock()
        native.create_snapshot.return_value = SimpleNamespace(
            snapshot_id="checkpoint-1"
        )
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ):
            session = self.backend.create(_spec())

            self.assertEqual(session.checkpoint(timeout=240), "checkpoint-1")

        native.create_snapshot.assert_called_once_with(timeout=240)

    def test_checkpoint_uses_official_backend_default_timeout(self):
        native = MagicMock()
        native.id = "default-source"
        native.commands = MagicMock()
        native.files = MagicMock()
        calls = []

        def create_snapshot():
            calls.append(True)
            return SimpleNamespace(snapshot_id="checkpoint-1")

        native.create_snapshot = create_snapshot
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ):
            session = self.backend.create(_spec())

            self.assertEqual(session.checkpoint(timeout=180), "checkpoint-1")

        self.assertEqual(calls, [True])

    def test_checkpoint_rejects_custom_timeout_on_official_backend(self):
        native = MagicMock()
        native.id = "default-source"
        native.commands = MagicMock()
        native.files = MagicMock()
        native.create_snapshot = lambda: SimpleNamespace(
            snapshot_id="checkpoint-1"
        )
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
            return_value=native,
        ):
            session = self.backend.create(_spec())

            with self.assertRaisesRegex(
                UnsupportedBackendFeatureError,
                "default 180-second",
            ):
                session.checkpoint(timeout=240)

    def test_restore_uses_snapshot_template_and_explicit_tunnel(self):
        native = MagicMock()
        native.id = "default-restored"
        native.commands = MagicMock()
        native.files = MagicMock()
        tunnel = HttpReverseTunnel(
            "https://new-target.example",
            reverse_port=9000,
            listen_port=9001,
            connect_timeout=12,
        )
        with patch.object(
            openyuanrong_sandbox.yr_sandbox,
            "Sandbox",
        ) as sandbox_type:
            sandbox_type.create.return_value = native
            session = self.backend.restore(
                "checkpoint-1",
                reverse_tunnel=tunnel,
            )

        self.assertEqual(session.id, "default-restored")
        sandbox_type.create.assert_called_once_with(
            "checkpoint-1",
            upstream="https://new-target.example",
            tunnel_connect_timeout=12,
            proxy_port=9001,
        )

    def test_checkpoint_catalog_pages_and_deletes(self):
        first = ([SimpleNamespace(snapshot_id="checkpoint-1")], "next")
        second = ([SimpleNamespace(snapshot_id="checkpoint-2")], "")
        with patch.object(
            openyuanrong_sandbox.yr_sandbox.Sandbox,
            "list_snapshots",
            side_effect=[first, second],
        ) as list_snapshots, patch.object(
            openyuanrong_sandbox.yr_sandbox.Sandbox,
            "delete_snapshot",
        ) as delete_snapshot:
            self.assertEqual(
                self.backend.list_checkpoints(),
                ["checkpoint-1", "checkpoint-2"],
            )
            self.backend.delete_checkpoint("checkpoint-1")

        self.assertEqual(list_snapshots.call_count, 2)
        delete_snapshot.assert_called_once_with("checkpoint-1")


class OpenYuanRongSdkBackendTest(unittest.TestCase):
    def setUp(self):
        self.config = BackendConfig(
            api_endpoint=Endpoint("api.example", 443, "https", True),
            gateway_endpoint=Endpoint("gateway.example", 80, "http", True),
            token="secret",
        )
        initialized = patch.object(openyuanrong_sdk._impl, "ensure_initialized")
        initialized.start()
        self.addCleanup(initialized.stop)
        self.backend = openyuanrong_sdk.OpenYuanRongSdkBackend(self.config)

    def test_failover_is_forwarded_to_native_invoke_options(self):
        instance = MagicMock()
        with (
            patch.object(
                openyuanrong_sdk._impl,
                "build_options",
                return_value=MagicMock(),
            ) as build_options,
            patch.object(
                openyuanrong_sdk._impl,
                "create_instance",
                return_value=instance,
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "real_instance_id",
                return_value="physical-id",
            ),
        ):
            self.backend.create(_spec(failover=True))

        self.assertIs(build_options.call_args.kwargs["failover"], True)

    def test_reload_forwards_to_actor_runtime(self):
        instance = MagicMock()
        with (
            patch.object(
                openyuanrong_sdk._impl,
                "build_options",
                return_value=MagicMock(),
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "create_instance",
                return_value=instance,
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "real_instance_id",
                return_value="physical-id",
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "reload_instance",
                return_value=True,
            ) as reload_instance,
        ):
            session = self.backend.create(_spec())
            result = session.reload()

        self.assertIs(result, True)
        reload_instance.assert_called_once_with(instance)

    def test_physical_id_failure_rolls_back_created_actor(self):
        instance = MagicMock()
        physical_id_error = RuntimeError("physical ID unavailable")
        with (
            patch.object(
                openyuanrong_sdk._impl,
                "build_options",
                return_value=MagicMock(),
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "create_instance",
                return_value=instance,
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "real_instance_id",
                side_effect=physical_id_error,
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "terminate_instance",
            ) as terminate,
            self.assertRaisesRegex(
                BackendOperationError,
                "physical ID unavailable",
            ) as raised,
        ):
            self.backend.create(_spec())

        self.assertIs(raised.exception.__cause__, physical_id_error)
        terminate.assert_called_once_with(instance)

    def test_rollback_failure_does_not_replace_physical_id_error(self):
        instance = MagicMock()
        physical_id_error = RuntimeError("physical ID unavailable")
        with (
            patch.object(
                openyuanrong_sdk._impl,
                "build_options",
                return_value=MagicMock(),
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "create_instance",
                return_value=instance,
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "real_instance_id",
                side_effect=physical_id_error,
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "terminate_instance",
                side_effect=RuntimeError("rollback failed"),
            ) as terminate,
            self.assertLogs(openyuanrong_sdk.logger, level="WARNING"),
            self.assertRaisesRegex(
                BackendOperationError,
                "physical ID unavailable",
            ) as raised,
        ):
            self.backend.create(_spec())

        self.assertIs(raised.exception.__cause__, physical_id_error)
        terminate.assert_called_once_with(instance)

    def test_termination_failure_still_closes_reverse_tunnel(self):
        instance = MagicMock()
        tunnel_client = MagicMock()
        terminate_error = RuntimeError("remote delete failed")
        with (
            patch.object(
                openyuanrong_sdk._impl,
                "build_options",
                return_value=MagicMock(),
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "create_instance",
                return_value=instance,
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "real_instance_id",
                return_value="physical-id",
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "start_reverse_tunnel",
                return_value=tunnel_client,
            ),
            patch.object(
                openyuanrong_sdk._impl,
                "terminate_instance",
                side_effect=[terminate_error, None],
            ) as terminate,
        ):
            session = self.backend.create(
                _spec(reverse_tunnel=HttpReverseTunnel("http://127.0.0.1:9000"))
            )
            with self.assertRaisesRegex(
                BackendOperationError,
                "remote delete failed",
            ) as raised:
                session.terminate()
            session.close()
            session.terminate()
            session.terminate()

        self.assertIs(raised.exception.__cause__, terminate_error)
        self.assertEqual(terminate.call_count, 2)
        tunnel_client.stop.assert_called_once_with()

    def test_close_finalizes_actor_sdk(self):
        with patch.object(openyuanrong_sdk._impl, "finalize") as finalize:
            self.backend.close()

        finalize.assert_called_once_with()

    def test_reusable_checkpoint_operations_are_explicitly_unsupported(self):
        with self.assertRaises(UnsupportedBackendFeatureError):
            self.backend.restore("checkpoint-1", reverse_tunnel=None)
        with self.assertRaises(UnsupportedBackendFeatureError):
            self.backend.list_checkpoints()
        with self.assertRaises(UnsupportedBackendFeatureError):
            self.backend.delete_checkpoint("checkpoint-1")


if __name__ == "__main__":
    unittest.main()
