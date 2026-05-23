terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = "agentic-cicd-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name        = "agentic-cicd-public-${count.index}-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name        = "agentic-cicd-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "alb" {
  name        = "agentic-cicd-alb-${var.environment}"
  description = "ALB ingress"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "service" {
  name        = "agentic-cicd-service-${var.environment}"
  description = "Runtime service traffic"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecr_repository" "runtime" {
  name                 = "agentic-cicd-runtime-${var.environment}"
  image_tag_mutability = "MUTABLE"
  force_delete         = var.environment != "prod"
}

resource "aws_ecs_cluster" "runtime" {
  name = "agentic-cicd-${var.environment}"
}

resource "aws_cloudwatch_log_group" "runtime" {
  name              = "/ecs/agentic-cicd-${var.environment}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "task_execution" {
  name = "agentic-cicd-task-execution-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_db_subnet_group" "main" {
  name       = "agentic-cicd-${var.environment}"
  subnet_ids = aws_subnet.public[*].id
}

resource "aws_db_instance" "postgres" {
  identifier             = "agentic-cicd-${var.environment}"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = var.db_instance_class
  allocated_storage      = var.db_allocated_storage
  db_name                = "agentic_cicd"
  username               = var.db_username
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.main.name
  publicly_accessible    = false
  skip_final_snapshot    = var.environment != "prod"
  vpc_security_group_ids = [aws_security_group.service.id]
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "agentic-cicd-${var.environment}"
  subnet_ids = aws_subnet.public[*].id
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id           = "agentic-cicd-${var.environment}"
  engine               = "redis"
  node_type            = var.redis_node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.main.name
  security_group_ids   = [aws_security_group.service.id]
}

resource "aws_lb" "runtime" {
  name               = "agentic-cicd-${var.environment}"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
}

resource "aws_lb_target_group" "runtime" {
  name        = "agentic-cicd-${var.environment}"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.runtime.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.runtime.arn
  }
}

resource "aws_ecs_task_definition" "runtime" {
  family                   = "agentic-cicd-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "runtime"
      image     = "${aws_ecr_repository.runtime.repository_url}:latest"
      essential = true
      portMappings = [{ containerPort = 8000, hostPort = 8000 }]
      environment = [
        { name = "DATABASE_URL", value = "postgresql+psycopg2://${var.db_username}:${var.db_password}@${aws_db_instance.postgres.address}:5432/agentic_cicd" },
        { name = "REDIS_URL", value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/0" },
        { name = "ENVIRONMENT", value = var.environment }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.runtime.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "runtime"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "runtime" {
  name            = "agentic-cicd-runtime-${var.environment}"
  cluster         = aws_ecs_cluster.runtime.id
  task_definition = aws_ecs_task_definition.runtime.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.runtime.arn
    container_name   = "runtime"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]
}

