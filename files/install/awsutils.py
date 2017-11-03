import ldap
import boto3
from botocore.exceptions import ClientError
import re


class NotFound(Exception):
    def __init__(self, *args, **kwargs):
        pass


class TooManyResult(Exception):
    def __init__(self, *args, **kwargs):
        pass


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
            self._computers = self._con.search_st(self.computers_base_dn, ldap.SCOPE_SUBTREE, '(objectclass=computer)', ['dNSHostName', 'distinguishedName'], 0, 500)
        return self._computers

    def delete_computer(self, hostname):
        computer_found = [attr for c_dn, attr in self.computers if 'dNSHostName' in attr
                          if re.match('^{}.*'.format(hostname.lower()), attr['dNSHostName'][0].lower())]
        if len(computer_found) > 1:
            raise TooManyResult
        elif not computer_found:
            raise NotFound
        else:
            print("DS - delete : {}".format(computer_found[0]['distinguishedName'][0]))
            self._con.delete_s(computer_found[0]['distinguishedName'][0])


def get_ec2_instance_state(instance_id):
    client = boto3.client('ec2')
    state = 'terminated'
    try:
        rsp = client.describe_instances(InstanceIds=[instance_id])
        if rsp['Reservations']:
            state = rsp['Reservations'][0]['Instances'][0]
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidInstanceID.NotFound':
            pass
        else:
            raise e
    return state