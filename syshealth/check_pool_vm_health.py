"""
    QE static pool VMs health check
   
    Usage example: 
        python3 check_pool_vm_health.py
        python3 check_pool_vm_health.py regression,12hrreg,security
        [ Environment variables needed: pool_cb_password=, vm_windows_password=, vm_linux_password=]

    Output: pool_vm_health_info.csv
"""
import sys
import os
import json
import urllib.request
from datetime import timedelta
from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster, ClusterOptions, ClusterTimeoutOptions
from paramiko import SSHClient, AutoAddPolicy

def get_pool_data(pools):
    pools_list = []
    for pool in pools.split(','):
        pools_list.append(pool)
    
    query = "SELECT ipaddr, os, state, origin, poolId FROM `QE-server-pool` WHERE poolId in [" \
                + ', '.join('"{0}"'.format(p) for p in pools_list) + "] or " \
                + ' or '.join('"{0}" in poolId'.format(p) for p in pools_list)
    pool_cb_host = os.environ.get('pool_cb_host')
    if not pool_cb_host:
        pool_cb_host = "172.23.104.162"
    pool_cb_user = os.environ.get('pool_cb_user')
    if not pool_cb_user:
        pool_cb_user = "Administrator"
    pool_cb_user_p = os.environ.get('pool_cb_password')
    if not pool_cb_user_p:
        print("Error: pool_cb_password environment variable setting is missing!")
        exit(1)
    data = ''
    try:
        pool_cluster = Cluster("couchbase://"+pool_cb_host, ClusterOptions(PasswordAuthenticator(pool_cb_user, pool_cb_user_p),
        timeout_options=ClusterTimeoutOptions(kv_timeout=timedelta(seconds=10))))
        result = pool_cluster.query(query)
        count = 0
        ssh_failed = 0
        ssh_ok = 0
        index = 0
        csvout = open("pool_vm_health_info.csv", "w")
        print("ipaddr,ssh_status,ssh_error,os,pool_state,pool_ids,cpus,memory_total(kB),memory_free(kB),memory_available(kB),memory_use(%)," + \
                "disk_size(MB),disk_used(MB),disk_avail(MB),disk_use%,uptime,system_time,users,cpu_load_avg_1min,cpu_load_avg_5mins,cpu_load_avg_15mins," + \
                "total_processes,couchbase_process,couchbase_version,couchbase_services")
        csvout.write("ipaddr,ssh_status,ssh_error,os,pool_state,pool_ids,cpus,memory_total(kB),memory_free(kB),memory_available(kB),memory_use(%)," + \
                "disk_size(MB),disk_used(MB),disk_avail(MB),disk_use%,uptime,system_time,users,cpu_load_avg_1min,cpu_load_avg_5mins,cpu_load_avg_15mins," \
                "total_processes,couchbase_process,couchbase_version,couchbase_services")
        for row in result:
            index += 1
            try:
                ssh_status, ssh_error, cpus, meminfo, diskinfo, uptime, systime, cpu_load, cpu_proc, cb_proc, cb_version, cb_serv = check_vm(row['os'],row['ipaddr'])
                if ssh_status == 'ssh_failed':
                    ssh_state=0
                    ssh_failed += 1
                else:
                    ssh_state=1
                    ssh_ok += 1
                print("{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}".format(index, row['ipaddr'], ssh_status, ssh_error, row['os'], \
                    row['state'],  '+'.join("{}".format(p) for p in row['poolId']), cpus, meminfo, diskinfo, uptime, systime, cpu_load, cpu_proc, cb_proc, cb_version, cb_serv))
                csvout.write("\n{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}".format(row['ipaddr'], ssh_state, ssh_error, row['os'], \
                    row['state'],  '+'.join("{}".format(p) for p in row['poolId']), cpus, meminfo, diskinfo, uptime, systime, cpu_load, cpu_proc, cb_proc, cb_version, cb_serv))
                csvout.flush()
            except Exception as ex:
                print(ex)
                pass
            count +=1
        print("ssh_ok={},ssh_failed={},total={}".format(ssh_ok, ssh_failed,count))
        csvout.close()
    except:
        print("exception:", sys.exc_info()[0])
    
