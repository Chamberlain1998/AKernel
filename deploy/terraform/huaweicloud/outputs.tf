# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

output "kubeconfig_path" {
  value       = local.kubeconfig_path
  description = "Path to kubeconfig used by providers."
}

output "cluster_id" {
  value       = try(huaweicloud_cce_cluster.this[0].id, "")
  description = "CCE cluster ID (if created)."
}

output "vpc_id" {
  value       = try(huaweicloud_vpc.this[0].id, "")
  description = "VPC ID (if created)."
}

output "subnet_id" {
  value       = try(huaweicloud_vpc_subnet.this[0].id, "")
  description = "Subnet ID (if created)."
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

output "cluster_api_eip" {
  value       = try(huaweicloud_vpc_eip.cluster_api[0].address, "")
  description = "CCE API server EIP when cluster_api_public_access=true."
}

output "node_subnet_snat_eip" {
  value       = try(huaweicloud_vpc_eip.node_subnet_snat[0].address, "")
  description = "Node subnet SNAT EIP when node_subnet_enable_snat=true."
}

output "node_subnet_nat_gateway_id" {
  value       = try(huaweicloud_nat_gateway.node_subnet[0].id, "")
  description = "NAT gateway ID for node subnet SNAT when node_subnet_enable_snat=true."
}

output "eni_subnet_id" {
  value       = try(huaweicloud_vpc_subnet.eni[0].id, "")
  description = "ENI subnet ID for CCE Turbo pod networking (if created)."
}

output "pod_subnet_snat_eip" {
  value       = try(huaweicloud_vpc_eip.pod_subnet_snat[0].address, "")
  description = "Pod subnet SNAT EIP when pod_subnet_enable_snat=true and container_network_type=eni."
}
