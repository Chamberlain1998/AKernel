#!/usr/bin/env python3

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0
"""Generate AKernel/openYuanrong-compatible signed JWT tokens.

The implementation intentionally matches openYuanrong's current TokenContent::Sign
logic: LITEBUS_DATA_KEY is a hex string, decoded to bytes, used as the HMAC key,
and the hex HMAC digest string is base64url encoded as the JWT signature.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import pathlib
import re
import sys
import time


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def parse_ttl(value: str) -> int | None:
    raw = value.strip().lower()
    if raw in {"never", "none", "-1"}:
        return None
    if raw.isdigit():
        return int(raw)
    match = re.fullmatch(r"(\d+)([smhdy])", raw)
    if not match:
        raise ValueError("TTL must be seconds, <n>s, <n>m, <n>h, <n>d, <n>y, or never")
    number = int(match.group(1))
    unit = match.group(2)
    scale = {
        "s": 1,
        "m": 60,
        "h": 60 * 60,
        "d": 24 * 60 * 60,
        "y": 365 * 24 * 60 * 60,
    }[unit]
    return number * scale


def read_seed(args: argparse.Namespace) -> str:
    if args.seed_hex:
        seed = args.seed_hex
    else:
        seed_file = pathlib.Path(args.seed_file) if args.seed_file else repo_root() / ".akernel" / args.env / "iam-seed"
        try:
            seed = seed_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise SystemExit(f"missing seed file: {seed_file}; run make config ENV={args.env} first")
    seed = "".join(seed.split()).upper()
    if not re.fullmatch(r"[0-9A-F]+", seed) or len(seed) % 2 != 0:
        raise SystemExit("seed must be an even-length hex string")
    return seed


def generate(seed_hex: str, tenant: str, role: str, ttl: int | None) -> str:
    seed = bytes.fromhex(seed_hex)
    header_json = b'{"alg":"HS256","typ":"JWT"}'
    exp = -1 if ttl is None else int(time.time()) + ttl

    payload: dict[str, object] = {"sub": tenant, "exp": exp}
    if role:
        payload["role"] = role

    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signing_input = f"{b64url(header_json)}.{b64url(payload_json)}"
    signature_hex = hmac.new(seed, signing_input.encode("utf-8"), hashlib.sha256).hexdigest()
    signature = b64url(signature_hex.encode("ascii"))
    return f"{signing_input}.{signature}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default="default", help="local .akernel/<env> directory")
    parser.add_argument("--seed-hex", default="", help="hex LITEBUS_DATA_KEY")
    parser.add_argument("--seed-file", default="", help="file containing hex LITEBUS_DATA_KEY")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--role", default="developer")
    parser.add_argument("--ttl", default="24h")
    parser.add_argument("--write-file", default="", help="write token to this file")
    parser.add_argument("--print-export", action="store_true", help="print export AKERNEL_TOKEN=...")
    args = parser.parse_args()

    ttl = parse_ttl(args.ttl)
    token = generate(read_seed(args), args.tenant, args.role, ttl)

    if args.write_file:
        path = pathlib.Path(args.write_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass

    if args.print_export:
        print(f"export AKERNEL_TOKEN={token!r}")
    else:
        print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
