#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y fontconfig openjdk-21-jre curl wget gnupg unzip git python3
sudo install -d -m 0755 /etc/apt/keyrings
sudo wget -q -O /etc/apt/keyrings/jenkins-keyring.asc https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key
printf '%s\n' 'deb [signed-by=/etc/apt/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/' | sudo tee /etc/apt/sources.list.d/jenkins.list >/dev/null
sudo apt-get update
sudo apt-get install -y jenkins
sudo install -d /etc/systemd/system/jenkins.service.d
printf '[Service]\nEnvironment="JENKINS_LISTEN_ADDRESS=127.0.0.1"\n' | sudo tee /etc/systemd/system/jenkins.service.d/listen.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now jenkins
sudo systemctl restart jenkins
java -version
printf '%s\n' 'Jenkins listens on localhost:8080. Use an SSH tunnel to open the setup wizard.'
