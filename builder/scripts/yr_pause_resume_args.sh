#!/bin/bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

configure_pause_resume_args() {
    local enabled="${1:?pause/resume enabled value is required}"
    local capability_file="${2:?RRT capability file is required}"
    local checkpoint_dir="${3:?checkpoint directory is required}"
    local standalone="${4:?standalone mode value is required}"
    local snapshot_backend="${AKERNEL_SNAPSHOT_STORAGE_BACKEND:-datasystem}"

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
            case "${snapshot_backend}" in
                datasystem)
                    pause_resume_args=(
                        --enable_sandbox_pause_resume true
                        --snapshot_storage_backend datasystem
                        --checkpoint_dir "${checkpoint_dir}"
                    )
                    ;;
                obs)
                    local obs_endpoint="${AKERNEL_SNAPSHOT_OBS_ENDPOINT:-}"
                    local obs_bucket="${AKERNEL_SNAPSHOT_OBS_BUCKET:-}"
                    local obs_access_key="${AKERNEL_SNAPSHOT_OBS_ACCESS_KEY:-}"
                    local obs_secret_key="${AKERNEL_SNAPSHOT_OBS_SECRET_KEY:-}"
                    local obs_security_token="${AKERNEL_SNAPSHOT_OBS_SECURITY_TOKEN:-}"
                    local obs_use_https="${AKERNEL_SNAPSHOT_OBS_USE_HTTPS:-true}"
                    local obs_path_style="${AKERNEL_SNAPSHOT_OBS_PATH_STYLE:-false}"
                    if [ -z "${obs_endpoint}" ] || [ -z "${obs_bucket}" ] || \
                        [ -z "${obs_access_key}" ] || [ -z "${obs_secret_key}" ]; then
                        echo "OBS snapshot storage requires endpoint, bucket, access key, and secret key" >&2
                        return 1
                    fi
                    case "${obs_use_https}" in true|false) ;; *)
                        echo "AKERNEL_SNAPSHOT_OBS_USE_HTTPS must be true or false" >&2
                        return 1
                    esac
                    case "${obs_path_style}" in true|false) ;; *)
                        echo "AKERNEL_SNAPSHOT_OBS_PATH_STYLE must be true or false" >&2
                        return 1
                    esac
                    pause_resume_args=(
                        --enable_sandbox_pause_resume true
                        --snapshot_storage_backend obs
                        --checkpoint_dir "${checkpoint_dir}"
                        --snapshot_obs_endpoint "${obs_endpoint}"
                        --snapshot_obs_bucket "${obs_bucket}"
                        --snapshot_obs_access_key "${obs_access_key}"
                        --snapshot_obs_secret_key "${obs_secret_key}"
                    )
                    if [ -n "${obs_security_token}" ]; then
                        pause_resume_args+=(--snapshot_obs_security_token "${obs_security_token}")
                    fi
                    pause_resume_args+=(
                        --snapshot_obs_use_https "${obs_use_https}"
                        --snapshot_obs_path_style "${obs_path_style}"
                    )
                    ;;
                *)
                    echo "AKERNEL_SNAPSHOT_STORAGE_BACKEND must be datasystem or obs" >&2
                    return 1
                    ;;
            esac
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
