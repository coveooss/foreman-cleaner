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

# Retrieve config from ENV
foreman_url = os.environ.get('FOREMAN_URL')
foreman_user = os.environ.get('FOREMAN_USER')
foreman_password = os.environ.get('FOREMAN_PASSWORD')
foreman_proxy_url = "https://{}:{}".format(os.environ.get(
    'FOREMANPROXY_HOST'), os.getenv('FOREMANPROXY_PORT', '8443'))
delay = os.getenv('FOREMAN_CLEAN_DELAY', '1')
ldap_host = os.environ.get('LDAP_HOST')
computers_base_dn = os.environ.get('COMPUTER_DN')
bind_user_dn = os.environ.get('DS_USER')
bind_password = os.environ.get('DS_PASSWORD')


@click.group()
def main():
    pass


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


@main.command()
@click.option("--check_on_fs", default=False, help="Check on /var/lib/puppet/ssl/ca/signed/ to get the certificate list")
@click.option("--json_file", default=None, help="Path to json file with the list on certificater to delete")
def clean_old_certificates(json_file, check_on_fs):
    """ This method that will clear all puppet cert for instances that do not still exist """
    logging.info("########## Start Cleaning ###########")
    # connect to Foreman and ForemanProxy
    f = Foreman(foreman_url, (foreman_user, foreman_password), api_version=2)
    fp = ForemanProxy(foreman_proxy_url)

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
    foreman_url = os.environ.get('FOREMAN_URL')
    foreman_user = os.environ.get('FOREMAN_USER')
    foreman_password = os.environ.get('FOREMAN_PASSWORD')
    ldap_host = os.environ.get('LDAP_HOST')
    computers_base_dn = os.environ.get('COMPUTER_DN')
    bind_user_dn = os.environ.get('DS_USER')
    bind_password = os.environ.get('DS_PASSWORD')

    # Stats
    saved = 0
    deleted = 0

    # connect to Foreman and ForemanProxy
    f = Foreman(foreman_url, (foreman_user, foreman_password), api_version=2)

    # Connect to the DS
    try:
        ds = AwsDs(ldap_host, computers_base_dn, bind_user_dn, bind_password)
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
    ds_computers = [attr['dNSHostName'][0].lower()
                    for c_dn, attr in ds.computers if 'dNSHostName' in attr]
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

    # connect to Foreman and ForemanProxy
    f = Foreman(foreman_url, (foreman_user, foreman_password), api_version=2)
    fp = ForemanProxy(foreman_proxy_url)

   # Connect to the DS
    try:
        ds = AwsDs(ldap_host, computers_base_dn, bind_user_dn, bind_password)
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
        if elapsed > datetime.timedelta(hours=int(delay)):
            # Make the following 2 call only at the end in order to avoid useless consuming API call
            try:
                instance_id = instance_id_dict[host['name']]['ec2_instance_id']
                is_terminated = (get_ec2_instance_state(
                    instance_id) == 'terminated')
            except KeyError:
                if host['ip']:
                    is_terminated = (get_ec2_instance_state(
                        '', ip=host['ip']) == 'terminated')
                else:
                    logging.warning(
                        "Can't retrieve EC2 id or ip, skipping {}".format(host["certname"]))
                    continue
            except Exception as e:
                logging.warning(
                    "Can't retrieve EC2 state, skipping {} : {}".format(host["certname"], e))
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
                except Exception as e:
                    logging.error("Something went wrong : {}".format(e))
        else:
            logging.debug("{} OK: Last puppet's run : {}".format(
                host["certname"], lastcompile))


# Read option
if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    main()
