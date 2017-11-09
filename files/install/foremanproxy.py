import requests
import socket


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
        uri = "/puppet/ca/{}".format(host)
        r = self.session.delete(self.url + uri)
        if r.status_code < 200 or r.status_code >= 300:
            print('Something went wrong: %s' % r.text)
        else:
            print('Puppet - {} deleted'.format(host))
        return r

    def get_certificates(self):
        uri = "/puppet/ca"
        r = self.session.get(self.url + uri)
        if r.status_code < 200 or r.status_code >= 300:
            print('Something went wrong: %s' % r.text)
        else:
            return r.json()