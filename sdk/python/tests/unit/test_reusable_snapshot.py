import dataclasses
import unittest
from unittest.mock import MagicMock, patch

import akernel_sdk
from akernel_sdk import Sandbox
from akernel_sdk import sandbox as sandbox_module


class ReusableSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.session.id = "default-clone"
        self.session.commands = MagicMock()
        self.session.files = MagicMock()
        self.backend = MagicMock()
        self.backend.create.return_value = self.session
        self.load_backend = patch.object(
            sandbox_module,
            "load_backend",
            return_value=self.backend,
        )
        self.load_backend.start()
        self.addCleanup(self.load_backend.stop)

    def test_snapshot_info_is_frozen_public_value(self):
        info = akernel_sdk.SnapshotInfo("snap-1", ("base",))
        self.assertEqual(info.names, ("base",))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            info.snapshot_id = "changed"

    def test_create_snapshot_delegates_to_backend_session(self):
        self.session.create_snapshot.return_value = akernel_sdk.SnapshotInfo(
            "snap-1",
            (),
        )
        sandbox = Sandbox()
        self.assertEqual(
            sandbox.create_snapshot(name="base"),
            akernel_sdk.SnapshotInfo("snap-1", ()),
        )
        self.session.create_snapshot.assert_called_once_with(name="base")

    def test_create_from_snapshot_reuses_normal_create_spec(self):
        snapshot = akernel_sdk.SnapshotInfo("snap-ready", ("base",))
        clone = Sandbox.create(snapshot, name="clone", cpu=2000)
        self.assertEqual(clone.id, "default-clone")
        spec = self.backend.create.call_args.args[0]
        self.assertEqual(spec.snapshot_id, "snap-ready")
        self.assertEqual(spec.name, "clone")
        self.assertEqual(spec.cpu, 2000)

    def test_get_list_delete_delegate_to_backend(self):
        self.backend.get_snapshot.return_value = akernel_sdk.SnapshotInfo(
            "snap-1",
            ("base",),
        )
        self.backend.list_snapshots.return_value = (
            [akernel_sdk.SnapshotInfo("snap-1", ())],
            "next",
        )
        self.assertEqual(
            Sandbox.get_snapshot("snap-1"),
            akernel_sdk.SnapshotInfo("snap-1", ("base",)),
        )
        self.assertEqual(
            Sandbox.list_snapshots(name="base", page_token="p", page_size=10)[1],
            "next",
        )
        self.backend.list_snapshots.assert_called_once_with(
            name="base",
            page_token="p",
            page_size=10,
        )
        Sandbox.delete_snapshot("snap-1")
        self.backend.delete_snapshot.assert_called_once_with("snap-1")