def check_vm(os_name, host):
    config = os.environ
    if '[' in host:
        host = host.replace('[','').replace(']','')
    if os_name == "windows":
        username = 'Administrator' if not config.get("vm_windows_username") else config.get("vm_windows_username")
        password = config.get("vm.windows.password")
    else:
        username = 'root' if not config.get("vm_linux_username") else config.get("vm_linux_username")
        password = config.get("vm_linux_password")
    try:
        client = SSHClient()
        client.set_missing_host_key_policy(AutoAddPolicy())
        client.connect(
            host,
            username=username,
            password=password,
            timeout=30
        )
        cpus = get_cpuinfo(client)
        meminfo = get_meminfo(client)
        diskinfo = get_diskinfo(client)
        uptime = get_uptime(client)
        systime = get_system_time(client)
        cpu_load = get_cpu_users_load_avg(client)
        cpu_total_processes = get_total_processes(client)
        cb_processes = get_cb_processes(client)
        cb_running_serv = get_cb_running_services(client)
        cb_version = get_cb_version(client)

        while len(meminfo.split(','))<3:
            meminfo += ','
        mem_total = meminfo.split(',')[0]
        mem_free = meminfo.split(',')[1]
        if mem_free and mem_total:
            meminfo += ","+ str(round(((int(mem_total)-int(mem_free))/int(mem_total))*100))
        while len(cpu_load.split(','))<4:
            cpu_load += ','
        #while len(cb_running_serv.split(','))<7:
        #    cb_running_serv += ','
    
        client.close()
    except Exception as e:
        meminfo = ',,,'
        diskinfo = ',,,'
        cpu_load = ',,,'
        cb_running_serv=','
        return 'ssh_failed', str(e).replace(',',' '), '', meminfo, diskinfo,'','',cpu_load, '', '', '',cb_running_serv
    return 'ssh_ok', '', cpus, meminfo, diskinfo, uptime, systime, cpu_load, cpu_total_processes, cb_processes, cb_version, cb_running_serv

def get_cpuinfo(ssh_client):
    return ssh_command(ssh_client,"cat /proc/cpuinfo  |egrep processor |wc -l")

def get_meminfo(ssh_client):
    return ssh_command(ssh_client,"cat /proc/meminfo |egrep Mem |cut -f2- -d':'|sed 's/ //g'|xargs|sed 's/ /,/g'|sed 's/kB//g'")

def get_diskinfo(ssh_client):
    return ssh_command(ssh_client,"df -ml --output=size,used,avail,pcent / |tail -1 |sed 's/ \+/,/g'|cut -f2- -d','|sed 's/%//g'")

def get_system_time(ssh_client):
    return ssh_command(ssh_client, "TZ='America/Los_Angeles' date '+%Y-%m-%d %H:%M:%S'")

def get_uptime(ssh_client):
    return ssh_command(ssh_client, "uptime -s")

def get_cpu_users_load_avg(ssh_client):
    return ssh_command(ssh_client, "uptime |rev|cut -f1-4 -d','|rev|sed 's/load average://g'|sed 's/ \+//g'|sed 's/users,/,/g'|sed 's/user,/,/g'")

def get_total_processes(ssh_client):
    return ssh_command(ssh_client, "ps aux | egrep -v COMMAND | wc -l")

def get_cb_processes(ssh_client):
    return ssh_command(ssh_client, "ps -o comm `pgrep -f couchbase` |egrep -v COMMAND |wc -l")

def get_cb_running_services(ssh_client):
    cb_processes = ssh_command(ssh_client, "ps -o comm `pgrep -f couchbase`|egrep -v COMMAND | xargs")
    cb_services = []
    for proc in cb_processes.split(' '):
        if proc == 'memcached':
            cb_services.append('data(kv)')
        elif proc == 'indexer':
            cb_services.append('index')
        elif proc == 'cbq-engine':
            cb_services.append('query(n1ql)')
        elif proc == 'cbft':
            cb_services.append('search(fts)')
        elif proc == 'cbas':
            cb_services.append('analytics(cbas)')
        elif proc == 'eventing-produc':
            cb_services.append('eventing')
        elif proc == 'goxdcr':
            cb_services.append('xdcr')
    cb_services.sort()
    return ' '.join(cb_services)
        
def get_cb_version(ssh_client):
    return ssh_command(ssh_client, "if [ -f /opt/couchbase/VERSION.txt ]; then cat /opt/couchbase/VERSION.txt; fi")

def ssh_command(ssh_client, cmd):
    ssh_output = ''
    ssh_error = ''
    try:
        ssh_stdin, ssh_stdout, ssh_stderr = ssh_client.exec_command(cmd)
        
        for line in iter(ssh_stdout.readline, ""):
            ssh_output += line
        if ssh_output:
            ssh_output = str(ssh_output).rstrip()
        for line in iter(ssh_stderr.readline, ""):
            ssh_error += line
    except:
        print("cmd={},error={}".format(cmd,ssh_error))

    return ssh_output

def main():
    if len(sys.argv) < 2:
        print("Usage: {} {}".format(sys.argv[0], "<pool> [xen_hosts_file] "))
        print("Environment: pool_cb_password=, [pool_cb_host=172.23.104.162, pool_cb_user=Administrator]")
        exit(1)
    pools = sys.argv[1]
    xen_hosts_file = ''
    if len(sys.argv) > 2:
        xen_hosts_file = sys.argv[2]
    get_pool_data(pools)


if __name__ == '__main__':
    main()
