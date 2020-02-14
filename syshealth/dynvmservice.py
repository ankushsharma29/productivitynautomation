import XenAPI
import sys
import argparse
import json
import time
import datetime
from flask import Flask, request
import configparser

import logging
log = logging.getLogger(__name__)
logging.info("dynxenvms")
print("*** Dynamic VMs ***")
app = Flask(__name__)

@app.route("/showall")
def showall_service():
    return perform_service(service_name='listvms')

#/getservers/username?count=number&os=centos&ver=6&expiresin=30
@app.route('/getservers/<string:username>')
def getservers_service(username):
    if request.args.get('count'):
        vm_count = int(request.args.get('count'))
    else:
        vm_count = 1
    os_name = request.args.get('os')
    return perform_service(1,'createvm', os_name, username, vm_count)

#/releaseservers/{username}/{state}
@app.route('/releaseservers/<string:username>')
def releaseservers_service(username):
    if request.args.get('count'):
        vm_count = int(request.args.get('count'))
    else:
        vm_count = 1
    os_name = request.args.get('os')
    return perform_service(1,'deletevm', os_name, username, vm_count)

def perform_service(xen_host_ref=1, service_name='list_vms', os="centos", vm_prefix_names="",
                                                                number_of_vms=1):
    xen_host = get_xen_host(xen_host_ref, os)
    url = "http://" + xen_host['host.name']
    log.debug("\nXen Server host: " + xen_host['host.name'] + "\n")
    try:
        session = XenAPI.Session(url)
        session.xenapi.login_with_password(xen_host['host.user'], xen_host['host.password'])
    except XenAPI.Failure as f:
        error = "Failed to acquire a session: {}".format(f.details)
        log.error(error)
        return error

    options = argparse.ArgumentParser()
    log.info("Getting template "+ os+'.template')
    template = xen_host[os+'.template']
    try:
        if service_name == 'createvm':
            log.debug("Creating from "+template+" :" +vm_prefix_names)
            new_vms = create_vms(session, template, vm_prefix_names, number_of_vms)
            log.info(new_vms)
            return new_vms
        elif service_name == 'deletevm':
            return delete_vms(session, vm_prefix_names, number_of_vms)
        elif service_name == 'listvm':
            return list_given_vm_set_details(session, vm_prefix_names, number_of_vms)
        elif service_name == 'listvms':
            return list_vms(session)
        else:
            list_vms(session)
    except Exception as e:
        log.error(str(e))
        raise
    finally:
        session.logout()

def get_all_xen_hosts():
    config = configparser.RawConfigParser()
    config.read('.dynvmservice.ini')
    log.debug(config.sections())
    xen_host_ref=1
    all_xen_hots = []
    xen_host = {}
    for section in config.sections():
        if section.startswith('xenhost'):
            xen_host = {}
            for key in config.keys():
                xen_host[key] = config.get('xenhost' + str(xen_host_ref), key)
            all_xen_hots.append(xen_host)
            xen_host_ref += 1
    return all_xen_hots

def get_xen_host(xen_host_ref=1,os='centos'):
    config = configparser.RawConfigParser()
    config.read('.dynvmservice.ini')
    log.info(config.sections())
    xen_host = {}
    xen_host["host.name"] = config.get('xenhost'+str(xen_host_ref), 'host.name')
    xen_host["host.user"] = config.get('xenhost' + str(xen_host_ref), 'host.user')
    xen_host["host.password"] = config.get('xenhost' + str(xen_host_ref), 'host.password')
    xen_host[os+".template"] = config.get('xenhost' + str(xen_host_ref), os+'.template')
    return xen_host


def usage(err=None):
    print("""\
Usage Syntax: dynxenvms -h or options

Examples:
 python dynxenvms.py -h
 python dynxenvms.py -x xenserver -u root -p pwd -c vmname -n count"
""")
    sys.exit(0)
def setLogLevel(log_level='info'):
    if log_level and log_level.lower() == 'info':
        log.setLevel(logging.INFO)
    elif log_level and log_level.lower() == 'warning':
        log.setLevel(logging.WARNING)
    elif log_level and log_level.lower() == 'debug':
        log.setLevel(logging.DEBUG)
    elif log_level and log_level.lower() == 'critical':
        log.setLevel(logging.CRITICAL)
    elif log_level and log_level.lower() == 'fatal':
        log.setLevel(logging.FATAL)
    else:
        log.setLevel(logging.NOTSET)


