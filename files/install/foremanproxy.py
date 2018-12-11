import requests
import socket
import subprocess


class ForemanProxy(object):
    def __init__(self, url, auth=None, verify=False):
        self.session = requests.Session()
        self.url = url
        self.session.verify = verify
        if auth is not None:
            self.session.auth = auth

        self.session.headers.update(
        {
            'Accept': 'application/json',
            'Content-type': 'application/json',
        })

        fqdn = socket.getfqdn()
        self.session.cert = ('/var/lib/puppet/ssl/certs/{}.pem'.format(fqdn), '/var/lib/puppet/ssl/private_keys/{}.pem'.format(fqdn))

    def delete_certificate(self, host):
        res = subprocess.Popen('/usr/bin/puppet cert clean {}'.format(host)
                               ,stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        # Wait for the process end and print error in case of failure
        if res.wait() != 0:
            output, error = res.communicate()
            Exception(error)
        else:
            print('Puppet - certificate {} deleted'.format(host))

    def get_certificates(self):
        uri = "/puppet/ca"
        r = self.session.get(self.url + uri)
        if r.status_code < 200 or r.status_code >= 300:
            print('Something went wrong: %s' % r.text)
        else:
            return r.json()