#!/bin/bash

# Create Certificate
puppet agent --noop --server=$FOREMANPROXY_HOST

# Get env variable for cronjob
env | grep FOREMAN | sed 's/^\(.*\)$/export \1/g' > /root/envs.sh
chmod +x /root/envs.sh

# Add cron for clean
echo "0 * * * * root . /root/envs.sh; /usr/bin/python -W ignore /install/host-cleaner.py clean_old_host > /proc/1/fd/1" >> /etc/cron.d/foreman-cleaner

service cron restart && tail -f /var/log/cron.log