def list_vms(session):
    vm_count=0
    vms = session.xenapi.VM.get_all()
    log.info("Server has {} VM objects (this includes templates):".format(len(vms)))
    log.info("-----------------------------------------------------------")
    log.info("S.No.,VMname,PowerState,Vcpus,MaxMemory,Networkinfo,Description")
    log.info("-----------------------------------------------------------")

    vm_details = []
    for vm in vms:
        record = session.xenapi.VM.get_record(vm)
        if not (record["is_a_template"]) and not (record["is_control_domain"]):
            vm_count = vm_count + 1
            name = record["name_label"]
            name_description = record["name_description"]
            uuid = record["uuid"]
            power_state = record["power_state"]
            vcpus = record["VCPUs_max"]
            memory_static_max = record["memory_static_max"]
            hostVIFs = record['VIFs']
            if (record["power_state"] != 'Halted'):
                ipRef = session.xenapi.VM_guest_metrics.get_record(record['guest_metrics'])
                networkinfo = ','.join([str(elem) for elem in ipRef['networks'].values()])
            else:
                networkinfo = 'N/A'

            vm_info = {}
            vm_info['name'] = name
            vm_info['power_state'] = power_state
            vm_info['vcpus'] = vcpus
            vm_info['memory_static_max'] = memory_static_max
            vm_info['networkinfo'] = networkinfo
            vm_info['name_description'] = name_description
            vm_details.append(vm_info)
            log.info(vm_info)

    log.info("Server has {} VM objects and {} templates.".format(vm_count, len(vms)-vm_count))
    log.info(vm_details)
    return json.dumps(vm_details, indent=2, sort_keys=True)

def list_vm_details(session, vm_name):
    vm = session.xenapi.VM.get_by_name_label(vm_name)
    if len(vm)>0:
        record = session.xenapi.VM.get_record(vm[0])
        name_description = record["name_description"]
        uuid = record["uuid"]
        power_state = record["power_state"]
        vcpus = record["VCPUs_max"]
        memory_static_max = record["memory_static_max"]
        hostVIFs = record['VIFs']
        if (record["power_state"] != 'Halted'):
            ipRef = session.xenapi.VM_guest_metrics.get_record(record['guest_metrics'])
            networkinfo = ','.join([str(elem) for elem in ipRef['networks'].values()])
        else:
            networkinfo = 'N/A'
        log.info(vm_name + "," + power_state + "," + vcpus + "," + memory_static_max +
              "," + networkinfo +", "+name_description)


def create_vms(session, template, vm_prefix_names, number_of_vms=1):
    vm_names = vm_prefix_names.split(",")
    index = 1
    new_vms_info = {}
    for i in range(len(vm_names)):
        if int(number_of_vms)>1:
            for k in range(int(number_of_vms)):
                vm_name = vm_names[i] + str(k+1)
                vm_ip, vm_os, error = create_vm(session, template, vm_name)
                new_vms_info[vm_name] = vm_ip
                if error:
                    new_vms_info[vm_name+"_error"] = error

                index = index+1
        else:
            vm_ip, vm_os, error = create_vm(session, template, vm_names[i])
            new_vms_info[vm_names[i]] = vm_ip
            if error:
                new_vms_info[vm_names[i] + "_error"] = error
            index = index + 1
    return new_vms_info

