#!/bin/bash

set -e

# Create Certificate
puppet agent --noop --server=$FOREMANPROXY_HOST

# Get env variable for cronjob
env | grep FOREMAN | sed 's/^\(.*\)$/export \1/g' > /root/envs.sh
chmod +x /root/envs.sh

# Add cron for clean
echo "0 * * * * . /root/envs.sh; python -W ignore /install/host-cleaner.py clean_old_host >> /var/log/cron.log" >> /var/spool/cron/crontabs/root
service cron restart

exec "$@"