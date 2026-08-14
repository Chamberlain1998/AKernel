#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

DOCKER_BIN="${DOCKER_BIN:-docker}"
DOCKERD_PID="${DOCKERD_PID:-}"

docker_job_wait_for_docker() {
  local timeout="${DOCKER_READY_TIMEOUT:-60}"
  local elapsed=0
  while [[ "${elapsed}" -lt "${timeout}" ]]; do
    if "${DOCKER_BIN}" info >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

docker_job_stop_dockerd() {
  if [[ -n "${DOCKERD_PID:-}" ]]; then
    kill "${DOCKERD_PID}" >/dev/null 2>&1 || true
    wait "${DOCKERD_PID}" >/dev/null 2>&1 || true
    DOCKERD_PID=""
  fi
}

docker_job_start_dockerd() {
  local log_file="${1:?dockerd log path required}"
  local driver="${DOCKER_DRIVER:-overlay2}"

  if "${DOCKER_BIN}" info >/dev/null 2>&1; then
    return 0
  fi
  if ! command -v dockerd >/dev/null 2>&1; then
    echo "Docker daemon is unavailable and dockerd is not installed." >&2
    return 1
  fi

  mkdir -p "$(dirname "${log_file}")"
  : >"${log_file}"
  dockerd \
    --host="${DOCKER_HOST:-unix:///var/run/docker.sock}" \
    --storage-driver="${driver}" >>"${log_file}" 2>&1 &
  DOCKERD_PID="$!"
  if docker_job_wait_for_docker; then
    return 0
  fi

  docker_job_stop_dockerd
  if [[ "${driver}" != "vfs" ]]; then
    echo "dockerd with ${driver} did not become ready; retrying with vfs." >&2
    cp "${log_file}" "${log_file}.${driver}" 2>/dev/null || true
    : >"${log_file}"
    dockerd \
      --host="${DOCKER_HOST:-unix:///var/run/docker.sock}" \
      --storage-driver=vfs >>"${log_file}" 2>&1 &
    DOCKERD_PID="$!"
    if docker_job_wait_for_docker; then
      return 0
    fi
    docker_job_stop_dockerd
  fi

  echo "Docker daemon failed to start. Log follows:" >&2
  cat "${log_file}" >&2
  return 1
}
