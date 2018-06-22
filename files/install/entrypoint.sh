#!/bin/bash

# Create Certificate
puppet agent --noop --server=$FOREMANPROXY_HOST

# Get env variable for cronjob
env | grep -E 'AWS|FOREMAN|DS|LDAP|COMPUTER_DN' | sed 's/^\(.*\)$/export \1/g' > /root/envs.sh
chmod +x /root/envs.sh

# Add cron for clean
echo "0 * * * * root . /root/envs.sh; /usr/bin/python -W ignore /install/host-cleaner.py clean_old_host > /proc/1/fd/1" >> /etc/cron.d/foreman-cleaner
# Add cron to clean all old certificates 
echo "30 11 * * * root . /root/envs.sh; /usr/bin/python -W ignore /install/host-cleaner.py clean_old_certificates > /proc/1/fd/1" >> /etc/cron.d/foreman-cleaner
# Add cron to clean DS leftovers
echo "30 6 * * * root . /root/envs.sh; /usr/bin/python -W ignore /install/host-cleaner.py clean_ds > /proc/1/fd/1" >> /etc/cron.d/foreman-cleaner
# Add cron to autoheal approbation relation between windows and DS
echo "30 * * * * root . /root/envs.sh; /usr/bin/python -W ignore /install/check_windows.py check_join -c /install/config.yaml > /proc/1/fd/1" >> /etc/cron.d/foreman-cleaner
service cron restart && tail -f /var/log/cron.log