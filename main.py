import os
import sys
import json
import argparse
import signal
import time
from datetime import datetime

import daemon
from daemon.pidfile import PIDLockFile

VERSION = "0.1"

# determine base directory
if sys.platform.startswith('linux'):
    base_dir = os.path.join(os.getenv('HOME'), '.config', 'tum')
elif sys.platform.startswith('darwin'):
    base_dir = os.path.join(os.getenv('HOME'), 'Library', 'Application Support', 'tum')

config_file = os.path.join(base_dir, 'config.json')
pidfile = os.path.join(base_dir, 'tum.pid')
logfile = os.path.join(base_dir, 'tum.log')

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
    print("Usage: tum [options]")
    print("Options:")
    print("  -h, --help               Show this help message and exit")
    print("  -c, --config             Show the current configuration")
    print("  -v, --version            Show the version of tum")
    print("  -a, --add <name>         Add a new service to monitor (requires -t/--target)")
    print("  -r, --remove <name>      Remove a service from monitoring")
    print("  -s, --service <type>     Specify the service type (ICMP/SMB/FTP/HTTP/SSH)")
    print("  -i, --interval <seconds> Set the monitoring interval (default: 60 seconds)")
    print("  -u, --username <name>    Set the username for the service (SMB/FTP/SSH)")
    print("  -P, --password <password> Set the password for the service (SMB/FTP/SSH)")
    print("  -p, --port <port>        Set the port for the service (uses sensible defaults if omitted)")
    print("  -t, --target <host>      Target hostname or IP address (required when adding)")
    print("  -d, --daemon <start|stop|status> Start, stop, or show status of the background daemon")
    print("Example:")
    print("  tum -a MyService -s ICMP -t 8.8.8.8 -i 30")
    print("  tum -a Web -s HTTP -t example.com -p 8080")
    print("  tum -d start")
    print("  tum -d status")

def add_service(name, service_type, interval, username, password, target, port):
    if not service_type:
        print("Error: --service is required when adding a service.")
        return
    if not target:
        print("Error: --target is required when adding a service.")
        return
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

def is_daemon_running():
    if not os.path.exists(pidfile):
        return False, None
    try:
        with open(pidfile, 'r') as f:
            pid_str = f.read().strip()
        if not pid_str:
            return False, None
        pid = int(pid_str)
    except Exception:
        return False, None
    try:
        os.kill(pid, 0)
        return True, pid
    except Exception:
        return False, pid

def daemon_worker():
    def handle_term(signum, frame):
        with open(logfile, "a+") as lf:
            lf.write(f"{datetime.utcnow().isoformat()} - Received termination signal, exiting daemon.\n")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    with open(logfile, "a+") as lf:
        lf.write(f"{datetime.utcnow().isoformat()} - Daemon worker started (pid {os.getpid()}).\n")

    while True:
        with open(logfile, "a+") as lf:
            lf.write(f"{datetime.utcnow().isoformat()} - heartbeat\n")
        time.sleep(60)

def start_daemon():
    running, pid = is_daemon_running()
    if running:
        print(f"Daemon already running (pid {pid}).")
        return

    os.makedirs(base_dir, exist_ok=True)
    os.makedirs(os.path.dirname(logfile), exist_ok=True)

    lock = PIDLockFile(pidfile)
    try:
        with open(logfile, "a+") as logf:
            ctx = daemon.DaemonContext(
                pidfile=lock,
                stdout=logf,
                stderr=logf,
                umask=0o022,
                working_directory=base_dir,
                detach_process=True,
            )
            with ctx:
                daemon_worker()
    except Exception as e:
        print(f"Failed to start daemon: {e}")

def stop_daemon():
    running, pid = is_daemon_running()
    if not running:
        if os.path.exists(pidfile):
            print(f"PID file exists but process {pid} not alive; removing stale PID file.")
            try:
                os.remove(pidfile)
            except Exception as e:
                print(f"Could not remove stale pidfile: {e}")
        else:
            print("Daemon is not running.")
        return

    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.2)
        if os.path.exists(pidfile):
            os.remove(pidfile)
        print(f"Sent SIGTERM to daemon (pid {pid}); stopped.")
    except Exception as e:
        print(f"Failed to stop daemon process {pid}: {e}")

def show_daemon_status():
    running, pid = is_daemon_running()
    if running:
        try:
            mtime = os.path.getmtime(pidfile)
            started = datetime.fromtimestamp(mtime)
            age = datetime.now() - started
            age_str = str(age).split('.')[0]
            print(f"Daemon is running (pid {pid}), started {age_str} ago.")
        except Exception:
            print(f"Daemon is running (pid {pid}).")
    else:
        if pid:
            print(f"Daemon PID file exists but process {pid} is not alive.")
        else:
            print("Daemon is not running.")

# check if config file exists
if not os.path.exists(config_file):
    print(f"Config file not found: {config_file}")
    print("This seems to be the first run of tum.")
    default_config = {"services": {}}
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    with open(config_file, 'w') as f:
        json.dump(default_config, f, indent=4)
    print(f"Default config file created: {config_file}")
else:
    print(f"Config file found: {config_file}")

# take in parameters
parser = argparse.ArgumentParser(prog='tum', add_help=False)
group = parser.add_mutually_exclusive_group()
group.add_argument('-a', '--add', metavar='NAME', help='Add a new service to monitor')
group.add_argument('-r', '--remove', metavar='NAME', help='Remove a service from monitoring')
group.add_argument('-c', '--config', action='store_true', help='Show the current configuration')
group.add_argument('-v', '--version', action='store_true', help='Show the version of tum')
group.add_argument('-d', '--daemon', metavar='ACTION', choices=['start', 'stop', 'status'],
                   help='Start, stop, or show status of the background daemon')

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

# Determine action
action = None
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
    action = f"daemon_{args.daemon}"

service_type = args.service 
interval = args.interval
username = args.username
password = args.password
port = args.port
target = args.target

# Debug / placeholder output
print(f"Action: {action}")
print(f"Service name: {service_name}")
print(f"Service type: {service_type}")
print(f"Target: {target}")
print(f"Port: {port}")
print(f"Interval: {interval}")
print(f"Username: {username}")
print(f"Password: {'***' if password else None}")

# Dispatch
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
    print(f"tum version {VERSION}")
    sys.exit(0)
elif action and action.startswith('daemon_'):
    if action == 'daemon_start':
        start_daemon()
    elif action == 'daemon_stop':
        stop_daemon()
    elif action == 'daemon_status':
        show_daemon_status()
    sys.exit(0)
