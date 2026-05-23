output "runtime_url" {
  description = "Public runtime load balancer URL."
  value       = "http://${aws_lb.runtime.dns_name}"
}

output "database_endpoint" {
  description = "RDS PostgreSQL endpoint."
  value       = aws_db_instance.postgres.address
  sensitive   = true
}

output "redis_endpoint" {
  description = "ElastiCache Redis endpoint."
  value       = aws_elasticache_cluster.redis.cache_nodes[0].address
}
