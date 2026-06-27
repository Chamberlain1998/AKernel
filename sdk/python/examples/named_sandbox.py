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

"""Create a named detached sandbox and delete it by name."""

import uuid

from akernel_sdk import Sandbox


def main() -> None:
    name = f"example-{uuid.uuid4().hex[:8]}"
    sandbox = Sandbox(name=name, detached=True, cpu=1000, memory=2048)
    try:
        result = sandbox.commands.run("printf named-sandbox-ok")
        assert result.exit_code == 0, result.stderr
        print(f"Created {name}: id={sandbox.id} output={result.stdout}")
    finally:
        # Detached sandboxes survive local client cleanup.
        sandbox.kill()
        Sandbox.delete(name)
        print(f"Deleted {name}")


if __name__ == "__main__":
    main()
