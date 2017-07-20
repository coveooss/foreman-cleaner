#!/bin/bash

set -e

# Create Certificate
puppet agent --noop --server=$FOREMANPROXY_HOST

# Add cron for clean
echo "0 * * * * python -W ignore /install/host-cleaner.py clean_old_host > /var/log/cron.log" >> /var/spool/cron/crontabs/root
service cron start

exec "$@"