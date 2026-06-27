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

"""Interactive PTY example."""

import sys

from akernel_sdk import Sandbox


def write_output(data: bytes) -> None:
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


with Sandbox(cpu=1000, memory=2048) as sandbox:
    with sandbox.pty.create(on_data=write_output) as session:
        session.send_stdin(b"echo hello from PTY\n")
        session.send_stdin(b"exit 7\n")
        print(f"exit code: {session.wait()}")
