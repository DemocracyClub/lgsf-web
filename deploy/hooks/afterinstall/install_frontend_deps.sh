#!/usr/bin/env bash
set -xeE

# should we delete the env and recreate?
cd /var/www/lgsf_web/code/
npm ci
