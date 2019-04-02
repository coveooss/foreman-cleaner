import click
import datetime
import os
import json
from foreman.client import Foreman
from foremanproxy import ForemanProxy
from awsutils import get_ec2_instance_state, AwsDs
import ldap
import re
import socket
from subprocess import check_output
import logging
import sys
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

# Retrieve config from ENV
FOREMAN_URL = os.environ.get('FOREMAN_URL')
FOREMAN_USER = os.environ.get('FOREMAN_USER')
FOREMAN_PASSWORD = os.environ.get('FOREMAN_PASSWORD')
FOREMAN_PROXY_URL = "https://{}:{}".format(os.environ.get(
    'FOREMANPROXY_HOST'), os.getenv('FOREMANPROXY_PORT', '8443'))
DELAY = os.getenv('FOREMAN_CLEAN_DELAY', '1')
LDAP_HOST = os.environ.get('LDAP_HOST')
COMPUTERS_BASE_DN = os.environ.get('COMPUTER_DN')
BIND_USER_DN = os.environ.get('DS_USER')
BIND_PASSWORD = os.environ.get('DS_PASSWORD')
PROMETHEUS_ENDPOINT = os.environ.get('PROMETHEUS_ENDPOINT')


def foreman_wrapper(foreman_call, call_args=None):
    last_len = 1
    args = call_args or {}

    if "kwargs" in call_args:
        args['kwargs']['page'] = 1
    else:
        args['page'] = 1

    result = foreman_call(**args)['results']
    while last_len > 0:
        if "kwargs" in call_args:
            args['kwargs']['page'] += 1
        else:
            args['page'] += 1
        tmp_result = foreman_call(**args)['results']
        last_len = len(tmp_result)

        if isinstance(tmp_result, dict):
            result.update(tmp_result)
        else:
            result += tmp_result
    return result


def build_from_cn(cn):
    return "{}.{}".format(cn.lower(), LDAP_HOST.lower())


def push_metrics(metrics_dict):
    registry = CollectorRegistry()
    for name, config in metrics_dict.items():
        g = Gauge("foreman_cleaner_{}".format(name), config['description'], registry=registry, labelnames=["instance"])
        g.labels(instance='k8s-foreman-cleaner').set_to_current_time()
        g.labels(instance='k8s-foreman-cleaner').set(config["value"])
        push_to_gateway(PROMETHEUS_ENDPOINT, job="foreman_cleaner", registry=registry)


@click.group()
def main():
    pass


@main.command()
@click.option("--check_on_fs", default=False, help="Check on /var/lib/puppet/ssl/ca/signed/ to get the certificate list")
@click.option("--json_file", default=None, help="Path to json file with the list on certificater to delete")
def clean_old_certificates(json_file, check_on_fs):
    """ This method that will clear all puppet cert for instances that do not still exist """
    logging.info("########## Start Cleaning ###########")
    # connect to Foreman and ForemanProxy
    f = Foreman(FOREMAN_URL, (FOREMAN_USER, FOREMAN_PASSWORD), api_version=2)
    fp = ForemanProxy(FOREMAN_PROXY_URL)

    host_pattern = ['ndev', 'nsta', 'nifd', 'npra',
                    'nifp-es5k', 'nhip', 'nifh', 'win', 'nprd', 'nqa']
    if not json_file and check_on_fs:
        jcerts = check_output(
            ["ls", "-f", "/var/lib/puppet/ssl/ca/signed/"]).split()
    elif not json_file and not check_on_fs:
        fp_certs = fp.get_certificates()
        jcerts = [c for c in fp_certs if fp_certs[c].get('state') == 'valid']
    else:
        try:
            with open(json_file) as data_file:
                jcerts = json.load(data_file)
        except Exception as e:
            print("Cant't decode json file: {}".format(e))
            sys.exit(0)
    certs = [cert.replace(".pem", "") for cert in jcerts if any(
        pattern in cert for pattern in host_pattern)]
    foreman_hosts = []

    result = foreman_wrapper(f.index_hosts, call_args={"per_page": 1000})
    for host in result:
        foreman_hosts.append(host["certname"])

    certs_to_delete = list(set(certs) - set(foreman_hosts))

    for cert in certs_to_delete:
        try:
            print(" {} will be deleted".format(cert))
            fp.delete_certificate(cert)

        except Exception as e:
            print(" {} couldn't be deleted: {}".format(cert, e))


