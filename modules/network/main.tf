terraform {
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}
data "aws_availability_zones" "this" {
  state = "available"
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}
locals {
  azs   = slice(data.aws_availability_zones.this.names, 0, 2)
  tiers = { public = 0, web = 10, app = 20, db = 30 }
  subnets = merge([for tier, base in local.tiers : {
    for i in range(2) : "${tier}-${i}" => { tier = tier, az = i, netnum = base + i }
  }]...)
}
resource "aws_vpc" "this" {
  cidr_block           = var.cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "vpc-${var.name}" }
}
resource "aws_subnet" "this" {
  for_each                = local.subnets
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.cidr, 8, each.value.netnum)
  availability_zone       = local.azs[each.value.az]
  map_public_ip_on_launch = false
  tags                    = { Name = "snet-${var.name}-${each.key}", tier = each.value.tier }
}
resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "igw-${var.name}" }
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = { Name = "rt-${var.name}-public" }
}
resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.this["public-${count.index}"].id
  route_table_id = aws_route_table.public.id
}
resource "aws_eip" "nat" {
  count  = var.enable_nat ? 2 : 0
  domain = "vpc"
  tags   = { Name = "eip-${var.name}-nat-${count.index}" }
}
resource "aws_nat_gateway" "this" {
  count         = var.enable_nat ? 2 : 0
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.this["public-${count.index}"].id
  tags          = { Name = "nat-${var.name}-${count.index}" }
  depends_on    = [aws_internet_gateway.this]
}
# One private route table per zone so a zone keeps its own NAT path.
resource "aws_route_table" "private" {
  count  = 2
  vpc_id = aws_vpc.this.id
  tags   = { Name = "rt-${var.name}-private-${count.index}" }
}
resource "aws_route" "private_nat" {
  count                  = var.enable_nat ? 2 : 0
  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[count.index].id
}
resource "aws_route_table_association" "private" {
  for_each       = { for k, v in local.subnets : k => v if contains(["web", "app"], v.tier) }
  subnet_id      = aws_subnet.this[each.key].id
  route_table_id = aws_route_table.private[each.value.az].id
}
# The database subnets have no internet route.
resource "aws_route_table" "db" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "rt-${var.name}-db" }
}
resource "aws_route_table_association" "db" {
  count          = 2
  subnet_id      = aws_subnet.this["db-${count.index}"].id
  route_table_id = aws_route_table.db.id
}
resource "aws_security_group" "this" {
  for_each    = toset(["alb", "web", "internal_alb", "app", "db", "bastion"])
  name        = "${var.name}-${replace(each.key, "_", "-")}"
  description = "Kantin Tongue ${replace(each.key, "_", " ")} tier"
  vpc_id      = aws_vpc.this.id
  tags        = { Name = "sg-${var.name}-${replace(each.key, "_", "-")}" }
}
locals {
  # Tier-to-tier rules. The bastion has no inbound rule; operators reach it through SSM Session Manager.
  ingress = {
    web_http_alb     = { sg = "web", port = 80, from = "alb" }
    web_ssh_bastion  = { sg = "web", port = 22, from = "bastion" }
    ialb_http_web    = { sg = "internal_alb", port = 8080, from = "web" }
    app_http_ialb    = { sg = "app", port = 8080, from = "internal_alb" }
    app_ssh_bastion  = { sg = "app", port = 22, from = "bastion" }
    db_postgres_app  = { sg = "db", port = 5432, from = "app" }
    db_postgres_host = { sg = "db", port = 5432, from = "bastion" }
  }
  egress = {
    alb_web     = { sg = "alb", port = 80, to = "web" }
    web_ialb    = { sg = "web", port = 8080, to = "internal_alb" }
    ialb_app    = { sg = "internal_alb", port = 8080, to = "app" }
    app_db      = { sg = "app", port = 5432, to = "db" }
    bastion_web = { sg = "bastion", port = 22, to = "web" }
    bastion_app = { sg = "bastion", port = 22, to = "app" }
    bastion_db  = { sg = "bastion", port = 5432, to = "db" }
  }
}
resource "aws_vpc_security_group_ingress_rule" "tier" {
  for_each                     = local.ingress
  security_group_id            = aws_security_group.this[each.value.sg].id
  referenced_security_group_id = aws_security_group.this[each.value.from].id
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
  description                  = replace(each.key, "_", " ")
}
# The public ALB only accepts CloudFront's origin-facing address ranges.
resource "aws_vpc_security_group_ingress_rule" "alb_cloudfront" {
  security_group_id = aws_security_group.this["alb"].id
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "HTTP from CloudFront origin-facing ranges"
}
resource "aws_vpc_security_group_egress_rule" "tier" {
  for_each                     = local.egress
  security_group_id            = aws_security_group.this[each.value.sg].id
  referenced_security_group_id = aws_security_group.this[each.value.to].id
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
  description                  = replace(each.key, "_", " ")
}
# Instances need HTTP/HTTPS through NAT for packages and the SSM agent, and reach tiers inside the VPC.
resource "aws_vpc_security_group_egress_rule" "internet" {
  for_each          = { for pair in setproduct(["web", "app", "bastion"], [80, 443]) : "${pair[0]}-${pair[1]}" => { sg = pair[0], port = pair[1] } }
  security_group_id = aws_security_group.this[each.value.sg].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = each.value.port
  to_port           = each.value.port
  description       = "Outbound ${each.value.port} through NAT or IGW"
}
output "vpc_id" { value = aws_vpc.this.id }
output "availability_zones" { value = local.azs }
output "subnet_ids" {
  value = { for tier in keys(local.tiers) : tier => [for i in range(2) : aws_subnet.this["${tier}-${i}"].id] }
}
output "security_group_ids" { value = { for k, v in aws_security_group.this : k => v.id } }
output "nat_public_ips" { value = aws_eip.nat[*].public_ip }
