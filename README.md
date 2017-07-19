# foreman-cleaner

Tools to clean foreman host,report and puppet's certs

## Config

Config is made through the following environment variables.

* FOREMAN_URL : Foreman's UI URL (ex :"https://confmanager.corp.com")
* FOREMAN_USER : The user service used to make call to the API
* FOREMAN_PASSWORD : Password for the user service
* FOREMANPROXY_HOST : The forman proxy hostname (ex: "puppet-elb.dev.cloud.coveo.com")
* FOREMAN_CLEAN_DELAY : Number of day from which a host without a puppet report will be deleted
