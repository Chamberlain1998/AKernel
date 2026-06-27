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

"""Command Stdin Example

Demonstrates feeding input to a background command and closing its stdin
to signal EOF.

By default a command's stdin is detached to /dev/null. Pass stdin=True
(with background=True) to keep an open stdin PIPE you can write to via
send_stdin(). Processes that only act on EOF (cat, sort, wc, ...) need
close_stdin() — or send_stdin(..., eof=True) — to finish.

Prerequisites:
  - AKERNEL_SERVER_ADDRESS and AKERNEL_TOKEN environment variables must be set.

Usage:
  export AKERNEL_SERVER_ADDRESS=your-server.example.com
  export AKERNEL_TOKEN=your-token
  python command_stdin.py
"""

from akernel_sdk import Sandbox


def main():
    with Sandbox(cpu=1000, memory=2048) as sb:
        print(f"Sandbox created: {sb.id}")

        # --- Feed input, then close stdin so `wc -l` reaches EOF ---
        handle = sb.commands.run("wc -l", background=True, stdin=True)
        handle.send_stdin("line one\nline two\nline three\n")
        handle.close_stdin()  # signal EOF; same as send_stdin("", eof=True)
        result = handle.wait(timeout=15)
        print(f"wc -l counted: {result.stdout.strip()} lines")

        # --- Send data and EOF together in a single call ---
        handle = sb.commands.run("cat", background=True, stdin=True)
        handle.send_stdin("hello from stdin\n", eof=True)
        result = handle.wait(timeout=15)
        print(f"cat echoed: {result.stdout.strip()}")

    print("Sandbox terminated.")


if __name__ == "__main__":
    main()
