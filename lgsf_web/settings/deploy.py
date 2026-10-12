# deploy.py
# The default settings entrypoint
# Set things here that we want to be true in ALL deployed environments
# but don't make sense in local dev

import requests

from .base import *

DEBUG = False
DATABASES["default"]["CONN_MAX_AGE"] = 60


def get_ec2_ip():
    token_req = requests.put(
        "http://169.254.169.254/latest/api/token",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
        timeout=2,
    )
    token_req.raise_for_status()
    ip_req = requests.get(
        "http://169.254.169.254/latest/meta-data/local-ipv4",
        headers={"X-aws-ec2-metadata-token": token_req.text},
        timeout=2,
    )
    ip_req.raise_for_status()
    return ip_req.text


EC2_IP = get_ec2_ip()
ALLOWED_HOSTS.append(EC2_IP)
