import os
import sys
import json
import argparse
#import daemon
from datetime import datetime

VERSION = "0.1"

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

def load_config():
    if not os.path.exists(config_file):
        return {}
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load config: {e}")
        return {}

def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, 'w') as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print(f"Failed to save config: {e}")

def show_help():
    print("Usage: tuptime [options]")
    print("Options:")
    print("  -h, --help               Show this help message and exit")
    print("  -c, --config             Show the current configuration")
    print("  -v, --version            Show the version of tuptime")
    print("  -a, --add <name>         Add a new service to monitor (requires -t/--target)")
    print("  -r, --remove <name>      Remove a service from monitoring")
    print("  -s, --service <type>     Specify the service type (ICMP/SMB/FTP/HTTP/SSH)")
    print("  -i, --interval <seconds> Set the monitoring interval (default: 60 seconds)")
    print("  -u, --username <name>    Set the username for the service (SMB/FTP/SSH)")
    print("  -P, --password <password> Set the password for the service (SMB/FTP/SSH)")
    print("  -p, --port <port>        Set the port for the service (uses sensible defaults if omitted)")
    print("  -t, --target <host>      Target hostname or IP address (required when adding)")
    print("  -d, --daemon <start|stop> Start or stop the background daemon")
    print("Example:")
    print("  tuptime -a MyService -s ICMP -t 8.8.8.8 -i 30")
    print("  tuptime -a Web -s HTTP -t example.com -p 8080")
    print("  tuptime -d start")

def add_service(name, service_type, interval, username, password, target, port):
    if not service_type:
        print("Error: --service is required when adding a service.")
        return
    if not target:
        print("Error: --target is required when adding a service.")
        return
    # default ports per service type
    default_ports = {
        "ICMP": None,
        "SMB": 445,
        "FTP": 21,
        "HTTP": 80,
        "SSH": 22,
    }
    if port is None:
        port = default_ports.get(service_type, None)
    cfg = load_config()
    services = cfg.get("services", {})
    if name in services:
        print(f"Service '{name}' already exists in config.")
        return
    entry = {
        "name": name,
        "service_type": service_type,
        "target": target,
        "port": port,
        "username": username or "",
        "password": password or "",
        "interval": interval,
        "isup": False,
        "total_uptime": 0,        # in seconds
        "total_downtime": 0,      # in seconds
        "last_downtime": None     # ISO 8601 timestamp or None
    }
    services[name] = entry
    cfg["services"] = services
    save_config(cfg)
    print(f"Added service '{name}' with type {service_type}, target {target}, port {port} to config.")

def remove_service(name):
    cfg = load_config()
    services = cfg.get("services", {})
    if name not in services:
        print(f"Service '{name}' not found in config.")
        return
    del services[name]
    cfg["services"] = services
    save_config(cfg)
    print(f"Removed service '{name}' from config.")

def show_config():
    cfg = load_config()
    print("Current configuration:")
    print(json.dumps(cfg, indent=4))

# Check for the config file and create default if missing
if not os.path.exists(config_file):
    print(f"Config file not found: {config_file}")
    print("This seems to be the first run of tuptime.")
    default_config = {"services": {}}
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    with open(config_file, 'w') as f:
        json.dump(default_config, f, indent=4)
    print(f"Default config file created: {config_file}")
else:
    print(f"Config file found: {config_file}")

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
parser.add_argument('-P', '--password', metavar='PASS', help='Set the password for the service (SMB/FTP/SSH)')
parser.add_argument('-p', '--port', metavar='PORT', type=int, help='Port number for the service')
parser.add_argument('-t', '--target', metavar='TARGET', help='Target hostname or IP address (required when adding)')
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
port = args.port
target = args.target

# placeholder output
print(f"Action: {action}")
print(f"Service name: {service_name}")
print(f"Service type: {service_type}")
print(f"Target: {target}")
print(f"Port: {port}")
print(f"Interval: {interval}")
print(f"Username: {username}")
print(f"Password: {'***' if password else None}")

# Execute the chosen action
if action == 'add':
    add_service(service_name, service_type, interval, username, password, target, port)
    sys.exit(0)
elif action == 'remove':
    remove_service(service_name)
    sys.exit(0)
elif action == 'show_config':
    show_config()
    sys.exit(0)
elif action == 'show_version':
    print(f"tuptime version {VERSION}")
    sys.exit(0)
elif action and action.startswith('daemon_'):
    if action == 'daemon_start':
        print("Starting daemon (not yet implemented).")
    elif action == 'daemon_stop':
        print("Stopping daemon (not yet implemented).")
    sys.exit(0)

