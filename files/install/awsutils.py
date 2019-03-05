import ldap
import ldap.modlist
import boto3
from botocore.exceptions import ClientError
import re
import os


class NotFound(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, **kwargs)


class TooManyResult(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, **kwargs)


class AwsDs(object):
    def __init__(self, ldap_host, computers_base_dn, bind_user_dn, bind_password, secure=False):
        """
        :param ldap_host: Ldap server hostname or ip
        :param base_dn: The root dn of the directory. Ex: "OU=Computers,DC=example,DC=com"
        :param bind_user_dn: User's dn used to bind with ad. Ex: "uid=toto,ou=users,dc=example,dc=com"
        :param bind_password: User's password for the binding
        :param secure: Use ldap or ldaps (True or False)
        """
        protocol = 'ldap'
        if secure:
            protocol = 'ldaps'

        self._con = ldap.initialize("{}://{}".format(protocol, ldap_host))
        self._con.simple_bind(bind_user_dn, bind_password)

        self.computers_base_dn = computers_base_dn
        self._computers = []

    @property
    def computers(self):
        if not self._computers:
            self._computers = self._con.search_st(self.computers_base_dn, ldap.SCOPE_SUBTREE, '(objectclass=computer)',[], 0, 500)
        return self._computers

    def delete_computer(self, hostname):
        cn = hostname.split('.')[0].upper()
        computer_found = []
        for c_dn, attr in self.computers:
            if 'dNSHostName' in attr and re.match('^{}.*'.format(hostname.lower()), attr['dNSHostName'][0].lower()):
                computer_found.append(attr)
                continue
            elif cn == attr['cn'][0].upper():
                computer_found.append(attr)

        if len(computer_found) > 1:
            raise TooManyResult("There is more than 1 result on DS lookup")
        elif not computer_found:
            raise NotFound("Host not found in DS")
        else:
            print("DS - delete : {} - {}".format(
                computer_found[0]['sAMAccountName'][0], computer_found[0]['distinguishedName'][0]))
            self._con.delete_s(computer_found[0]['distinguishedName'][0])

    def add_computer(self, dn):

        cn = dn.split(",")[0].replace("CN=", "")
        modlist = {
            "objectClass": ['top', 'person', 'organizationalPerson', 'user', 'computer'],
            "cn": cn,
            "displayName": cn+'$',
            "userAccountControl": '4096',
            "SAMAccountName": cn+'$'
        }

        result = self._con.add_s(dn, ldap.modlist.addModlist(modlist))
        return result


def get_ec2_instance_state(instance_id, ip=None, mac=None):
    client = boto3.client('ec2')
    state = 'terminated'
    options = {"InstanceIds": [instance_id]}
    if ip:
        options = {"Filters": [
            {
                'Name': 'private-ip-address',
                'Values': [ip]
            },
        ]}

    try:
        if instance_id or ip:
            rsp = client.describe_instances(**options)
            if rsp['Reservations']:
                state = rsp['Reservations'][0]['Instances'][0]['State']['Name']
        elif mac:
            state = get_eni_status(mac=mac, client=client)
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidInstanceID.NotFound':
            pass
        else:
            raise e
    return state


def get_eni_status(mac, client=None):
    if not client:
        client = boto3.client('ec2')
    state = 'terminated'
    try:
        response = client.describe_network_interfaces(
            Filters=[
                {
                    'Name': 'mac-address',
                    'Values': [mac]
                },
            ]
        )

        state = response["NetworkInterfaces"]["Status"]
    except TypeError:
        pass

    return state


def get_instances_from_ec2(domain_name):
    client = boto3.resource('ec2')
    machine_names = {}

    for instance in client.instances.all():
        name = ''
        if instance.tags:
            for tag in instance.tags:
                if tag['Key'] == 'opsworks:instance':
                    name = tag['Value']
                    break
                elif tag['Key'] == 'Name':
                    name = tag['Value']
            if name:
                machine_names['{}.{}'.format(name.lower(), domain_name)] = \
                    {'status': instance.state['Name'], 'cn': name.lower()}

    return machine_names
