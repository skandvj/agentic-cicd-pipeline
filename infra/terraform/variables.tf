variable "environment" {
  description = "Deployment environment, such as staging or prod."
  type        = string
  default     = "staging"
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "task_cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate task memory MiB."
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "Runtime task count."
  type        = number
  default     = 2
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "Allocated RDS storage in GiB."
  type        = number
  default     = 20
}

variable "db_username" {
  description = "Database username, normally supplied from Secrets Manager."
  type        = string
  sensitive   = true
}

variable "db_password" {
  description = "Database password, normally supplied from Secrets Manager."
  type        = string
  sensitive   = true
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 14
}

