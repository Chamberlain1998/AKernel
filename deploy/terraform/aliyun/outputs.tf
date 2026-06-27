# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

output "kubeconfig_path" {
  value       = local.kubeconfig_path
  description = "Path to kubeconfig used by providers."
}

output "cluster_id" {
  value       = try(alicloud_cs_managed_kubernetes.ack[0].id, "")
  description = "ACK cluster ID (if created)."
}

output "vpc_id" {
  value       = local.effective_vpc_id
  description = "VPC ID (created or existing)."
}

output "core_namespace" {
  value       = var.core_namespace
  description = "Namespace for akernel core release."
}

output "monitor_namespace" {
  value       = var.monitor_namespace
  description = "Namespace for monitor resources."
}

output "dragonfly_namespace" {
  value       = var.dragonfly_namespace
  description = "Namespace for Dragonfly components."
}
