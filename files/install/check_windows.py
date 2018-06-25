from awsutils import AwsDs
import ldap
import logging
import sys
from awsutils import get_instances_from_ec2
import click
import yaml

@click.group()
def main():
    pass


@main.command()
@click.option("--config_file", '-c', help="Specify config file")
def check_join(config_file):

    with open(config_file, 'r') as stream:
        try:
            config = yaml.load(stream)
        except yaml.YAMLError as exc:
            print(exc)

    domain_name = config['domain_name']
    computers_base_dn = config['domain_computer_dn']
    bind_user_dn = config['domain_user']
    bind_password = config['domain_password']
    search_filters = config['search_filters']
    auto_heal = config['auto_heal']

    # Connect to the DS
    try:
        ds = AwsDs(domain_name, computers_base_dn, bind_user_dn, bind_password)
    except ldap.INVALID_CREDENTIALS:
        raise "Your username or password is incorrect."

    # Get all ds computer
    ds_computers = {}
    for c_dn, attr in ds.computers:
        ds_computers[attr['cn'][0].lower()] = attr.get('dNSHostName', None)
    # Extract only dns name
    ds_computers_names = [dns_names[0] for cn, dns_names in ds_computers.iteritems() for p in search_filters if dns_names and p in dns_names[0]]

    # Get all running ec2 instances
    ec2_instances = get_instances_from_ec2(domain_name)
    # Extract only names
    ec2_instances_names = [dns_name for dns_name, instance_infos in ec2_instances.iteritems() for pattern in search_filters if pattern in dns_name ]
    ec2_instances_cn = [instance_infos['cn'] for dns_name, instance_infos in ec2_instances.iteritems() for pattern in
                           search_filters if pattern in dns_name]
    unjoined_machines = set(ec2_instances_names) - set(ds_computers_names)
    unjoined_machines = list(unjoined_machines)
    joined_machines = set(ec2_instances_names) & set(ds_computers_names)

    need_repair = [cn for cn, dns_names in ds_computers.iteritems() for p in search_filters if not dns_names and p in cn and cn in ec2_instances_cn]

    # Delete from unjoined list machines which need repair
    for m in need_repair:
        for i, v in enumerate(unjoined_machines):
            if m in v:
                del unjoined_machines[i]

    # Delete from repair list machine which is stopped in ec2
    for ec2_instance in ec2_instances_names:
        if ec2_instances[ec2_instance]['status'] != 'running':
            for i, v in enumerate(need_repair):
                if v in ec2_instance:
                    del need_repair[i]

    if unjoined_machines:
        logging.info("--------------------------------")
        logging.info("Unjoined machines:")
        for m in unjoined_machines:
            logging.info('{} ec2status :{}'.format(m, ec2_instances[m]['status']))
            if auto_heal:
                logging.info("autoheal is enabled, try to re-create computer in DS")
                try:
                    ds.add_computer('CN={},{}'.format(ec2_instances[m]['cn'], computers_base_dn))
                    logging.info("Autoheal succeeded")
                    need_repair.append(m)
                except:
                    logging.error('Autoheal failed')
    else:
        logging.info('All Windows machine are joined to the domain')
    logging.debug("--------------------------------")
    logging.debug("Joined machines:")
    for m in joined_machines:
        logging.debug(m)
    if need_repair:
        logging.info("--------------------------------")
        logging.info("Machine which need to repair the AD secureChannel:")
        logging.info("Set fix_join parameter in puppet")
        logging.info("or")
        logging.info("Run \"Test-ComputerSecureChannel -credential DOMAIN\USERNAME -Repair\"")
        for m in need_repair:
            logging.info(m)

if __name__ == "__main__":
    logging.getLogger('botocore').setLevel(logging.WARN)
    logging.getLogger('boto3').setLevel(logging.WARN)
    logger = logging.getLogger()
    loggers_dict = logging.Logger.manager.loggerDict
    logger.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    main()
