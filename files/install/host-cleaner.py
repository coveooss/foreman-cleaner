import baker
import datetime
import os
import requests
import socket
from foreman.client import Foreman
from subprocess import call


class ForemanProxy(object):
    def __init__(self, url, auth=None, verify=False):
        self.session = requests.Session()
        self.url = url

        if auth is not None:
            self.session.auth = auth

        self.session.headers.update(
        {
            'Accept': 'application/json; version=1.15',
            'Content-type': 'application/json',
        })

        fqdn = socket.getfqdn()
        self.session.cert = ('/var/lib/puppet/ssl/certs/{}.pem'.format(fqdn), '/var/lib/puppet/ssl/keys/{}.pem'.format(fqdn))

    def delete_certificate(self, host):
        uri = "/puppet/ca/{}".format(host)
        r = self.session.delete(self.url + uri)
        if r.status_code < 200 or r.status_code >= 300:
            print('Something went wrong: %s' % r.text)
        return r

@baker.command()
def clean_old_host():

    # Retrieve config from ENV
    foreman_url = os.environ.get('FOREMAN_URL')
    foreman_user = os.environ.get('FOREMAN_USER')
    foreman_password = os.environ.get('FOREMAN_PASSWORD')
    foreman_proxy_url = "https://{}:{}".format(os.environ.get('FOREMANPROXY_HOST'),os.getenv('FOREMANPROXY_PORT','8443'))
    delay = os.getenv('FOREMAN_CLEAN_DELAY', '1')

    #connect to Foreman and ForemanProxy
    f=Foreman(foreman_url, (foreman_user, foreman_password))
    fp = ForemanProxy(foreman_proxy_url)


    #Get the the current date
    currentdate = datetime.datetime.utcnow()

    #check for all host
    get_next_page = True
    page = 1
    while get_next_page:
        result = f.index_hosts(per_page="1000", page=str(page))
        if len(result) == 1000:
            page += 1
        else:
            get_next_page = False
        for host in result:
            #get the la comiple date
            lastcompile = f.show_hosts(id=host["host"]["id"])["host"]["last_compile"]
            #Convert the string date to datetime format
            if lastcompile:
                hostdate = datetime.datetime.strptime(lastcompile,'%Y-%m-%dT%H:%M:%SZ')
                #Get the delta between the last puppet repport and the current date
                elapsed = currentdate - hostdate
                # if the deta is more than $delay days we delete the host
                if elapsed > datetime.timedelta(hours=int(delay)):
                    print "I will destroy the server "+host["host"]["name"]+" because the last report was " +str(lastcompile)
                    #destroy the host in foreman
                    f.destroy_hosts(id=host["host"]["id"])
                    #remove the certificate in puppet
                    fp.delete_certificate(host["host"]["name"])


## Read option
if __name__ == "__main__":
  baker.run()