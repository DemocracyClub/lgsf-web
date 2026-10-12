#!/usr/bin/env bash
set -xeE

# Ensure gunicorn is on the right port
sudo sed "s/127.0.0.1/0.0.0.0/g" /etc/systemd/system/lgsf_web_gunicorn.service -i
sudo systemctl daemon-reload

# enabling will allow the services to start if the instance reboots
systemctl enable lgsf_web_gunicorn.service
systemctl start lgsf_web_gunicorn.service