@main.command()
def clean_ds():
    """ This is a 'one time use' method that will clear from the DS all instances that doesn't still exist """
    # Retrieve config from ENV

    # Stats
    saved = 0
    deleted = 0

    # connect to Foreman and ForemanProxy
    f = Foreman(FOREMAN_URL, (FOREMAN_USER, FOREMAN_PASSWORD), api_version=2)

    # Connect to the DS
    try:
        ds = AwsDs(LDAP_HOST, COMPUTERS_BASE_DN, BIND_USER_DN, BIND_PASSWORD)
    except ldap.INVALID_CREDENTIALS:
        raise "Your username or password is incorrect."

    # Get all host from foreman
    page = 1
    result = []
    last_len = 1

    while last_len > 0:
        tmp_result = f.index_hosts(per_page="1000", page=str(page))['results']
        last_len = len(tmp_result)
        page += 1
        result += tmp_result
    foreman_hosts = {host["certname"]: host["ip"] for host in result}

    # Get all ds computer
    ds_computers = []

    for c_dn, attr in ds.computers:
        if 'dNSHostName' in attr and re.match('.*\.cloud\.coveo\.com$', attr['dNSHostName'][0]):
            ds_computers.append(attr['dNSHostName'][0].lower())
            continue
        else:
            ds_computers.append(build_from_cn(attr['cn'][0]))

    to_delete = ds_computers

    """
    to_delete = []

    # (Optional) filter which instances should be cleaned
    for ds_computer in ds_computers:
        if re.match('^npra-al.*', ds_computer) or re.match('^npra-aw.*', ds_computer):
            to_delete.append(ds_computer)
    """

    # Exlude host that exist in foreman to the list of instances retrieve from the DS
    for foreman_host in foreman_hosts.keys():
        for i, ds_computer in enumerate(to_delete):
            if re.match('^{}.*'.format(foreman_host), ds_computer):
                del to_delete[i]

    for host in to_delete:
        try:
            ip_address = socket.gethostbyname(host)
            found = True
        except:
            found = False

        # Make the following 2 call only at the end in order to avoid useless consuming API call
        try:
            if found:
                is_terminated = (get_ec2_instance_state(
                    '', ip=ip_address) == 'terminated')
                if not is_terminated:
                    print("{} is not terminated, ignoring this instance".format(host))
                    saved += 1
                    continue
            logging.info("I will destroy the server {}".format(host))
            # remove host in the DS
            ds.delete_computer(host)
            deleted += 1
        except Exception as e:
            logging.error("Something went wrong : {}".format(e))
    logging.info("{} instances deleted\n{} instances saved\n{} instances in foreman\n".format(
        deleted, saved, len(foreman_hosts)))


@main.command()
def clean_old_host():
    """ Method call by cron to clean instances """
    logging.info("########## Start Cleaning ###########")

    metrics = {
        'hosts_ok': {
            'description': 'count of hosts which have a report in the defined delay',
            'value': 0
        },
        'hosts_deleted': {
            'description': 'count of hosts successfully deleted from foreman puppet and ds',
            'value': 0
        },
        'hosts_skipped': {
            'description': 'count of hosts skipped because they are still in EC2',
            'value': 0
        },
        'hosts_delete_failed': {
            'description': 'count hosts unsuccessfully deleted from foreman puppet and ds',
            'value': 0
        },
    }

    # connect to Foreman and ForemanProxy
    f = Foreman(FOREMAN_URL, (FOREMAN_USER, FOREMAN_PASSWORD), api_version=2)
    fp = ForemanProxy(FOREMAN_PROXY_URL)

    # Connect to the DS
    try:
        ds = AwsDs(LDAP_HOST, COMPUTERS_BASE_DN, BIND_USER_DN, BIND_PASSWORD)
    except ldap.INVALID_CREDENTIALS:
        raise "Your username or password is incorrect."

    # Get the the current date
    currentdate = datetime.datetime.utcnow()

    # check for all host
    instance_id_dict = foreman_wrapper(f.do_get, call_args={'url': '/api/fact_values?&search=+name+%3D+ec2_instance_id',
                                                            'kwargs': {'per_page': 1000}})
    result = foreman_wrapper(f.index_hosts, call_args={"per_page": 1000})
    for host in result:
        # get the compile date
        lastcompile = None
        if host["last_compile"]:
            lastcompile = host["last_compile"]
        elif host["last_report"]:
            lastcompile = host["last_report"]
        elif host["created_at"]:
            lastcompile = host["created_at"]

        # Convert the string date to datetime format
        if not host["last_compile"] and not host["last_report"] and host["created_at"]:
            logging.info("Can't retrieve last compile/report date for {}, will use create time ({})".format(
                host["certname"], host["created_at"]))

        hostdate = datetime.datetime.strptime(
            lastcompile, '%Y-%m-%dT%H:%M:%S.%fZ')
        # Get the delta between the last puppet repport and the current date
        elapsed = currentdate - hostdate
        # if the deta is more than $delay days we delete the host
        if elapsed > datetime.timedelta(hours=int(DELAY)):
            # Make the following 2 call only at the end in order to avoid useless consuming API call
            try:
                instance_id = instance_id_dict[host['name']]['ec2_instance_id']
                is_terminated = (get_ec2_instance_state(
                    instance_id) == 'terminated')
            except KeyError:
                if host['ip']:
                    is_terminated = (get_ec2_instance_state(
                        '', ip=host['ip']) == 'terminated')
                elif host['mac']:
                    is_terminated = (get_ec2_instance_state(
                        '', ip=host['ip'], mac=host['mac']) == 'terminated')
                else:
                    logging.warning(
                        "Can't retrieve EC2 id or ip, skipping {}".format(host["certname"]))
                    metrics["hosts_skipped"]["value"] += 1
                    continue
            except Exception as e:
                logging.warning(
                    "Can't retrieve EC2 state, skipping {} : {}".format(host["certname"], e))
                metrics["hosts_skipped"]["value"] += 1
                continue

            if is_terminated:
                try:
                    logging.info("I will destroy the server {} because the last report was {}".format(
                        host["certname"], str(lastcompile)))
                    # destroy the host in foreman
                    f.destroy_hosts(id=host["id"])
                    # remove the certificate in puppet
                    fp.delete_certificate(host["certname"])
                    # remove host in the DS
                    ds.delete_computer(host["certname"])
                    metrics["hosts_deleted"]["value"] += 1
                except Exception as e:
                    logging.error("Something went wrong : {}".format(e))
                    metrics["hosts_delete_failed"]["value"] += 1
            else:
                metrics["hosts_skipped"]["value"] += 1
        else:
            metrics["hosts_ok"]["value"] += 1
            logging.debug("{} OK: Last puppet's run : {}".format(
                host["certname"], lastcompile))

    push_metrics(metrics)


# Read option
if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    main()
