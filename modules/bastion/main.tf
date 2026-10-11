terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}
data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}
resource "aws_iam_role" "this" {
  name = "${var.name}-bastion"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" } }]
  })
}
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_instance_profile" "this" {
  name = "${var.name}-bastion"
  role = aws_iam_role.this.name
}
# Reached through SSM Session Manager; its security group has no inbound rule.
resource "aws_instance" "this" {
  ami                         = data.aws_ssm_parameter.ubuntu.insecure_value
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [var.security_group_id]
  associate_public_ip_address = true
  key_name                    = var.key_name
  iam_instance_profile        = aws_iam_instance_profile.this.name
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }
  root_block_device {
    volume_type = "gp3"
    volume_size = 10
    encrypted   = true
  }
  tags = { Name = "bastion-${var.name}" }
  # A newer Ubuntu image must not replace the bastion during routine plans.
  lifecycle { ignore_changes = [ami] }
}
output "instance_id" { value = aws_instance.this.id }
