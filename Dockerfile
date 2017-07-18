FROM ubuntu:16.04

LABEL maintainer "coveo"

# Install requierements
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y wget cron python puppet
    
RUN service puppet stop && systemctl disable puppet

# Create install dir and clean apt cache
RUN mkdir /install && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN pip install baker foreman requests

COPY files/install /install
RUN chmod +x /install/entrypoint.sh

ENTRYPOINT ["/install/entrypoint.sh"]
CMD ["tailf", "/var/logs/cron.log"]
