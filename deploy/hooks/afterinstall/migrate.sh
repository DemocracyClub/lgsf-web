#!/bin/bash
set -euxo pipefail

cd /var/www/lgsf_web/code/
uv run manage.py migrate --noinput
