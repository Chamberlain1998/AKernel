from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).parents[1] / "pause_resume_function_matrix_e2e.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("pause_resume_function_matrix_e2e", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_parse_memory_state() -> None:
    state = MODULE._parse_memory_state("2\t314\t42\t33554432\t123456\t90\n")

    assert state == {
        "sequence": 2,
        "pid": 314,
        "counter": 42,
        "length": 33_554_432,
        "checksum": 123_456,
        "sentinelByte": 90,
    }


def test_assert_memory_state_continuity_accepts_same_process_and_memory() -> None:
    before = {
        "sequence": 1,
        "pid": 314,
        "counter": 42,
        "length": 33_554_432,
        "checksum": 123_456,
        "sentinelByte": 90,
    }
    after = {**before, "sequence": 2}

    MODULE._assert_memory_state_continuity(before, after)


def test_assert_memory_state_continuity_rejects_reinitialized_process() -> None:
    before = {
        "sequence": 1,
        "pid": 314,
        "counter": 42,
        "length": 33_554_432,
        "checksum": 123_456,
        "sentinelByte": 90,
    }
    after = {**before, "sequence": 2, "pid": 315, "counter": 41}

    try:
        MODULE._assert_memory_state_continuity(before, after)
    except AssertionError as exc:
        assert "memory process identity/state changed" in str(exc)
    else:
        raise AssertionError("reinitialized process was accepted")
