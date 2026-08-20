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

"""Create a reusable Snapshot and restore an independent clone."""

from akernel_sdk import Sandbox


def main() -> None:
    source = Sandbox(name="snapshot-source")
    clone = None
    snapshot = None
    try:
        source.files.write("/tmp/marker", "from reusable snapshot")
        snapshot = source.create_snapshot(name="python-ready")
        clone = Sandbox.create(snapshot, name="snapshot-clone")
        assert clone.files.read("/tmp/marker") == "from reusable snapshot"
        print(f"Restored {clone.id} from {snapshot.snapshot_id}")
    finally:
        if clone is not None:
            clone.kill()
        source.kill()
        if snapshot is not None:
            Sandbox.delete_snapshot(snapshot.snapshot_id)


if __name__ == "__main__":
    main()
