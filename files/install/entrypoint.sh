#!/bin/bash

# Create Certificate
puppet agent --noop --server=$FOREMANPROXY_HOST

# Add cron for clean
echo "* */1 * * * python -W ignore /install/host-cleaner.py clean_old_host > /var/logs/cron.log" >> /var/spool/cron/crontabs/root
service cron start