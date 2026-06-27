#!/bin/bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

mkdir -p /etc/k8s_secrets
mount --bind /run/secrets/kubernetes.io/serviceaccount /etc/k8s_secrets
