#!/usr/bin/env bash
set -xeE


cd /var/www/lgsf_web/code/
. .venv/bin/activate
python manage.py collectstatic --noinput --clear
