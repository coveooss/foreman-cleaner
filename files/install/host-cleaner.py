import baker
import datetime
import os
import json
from foreman.client import Foreman
from foremanproxy import ForemanProxy
from awsutils import get_ec2_instance_state, AwsDs
import ldap
import re


@baker.command()
def clean_old_certificates(json_file=None):
    """ This is a 'one time use' method that will clear all puppet cert for instances that doesn't still exist """
    # Retrieve config from ENV
    foreman_url = os.environ.get('FOREMAN_URL')
    foreman_user = os.environ.get('FOREMAN_USER')
    foreman_password = os.environ.get('FOREMAN_PASSWORD')
    foreman_proxy_url = "https://{}:{}".format(os.environ.get('FOREMANPROXY_HOST'), os.getenv('FOREMANPROXY_PORT','8443'))

    # connect to Foreman and ForemanProxy
    f=Foreman(foreman_url, (foreman_user, foreman_password))
    fp = ForemanProxy(foreman_proxy_url)

    # Build a certificates list with only hostcert, discarding specific certs used for foreman, puppet, etc ...
    host_pattern = ['ndev', 'nsta', 'nifd', 'npra', 'nifp', 'nhip', 'nifh', 'win']
    if not json_file:
        certs = fp.get_certificates().keys()
    else:
        try:
            with open(json_file) as data_file:
                certs = json.load(data_file)
        except:
            print("Cant't decode json file")
    certs = [cert for cert in certs if any(pattern in cert for pattern in host_pattern)]
    foreman_hosts = []

    # Get all host in foreman
    get_next_page = True
    page = 1
    while get_next_page:
        result = f.index_hosts(per_page="1000", page=str(page))
        if len(result) == 1000:
            page += 1
        else:
            get_next_page = False
        for host in result:
            foreman_hosts.append(host["host"]["name"])

    certs_to_delete = list(set(certs) - set(foreman_hosts))

    for cert in certs_to_delete:
        print(" {} will be deleted".format(cert))
        try:
            fp.delete_certificate(cert)
        except:
            print(" {} couldn't be deleted".format(cert))


@baker.command()
def clean_ds():
    """ This is a 'one time use' method that will clear from the DS all instances that doesn't still exist """
    # Retrieve config from ENV
    foreman_url = os.environ.get('FOREMAN_URL')
    foreman_user = os.environ.get('FOREMAN_USER')
    foreman_password = os.environ.get('FOREMAN_PASSWORD')
    delay = os.getenv('FOREMAN_CLEAN_DELAY', '1')
    ldap_host = os.environ.get('LDAP_HOST')
    computers_base_dn = os.environ.get('COMPUTER_DN')
    bind_user_dn = os.environ.get('DS_USER')
    bind_password = os.environ.get('DS_PASSWORD')

    # connect to Foreman and ForemanProxy
    f=Foreman(foreman_url, (foreman_user, foreman_password), api_version=2)

    # Connect to the DS
    try:
        ds = AwsDs(ldap_host, computers_base_dn ,bind_user_dn, bind_password)
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
    foreman_hosts = [host["certname"] for host in result]

    # Get all ds computer
    ds_computers = [attr['dNSHostName'][0].lower() for c_dn, attr in ds.computers if 'dNSHostName' in attr]
    to_delete = []

    # (Optional) filter which instances should be cleaned
    for ds_computer in ds_computers:
        if re.match('^ndev-al.*', ds_computer):
            to_delete.append(ds_computer)
        elif re.match('^ndev-aw.*', ds_computer):
            to_delete.append(ds_computer)

    # Exlude host that exist in foreman to the list of instances retrieve from the DS
    for foreman_host in foreman_hosts:
        for i, ds_computer in enumerate(to_delete):
            if re.match('^{}.*'.format(foreman_host), ds_computer):
                del to_delete[i]

    for host in to_delete:
        # Make the following 2 call only at the end in order to avoid useless consuming API call
        try:
            print "I will destroy the server "+host
            # remove host in the DS
            ds.delete_computer(host)
        except Exception as e:
            print("Something went wrong : {}".format(e))


@baker.command()
def clean_old_host():
    """ Method call by cron to clean instances """
    # Retrieve config from ENV
    foreman_url = os.environ.get('FOREMAN_URL')
    foreman_user = os.environ.get('FOREMAN_USER')
    foreman_password = os.environ.get('FOREMAN_PASSWORD')
    foreman_proxy_url = "https://{}:{}".format(os.environ.get('FOREMANPROXY_HOST'), os.getenv('FOREMANPROXY_PORT','8443'))
    delay = os.getenv('FOREMAN_CLEAN_DELAY', '1')
    ldap_host = os.environ.get('LDAP_HOST')
    computers_base_dn = os.environ.get('COMPUTER_DN')
    bind_user_dn = os.environ.get('DS_USER')
    bind_password = os.environ.get('DS_PASSWORD')

    # connect to Foreman and ForemanProxy
    f=Foreman(foreman_url, (foreman_user, foreman_password), api_version=2)
    fp = ForemanProxy(foreman_proxy_url)

    # Connect to the DS
    try:
        ds = AwsDs(ldap_host, computers_base_dn ,bind_user_dn, bind_password)
    except ldap.INVALID_CREDENTIALS:
        raise "Your username or password is incorrect."

    # Get the the current date
    currentdate = datetime.datetime.utcnow()

    # check for all host
    page = 1
    result = []
    last_len = 1
    while last_len > 0:
        tmp_result = f.index_hosts(per_page="1000", page=str(page))['results']
        last_len = len(tmp_result)
        page += 1
        result += tmp_result

    for host in result:
        # get the compile date
        lastcompile = f.show_hosts(id=host["id"])["last_compile"]
        # Convert the string date to datetime format
        if not lastcompile:
            print("Can't retrieve last compile date, skipping {}".format(host["certname"]))
            continue

        hostdate = datetime.datetime.strptime(lastcompile, '%Y-%m-%dT%H:%M:%S.%fZ')
        # Get the delta between the last puppet repport and the current date
        elapsed = currentdate - hostdate
        # if the deta is more than $delay days we delete the host
        if elapsed > datetime.timedelta(hours=int(delay)):
            # Make the following 2 call only at the end in order to avoid useless consuming API call
            try:
                instance_id = f.do_get('/api/hosts/{}/facts'.format(host["id"]), {"search": "ec2_instance_id"})['results'][host["name"]]["ec2_instance_id"]
                is_terminated = (get_ec2_instance_state(instance_id) == 'terminated')
            except Exception as e:
                print("Can't retrieve EC2 state, skipping {} : {}".format(host["certname"], e))
                continue
            if is_terminated:
                try:
                    print("I will destroy the server {} because the last report was {}".format(host["certname"], str(lastcompile)))
                    # destroy the host in foreman
                    f.destroy_hosts(id=host["id"])
                    # remove the certificate in puppet
                    fp.delete_certificate(host["certname"])
                    # remove host in the DS
                    ds.delete_computer(host["certname"])
                except Exception as e:
                    print("Something went wrong : {}".format(e))

# Read option
if __name__ == "__main__":
  baker.run()