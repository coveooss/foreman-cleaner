FROM ubuntu:16.04

LABEL maintainer "coveo"

# Install requierements
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y wget \
        cron python puppet python-setuptools python-dev build-essential \
        libsasl2-dev libldap2-dev libssl-dev && \
    easy_install pip

RUN service puppet stop && systemctl disable puppet

# Create install dir and clean apt cache
RUN mkdir /install && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* && \
    touch /var/log/cron.log

RUN pip install baker python-foreman requests python-ldap boto3

COPY files/install /install
RUN chmod +x /install/entrypoint.sh

CMD ["/install/entrypoint.sh"]
