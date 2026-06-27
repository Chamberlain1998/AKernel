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

"""Use the same S3Config type for a rootfs and a read-only mount.

Required environment variables:

* AKERNEL_S3_ENDPOINT
* AKERNEL_S3_BUCKET
* AKERNEL_S3_ROOTFS_OBJECT and/or AKERNEL_S3_MOUNT_OBJECT

Credentials are optional and use AKERNEL_S3_ACCESS_KEY and
AKERNEL_S3_SECRET_KEY.
"""

import os

from akernel_sdk import Mount, S3Config, Sandbox


def s3_config(object_name: str) -> S3Config:
    return S3Config(
        endpoint=os.environ["AKERNEL_S3_ENDPOINT"],
        bucket=os.environ["AKERNEL_S3_BUCKET"],
        object=object_name,
        access_key=os.environ.get("AKERNEL_S3_ACCESS_KEY"),
        secret_key=os.environ.get("AKERNEL_S3_SECRET_KEY"),
    )


def run_rootfs(object_name: str) -> None:
    with Sandbox(rootfs=s3_config(object_name), cpu=1000, memory=2048) as sandbox:
        result = sandbox.commands.run("cat /etc/os-release")
        assert result.exit_code == 0, result.stderr
        print("S3 rootfs:\n" + result.stdout)


def run_mount(object_name: str) -> None:
    mount = Mount(
        target="/mnt/data",
        type="erofs",
        s3_config=s3_config(object_name),
    )
    with Sandbox(mounts=[mount], cpu=1000, memory=2048) as sandbox:
        result = sandbox.commands.run("ls -la /mnt/data")
        assert result.exit_code == 0, result.stderr
        print("S3 mount:\n" + result.stdout)


def main() -> None:
    rootfs_object = os.environ.get("AKERNEL_S3_ROOTFS_OBJECT")
    mount_object = os.environ.get("AKERNEL_S3_MOUNT_OBJECT")
    if not rootfs_object and not mount_object:
        raise SystemExit("set AKERNEL_S3_ROOTFS_OBJECT and/or AKERNEL_S3_MOUNT_OBJECT")
    if rootfs_object:
        run_rootfs(rootfs_object)
    if mount_object:
        run_mount(mount_object)


if __name__ == "__main__":
    main()
