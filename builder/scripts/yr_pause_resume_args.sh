#!/bin/bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

configure_pause_resume_args() {
    local enabled="${1:?pause/resume enabled value is required}"
    local capability_file="${2:?RRT capability file is required}"
    local checkpoint_dir="${3:?checkpoint directory is required}"
    local standalone="${4:?standalone mode value is required}"

    pause_resume_args=()
    standalone_pause_resume_args=()

    case "${enabled}" in
        true)
            if [ ! -f "${capability_file}" ]; then
                echo "pause/resume requires an image built with the RRT runtime" >&2
                return 1
            fi
            mkdir -p "${checkpoint_dir}"
            if [ ! -w "${checkpoint_dir}" ]; then
                echo "checkpoint directory is not writable: ${checkpoint_dir}" >&2
                return 1
            fi
            pause_resume_args=(
                --enable_sandbox_pause_resume true
                --snapshot_storage_backend datasystem
                --checkpoint_dir "${checkpoint_dir}"
            )
            standalone_pause_resume_args=("${pause_resume_args[@]}")
            case "${standalone}" in
                true)
                    standalone_pause_resume_args+=(--data_system_enable true)
                    ;;
                false) ;;
                *)
                    echo "AKS_LOCAL_MODE must be true or false" >&2
                    return 1
                    ;;
            esac
            ;;
        false) ;;
        *)
            echo "AKERNEL_ENABLE_PAUSE_RESUME must be true or false" >&2
            return 1
            ;;
    esac
}
