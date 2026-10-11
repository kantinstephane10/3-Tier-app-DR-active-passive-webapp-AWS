terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}
data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}
resource "aws_iam_role" "instance" {
  name = "${var.name}-instance"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" } }]
  })
}
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_instance_profile" "instance" {
  name = "${var.name}-instance"
  role = aws_iam_role.instance.name
}
resource "aws_lb" "public" {
  name                       = "alb-${var.name}"
  load_balancer_type         = "application"
  internal                   = false
  security_groups            = [var.security_group_ids["alb"]]
  subnets                    = var.subnet_ids["public"]
  drop_invalid_header_fields = true
}
resource "aws_lb_target_group" "web" {
  name        = "tg-${var.name}-web"
  port        = 80
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "instance"
  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 10
    unhealthy_threshold = 3
  }
}
resource "aws_lb_listener" "public" {
  load_balancer_arn = aws_lb.public.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }
}
# Only requests carrying CloudFront's secret origin header reach the web tier.
resource "aws_lb_listener_rule" "cloudfront" {
  listener_arn = aws_lb_listener.public.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [var.origin_secret]
    }
  }
}
resource "aws_lb" "internal" {
  name                       = "ialb-${var.name}"
  load_balancer_type         = "application"
  internal                   = true
  security_groups            = [var.security_group_ids["internal_alb"]]
  subnets                    = var.subnet_ids["app"]
  drop_invalid_header_fields = true
}
resource "aws_lb_target_group" "app" {
  name        = "tg-${var.name}-app"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "instance"
  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 10
    unhealthy_threshold = 3
  }
}
resource "aws_lb_listener" "internal" {
  load_balancer_arn = aws_lb.internal.arn
  port              = 8080
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
locals {
  target_groups = { web = aws_lb_target_group.web.arn, app = aws_lb_target_group.app.arn }
}
resource "aws_launch_template" "tier" {
  for_each               = toset(["web", "app"])
  name                   = "lt-${var.name}-${each.key}"
  image_id               = data.aws_ssm_parameter.ubuntu.insecure_value
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [var.security_group_ids[each.key]]
  update_default_version = true
  user_data = base64encode(templatefile("${path.module}/cloud-init-${each.key}.yaml.tftpl", {
    app_lb            = aws_lb.internal.dns_name
    region            = var.region
    database_endpoint = var.database_endpoint
  }))
  iam_instance_profile { name = aws_iam_instance_profile.instance.name }
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  block_device_mappings {
    device_name = "/dev/sda1"
    ebs {
      volume_type           = "gp3"
      volume_size           = 20
      encrypted             = true
      delete_on_termination = true
    }
  }
  # Provider default tags do not reach instances launched by Auto Scaling.
  tag_specifications {
    resource_type = "instance"
    tags          = merge(var.tags, { Name = "${var.name}-${each.key}", tier = each.key, backup = var.backup_tag })
  }
  tag_specifications {
    resource_type = "volume"
    tags          = merge(var.tags, { Name = "${var.name}-${each.key}", tier = each.key })
  }
}
resource "aws_autoscaling_group" "tier" {
  for_each                  = aws_launch_template.tier
  name                      = "asg-${var.name}-${each.key}"
  min_size                  = var.instances
  max_size                  = var.max_instances
  desired_capacity          = var.instances
  vpc_zone_identifier       = var.subnet_ids[each.key]
  target_group_arns         = [local.target_groups[each.key]]
  health_check_type         = "ELB"
  health_check_grace_period = 600
  launch_template {
    id      = each.value.id
    version = "$Latest"
  }
  instance_refresh {
    strategy = "Rolling"
    preferences { min_healthy_percentage = 50 }
  }
  lifecycle { ignore_changes = [desired_capacity] }
}
resource "aws_autoscaling_policy" "cpu" {
  for_each               = aws_autoscaling_group.tier
  name                   = "cpu-${var.name}-${each.key}"
  autoscaling_group_name = each.value.name
  policy_type            = "TargetTrackingScaling"
  target_tracking_configuration {
    predefined_metric_specification { predefined_metric_type = "ASGAverageCPUUtilization" }
    target_value = 60
  }
}
output "origin_hostname" { value = aws_lb.public.dns_name }
output "internal_lb_hostname" { value = aws_lb.internal.dns_name }
output "autoscaling_groups" { value = { for k, v in aws_autoscaling_group.tier : k => v.name } }