def create_vm(session, template, new_vm_name):
    error = ''
    try:
        log.info("\n--- Creating VM: " + new_vm_name + " using " + template)
        pifs = session.xenapi.PIF.get_all_records()
        lowest = None
        for pifRef in pifs.keys():
            if (lowest is None) or (pifs[pifRef]['device'] < pifs[lowest]['device']):
                lowest = pifRef
        log.debug("Choosing PIF with device: {}".format(pifs[lowest]['device']))
        # List all the VM objects
        vms = session.xenapi.VM.get_all_records()
        log.debug("Server has {} VM objects (this includes templates)".format(len(vms)))

        templates = []
        all_templates = []
        for vm in vms:
            record = vms[vm]
            ty = "VM"
            if record["is_a_template"]:
                ty = "Template"
                all_templates.append(vm)
                # Look for a given template
                if record["name_label"].startswith(template):
                    templates.append(
                        vm)  #  log.info("  Found %8s with name_label = %s" % (ty,
                    # record["name_label"]))

        log.debug("Server has {} Templates and {} VM objects.".format(
            len(all_templates), (len(vms) - len(all_templates))))

        log.debug("Choosing a " + template + " template to clone")
        if not templates:
            log.error("Could not find any " + template + " templates. Exiting.")
            sys.exit(1)

        template_ref = templates[0]
        log.debug("  Selected template: {}".format(session.xenapi.VM.get_name_label(template_ref)))
        log.debug("Installing new VM from the template")
        vm = session.xenapi.VM.clone(template_ref, new_vm_name)

        network = session.xenapi.PIF.get_network(lowest)
        log.debug("Chosen PIF is connected to network: {}".format(session.xenapi.network.get_name_label(
            network)))
        vifs = session.xenapi.VIF.get_all()
        log.debug(("Number of VIFs=" + str(len(vifs))))
        for i in range(len(vifs)):
            vmref = session.xenapi.VIF.get_VM(vifs[i])
            a_vm_name = session.xenapi.VM.get_name_label(vmref)
            #  log.info((str(i)+"."+session.xenapi.network.get_name_label(session.xenapi.VIF.get_network(
            #    vifs[i]))+" "+a_vm_name)
            if (a_vm_name == new_vm_name):
                session.xenapi.VIF.move(vifs[i], network)

        log.debug("Adding non-interactive to the kernel commandline")
        session.xenapi.VM.set_PV_args(vm, "non-interactive")
        log.debug("Choosing an SR to instantiate the VM's disks")
        pool = session.xenapi.pool.get_all()[0]
        default_sr = session.xenapi.pool.get_default_SR(pool)
        default_sr = session.xenapi.SR.get_record(default_sr)
        log.debug("Choosing SR: {} (uuid {})".format(default_sr['name_label'], default_sr['uuid']))
        log.debug("Asking server to provision storage from the template specification")
        description = new_vm_name + " from " + template + " on " + str(
            datetime.datetime.utcnow())
        session.xenapi.VM.set_name_description(vm, description)
        session.xenapi.VM.provision(vm)
        log.info("Starting VM")
        session.xenapi.VM.start(vm, False, True)
        log.debug("  VM is booting")

        log.debug("Waiting for the installation to complete")

        # Here we poll because we don't generate events for metrics objects currently

        def read_os_name(a_vm):
            vgm = session.xenapi.VM.get_guest_metrics(a_vm)
            try:
                os = session.xenapi.VM_guest_metrics.get_os_version(vgm)
                if "name" in os.keys():
                    return os["name"]
                return None
            except:
                return None

        def read_ip_address(a_vm):
            vgm = session.xenapi.VM.get_guest_metrics(a_vm)
            try:
                os = session.xenapi.VM_guest_metrics.get_networks(vgm)
                if "0/ip" in os.keys():
                    return os["0/ip"]
                return None
            except:
                return None

        def read_cpu_memory(a_vm):
            vgm = session.xenapi.VM.get_guest_metrics(a_vm)
            try:
                vm_mem= session.xenapi.VM_guest_metrics.get_memory(vgm)
                log.info(vm_mem)

                return vm_mem
            except:
                return None

        while read_os_name(vm) is None:
            time.sleep(1)
        vm_os_name = read_os_name(vm)
        log.info("VM OS name: {}".format(vm_os_name))
        while read_ip_address(vm) is None:
            time.sleep(1)

        vm_ip_addr = read_ip_address(vm)
        log.info("VM IP: {}".format(vm_ip_addr))
    except Exception as e:
        error = str(e)
        log.error(error)
        vm_ip_addr = ''
        vm_os_name = ''

    return vm_ip_addr, vm_os_name, error


def delete_vms(session, vm_prefix_names, number_of_vms=1):
    vm_names = vm_prefix_names.split(",")

    vm_info = {}
    for i in range(len(vm_names)):
        if int(number_of_vms)>1:
            for k in range(int(number_of_vms)):
                delete_vm(session, vm_names[i] + str(k+1))
                vm_info[vm_names[i] + str(k+1)] = "deleted"

        else:
            delete_vm(session, vm_names[i])
            vm_info[vm_names[i]] = "deleted"

    return json.dumps(vm_info, indent=2, sort_keys=True)

def delete_vm(session, vm_name):
    log.info("Deleting VM: "+ vm_name)
    vm = session.xenapi.VM.get_by_name_label(vm_name)
    for j in range(len(vm)):
        record = session.xenapi.VM.get_record(vm[j])
        power_state = record["power_state"]
        if power_state != 'Halted':
            session.xenapi.VM.shutdown(vm[j])

        vbds = session.xenapi.VM.get_VBDs(vm[j])
        vdi = session.xenapi.VBD.get_VDI(vbds[0])
        if vdi:
            log.debug("Deleting the disk...")
            session.xenapi.VDI.destroy(vdi)
        session.xenapi.VM.destroy(vm[j])


def list_given_vm_set_details(session, options):
    vm_names = options.list_vm_names.split(",")
    for i in range(len(vm_names)):
        if int(options.number_of_vms) > 1:
            for k in range(int(options.number_of_vms)):
                list_vm_details(session, vm_names[i] + str(k + 1))
        else:
            list_vm_details(session, vm_names[i])

def parse_arguments():
    log.debug("Parsing arguments")
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", default=".dynvmservice.ini", help="Configuration file")
    parser.add_argument("-l", "--log-level", dest="loglevel", default="INFO",
                        help="e.g -l info,warning,error")
    options = parser.parse_args()
    return options

def main():
    options = parse_arguments()
    setLogLevel()
    app.run(debug=True)

if __name__ == "__main__":
    main()

