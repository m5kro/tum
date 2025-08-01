# tuptime - A tool to track system uptime and downtime.
# Currently supports:
# ICMP
# SMB
# FTP
# HTTP
# SSH

import os
import sys
import json
import argparse

config_file = None
# get the system os (windows, linux, mac)
sys_type = sys.platform
print(f"Detected system type: {sys_type}")

# Set config file location based on the system type
if sys_type.startswith('win'):
    config_file = os.path.join(os.getenv('APPDATA'), 'tuptime', 'config.json')
elif sys_type.startswith('linux'):
    config_file = os.path.join(os.getenv('HOME'), '.config', 'tuptime', 'config.json')
elif sys_type.startswith('darwin'):
    config_file = os.path.join(os.getenv('HOME'), 'Library', 'Application Support', 'tuptime', 'config.json')


# Check for the config file
if not os.path.exists(config_file):
    print(f"Config file not found: {config_file}")
    print("This seems to be the first run of tuptime.")
    # Create blank config file
    default_config = {
    }
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    with open(config_file, 'w') as f:
        json.dump(default_config, f, indent=4)
    print(f"Default config file created: {config_file}")
else:
    print(f"Config file found: {config_file}")

def show_help():
    print("Usage: tuptime [options]")
    print("Options:")
    print("  -h, --help             Show this help message and exit")
    print("  -c, --config           Show the current configuration")
    print("  -v, --version          Show the version of tuptime")
    print("  -a, --add <name>       Add a new service to monitor")
    print("  -r, --remove <name>    Remove a service from monitoring")
    print("  -s, --service <type>   Specify the service type (ICMP/SMB/FTP/HTTP/SSH)")
    print("  -i, --interval <seconds> Set the monitoring interval (default: 60 seconds)")
    print("  -u, --username <name>  Set the username for the service (SMB/FTP/SSH)")
    print("  -p, --password <password> Set the password for the service (SMB/FTP/SSH)")
    print("  -d, --daemon <start|stop> Start or stop the background daemon")
    print("Example:")
    print("  tuptime -a MyService -s ICMP -i 30")
    print("  tuptime -d start")

# take in parameters
parser = argparse.ArgumentParser(prog='tuptime', add_help=False)
group = parser.add_mutually_exclusive_group()
group.add_argument('-a', '--add', metavar='NAME', help='Add a new service to monitor')
group.add_argument('-r', '--remove', metavar='NAME', help='Remove a service from monitoring')
group.add_argument('-c', '--config', action='store_true', help='Show the current configuration')
group.add_argument('-v', '--version', action='store_true', help='Show the version of tuptime')
group.add_argument('-d', '--daemon', metavar='ACTION', choices=['start', 'stop'],
                   help='Start or stop the background daemon')

parser.add_argument('-s', '--service', metavar='TYPE', type=lambda s: s.upper(),
                    choices=['ICMP', 'SMB', 'FTP', 'HTTP', 'SSH'],
                    help='Specify the service type (ICMP/SMB/FTP/HTTP/SSH)')
parser.add_argument('-i', '--interval', metavar='SECONDS', type=int, default=60,
                    help='Set the monitoring interval (default: 60 seconds)')
parser.add_argument('-u', '--username', metavar='USER', help='Set the username for the service (SMB/FTP/SSH)')
parser.add_argument('-p', '--password', metavar='PASS', help='Set the password for the service (SMB/FTP/SSH)')
parser.add_argument('-h', '--help', action='store_true', help='Show this help message and exit')

args = parser.parse_args()

if args.help:
    show_help()
    sys.exit(0)

# Map parsed args into variables
action = None  # one of: 'add', 'remove', 'show_config', 'show_version', 'daemon_start', 'daemon_stop', or None
service_name = None
if args.add:
    action = 'add'
    service_name = args.add
elif args.remove:
    action = 'remove'
    service_name = args.remove
elif args.config:
    action = 'show_config'
elif args.version:
    action = 'show_version'
elif args.daemon:
    action = f"daemon_{args.daemon}"  # 'daemon_start' or 'daemon_stop'

service_type = args.service 
interval = args.interval
username = args.username
password = args.password

# placeholder output
print(f"Action: {action}")
print(f"Service name: {service_name}")
print(f"Service type: {service_type}")
print(f"Interval: {interval}")
print(f"Username: {username}")
print(f"Password: {'***' if password else None}")
