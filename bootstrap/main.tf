# Jenkins deployment identity. PowerUserAccess covers every service except IAM;
# the inline policy allows IAM only on roles and instance profiles named "<prefix>-*",
# and only with the three AWS managed policies this project attaches, so the
# pipeline cannot grant itself broader access.
resource "aws_iam_user" "jenkins" {
  name = "${var.prefix}-jenkins"
}
resource "aws_iam_user_policy_attachment" "power_user" {
  user       = aws_iam_user.jenkins.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}
locals {
  role_arn    = "arn:aws:iam::${var.account_id}:role/${var.prefix}-*"
  profile_arn = "arn:aws:iam::${var.account_id}:instance-profile/${var.prefix}-*"
  attachable_policies = [
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
    "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup",
    "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores",
  ]
}
resource "aws_iam_user_policy" "scoped_iam" {
  name = "${var.prefix}-scoped-iam"
  user = aws_iam_user.jenkins.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ProjectRoles"
        Effect   = "Allow"
        Resource = local.role_arn
        Action = [
          "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:UpdateRole", "iam:TagRole", "iam:UntagRole",
          "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole", "iam:PassRole",
        ]
      },
      {
        Sid       = "ProjectRolePolicies"
        Effect    = "Allow"
        Resource  = local.role_arn
        Action    = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
        Condition = { ArnEquals = { "iam:PolicyARN" = local.attachable_policies } }
      },
      {
        Sid      = "ProjectInstanceProfiles"
        Effect   = "Allow"
        Resource = local.profile_arn
        Action = [
          "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile", "iam:GetInstanceProfile",
          "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile", "iam:TagInstanceProfile", "iam:UntagInstanceProfile",
        ]
      },
    ]
  })
}
output "jenkins_user" { value = aws_iam_user.jenkins.name }
output "next_step" {
  value = "Create an access key for ${aws_iam_user.jenkins.name} in the IAM console and store it only in Jenkins credentials."
}
