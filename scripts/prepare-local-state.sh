#!/usr/bin/env bash
set -euo pipefail
TASK_OWNER=${1:-jenkins}
TASK_GROUP=$(id -gn "$TASK_OWNER")
sudo install -d -m 0700 -o "$TASK_OWNER" -g "$TASK_GROUP" /var/lib/jenkins/terraform-state /var/lib/jenkins/terraform-state/kt-aws-lab /var/lib/jenkins/terraform-state/kt-aws-lab/backups
printf '%s\n' 'Local state directory created. Assign terraform-local only to this persistent agent.'
