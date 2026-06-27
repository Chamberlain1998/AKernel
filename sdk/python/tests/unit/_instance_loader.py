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

"""Load the remote actor as a plain local class for unit tests."""

from pathlib import Path
from types import ModuleType


def load_instance_class():
    source_path = Path(__file__).parents[2] / "akernel_sdk" / "_instance.py"
    source = source_path.read_text(encoding="utf-8")
    source = source.replace("import yr\n", "")
    source = source.replace("@yr.instance\n", "")
    module = ModuleType("_akernel_test_instance")
    exec(compile(source, str(source_path), "exec"), module.__dict__)
    return module._SandboxInstance
