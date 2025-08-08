import os
import sys
import json
import argparse
import signal
import time
import threading
import subprocess

from datetime import datetime, timezone

import daemon
from daemon.pidfile import PIDLockFile

import requests
import urllib3
from urllib.parse import urlparse
# Disable warnings for self-signed certs
from requests.exceptions import SSLError, RequestException
from urllib3.exceptions import InsecureRequestWarning
urllib3.disable_warnings(InsecureRequestWarning)

from smb.SMBConnection import SMBConnection

from ftplib import FTP, error_perm, all_errors

import socket
import paramiko

VERSION = "1.0.1"

# Text coloring
class bcolors:
    HEADER = '\033[95m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'

# Determine base directory
if sys.platform.startswith('linux'):
    base_dir = os.path.join(os.getenv('HOME'), '.config', 'tum')
elif sys.platform.startswith('darwin'):
    base_dir = os.path.join(os.getenv('HOME'), 'Library', 'Application Support', 'tum')

config_file = os.path.join(base_dir, 'config.json')
pidfile     = os.path.join(base_dir, 'tum.pid')
logfile     = os.path.join(base_dir, 'tum.log')
metrics_dir = os.path.join(base_dir, 'metrics')

def load_config():
    if not os.path.exists(config_file):
        return {}
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(bcolors.FAIL + f"Failed to load config: {e}" + bcolors.ENDC)
        return {}

def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, 'w') as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print(bcolors.FAIL + f"Failed to save config: {e}" + bcolors.ENDC)

def show_help():
    print("Usage: tum [options]")
    print("Options:")
    print("  -h, --help               Show this help message and exit")
    print("  -c, --config             Show the current configuration")
    print("  -v, --version            Show the version of tum")
    print("  -a, --add <name>         Add a new service to monitor (requires -t/--target and -s/--service)")
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

def add_service(name, service_type, interval, username, password, target, port, location):
    if not service_type:
        print(bcolors.FAIL + "Error: --service is required when adding a service." + bcolors.ENDC)
        return
    if not target:
        print(bcolors.FAIL + "Error: --target is required when adding a service." + bcolors.ENDC)
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
        print(bcolors.WARNING + f"Service '{name}' already exists in config." + bcolors.ENDC)
        return
    entry = {
        "name": name,
        "service_type": service_type,
        "target": target,
        "port": port,
        "location": location or "/",
        "username": username or "",
        "password": password or "",
        "interval": interval
    }
    services[name] = entry
    cfg["services"] = services
    save_config(cfg)
    print(bcolors.OKGREEN + f"Added service '{name}' with type {service_type}, target {target}, port {port} to config." + bcolors.ENDC)

def remove_service(name):
    cfg = load_config()
    services = cfg.get("services", {})
    if name not in services:
        print(bcolors.WARNING + f"Service '{name}' not found in config." + bcolors.ENDC)
        return
    del services[name]
    cfg["services"] = services
    save_config(cfg)
    print(bcolors.OKGREEN + f"Removed service '{name}' from config." + bcolors.ENDC)

def show_config():
    cfg = load_config()
    print("Current configuration:")
    print(json.dumps(cfg, indent=4))

def is_daemon_running():
    if not os.path.exists(pidfile):
        return False, None
    try:
        with open(pidfile, 'r') as f:
            pid = int(f.read().strip() or 0)
    except Exception:
        return False, None
    try:
        os.kill(pid, 0)
        return True, pid
    except Exception:
        return False, pid

def format_duration(seconds):
    # Skipping leading zero units for time
    total = int(seconds)
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or parts:
        parts.append(f"{hours}h")
    if minutes or parts:
        parts.append(f"{minutes}m")
    # Always include seconds
    parts.append(f"{secs}s")
    return " ".join(parts)

def show_status_all_services():
    if not is_daemon_running()[0]:
        print(bcolors.WARNING + "Daemon is not running. Start with 'tum -d start'." + bcolors.ENDC)
        return
    
    cfg = load_config()
    services = cfg.get("services", {})
    if not services:
        print(bcolors.WARNING + "No services configured." + bcolors.ENDC)
        return

    print("Service status:")
    for name, svc in services.items():
        metrics_file = os.path.join(metrics_dir, f"{name}.json")
        try:
            with open(metrics_file, 'r') as f:
                metrics = json.load(f)
        except Exception:
            print(f"- {name} ({svc['service_type']}): no metrics available yet")
            continue

        status = (bcolors.OKGREEN + "UP" + bcolors.ENDC) if metrics.get("isup") else (bcolors.FAIL + "DOWN" + bcolors.ENDC)

        uptime = metrics.get("total_uptime", 0)
        downtime = metrics.get("total_downtime", 0)
        total_time = uptime + downtime
        up_pct = (uptime / total_time * 100) if total_time > 0 else 0
        down_pct = (downtime / total_time * 100) if total_time > 0 else 0

        print(bcolors.HEADER + f"- {name} ({svc['service_type']}): {status}" + bcolors.ENDC)
        print(f"    Target:   {svc['target']}")
        print(f"    Uptime:   {up_pct:.2f}% ({format_duration(uptime)})")
        print(f"    Downtime: {down_pct:.2f}% ({format_duration(downtime)})")

        last_down = metrics.get("last_downtime")
        if last_down:
            print(f"    Last downtime: {last_down}")
        else:
            print("    Last downtime: N/A")

def monitor_icmp_service(name, svc):
    target   = svc['target']
    interval = svc.get('interval', 60)
    os.makedirs(metrics_dir, exist_ok=True)
    metrics_file = os.path.join(metrics_dir, f"{name}.json")
    try:
        with open(metrics_file, 'r') as f:
            metrics = json.load(f)
    except Exception:
        metrics = {'isup': False, 'total_uptime': 0, 'total_downtime': 0, 'last_downtime': None}

    while True:
        try:
            # Invoke system ping to bypass root requirements
            completed = subprocess.run(
                ["ping", "-c", "1", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=interval
            )
            up = (completed.returncode == 0)
        except subprocess.TimeoutExpired:
            up = False
        except Exception:
            up = False

        if up:
            metrics['total_uptime'] += interval
        else:
            metrics['total_downtime'] += interval
            if metrics.get('isup', True):
                metrics['last_downtime'] = datetime.now(timezone.utc).isoformat()
        metrics['isup'] = up

        with open(metrics_file, 'w') as f:
            json.dump(metrics, f, indent=4)

        with open(logfile, 'a+') as lf:
            status = 'UP' if up else 'DOWN'
            lf.write(f"{datetime.now(timezone.utc).isoformat()} - ICMP '{name}' ({target}): {status}\n")

        time.sleep(interval)

def monitor_http_service(name, svc):
    # Fetch a URL via HTTPS first then HTTP on failure
    
    raw = svc['target']
    arg_loc = svc.get('location', '').strip()
    parsed = urlparse(raw)

    # Hostname (no scheme, no port)
    host = parsed.hostname or raw

    # Determine port: explicit svc["port"] > parsed.port > default by scheme
    if svc.get('port'):
        port = svc['port']
    elif parsed.port:
        port = parsed.port
    else:
        port = 443 if parsed.scheme == 'https' else 80

    # Determine location: CLI arg beats parsed.path; otherwise use parsed.path
    if arg_loc != '/':
        loc = arg_loc
    else:
        loc = parsed.path or '/'
    # Ensure leading slash
    if not loc.startswith('/'):
        loc = '/' + loc

    if port == 80 or port == 443:
        # If port is default for HTTP/HTTPS, don't include it in the URL
        https_url = f"https://{host}{loc}"
        http_url  = f"http://{host}{loc}"
    else:
        https_url = f"https://{host}:{port}{loc}"
        http_url  = f"http://{host}:{port}{loc}"

    interval = svc.get('interval', 60)
    os.makedirs(metrics_dir, exist_ok=True)
    metrics_file = os.path.join(metrics_dir, f"{name}.json")
    try:
        with open(metrics_file, 'r') as f:
            metrics = json.load(f)
    except Exception:
        metrics = {'isup': False, 'total_uptime': 0,
                   'total_downtime': 0, 'last_downtime': None}

    while True:
        up = False
        # Try HTTPS first, then HTTP on SSL errors
        for url in (https_url, http_url):
            try:
                resp = requests.get(url, timeout=interval, verify=False)
                if 200 <= resp.status_code < 400:
                    up = True
                break
            except SSLError:
                # Bad cert or TLS issue
                continue
            except RequestException:
                # Network error, timeout, DNS failure
                break

        if up:
            metrics['total_uptime'] += interval
        else:
            metrics['total_downtime'] += interval
            if metrics.get('isup', True):
                metrics['last_downtime'] = datetime.now(timezone.utc).isoformat()
        metrics['isup'] = up

        with open(metrics_file, 'w') as f:
            json.dump(metrics, f, indent=4)

        tried = up and https_url or http_url
        with open(logfile, 'a+') as lf:
            status = 'UP' if up else 'DOWN'
            lf.write(f"{datetime.now(timezone.utc).isoformat()} - HTTP '{name}' ({tried}): {status}\n")

        time.sleep(interval)

def monitor_smb_service(name, svc):
    # Check SMB share and optionally verify access to a specific folder/file

    raw       = svc['target']
    parsed    = urlparse(raw if '://' in raw else f"//{raw}")
    host      = parsed.hostname or raw
    port      = svc.get('port', 445)
    loc       = svc.get('location', '/').strip()
    interval  = svc.get('interval', 60)

    # Parse share and optional subpath
    parts  = loc.lstrip('/').split('/', 1)
    share  = parts[0]
    path   = parts[1] if len(parts) > 1 else ''

    os.makedirs(metrics_dir, exist_ok=True)
    metrics_file = os.path.join(metrics_dir, f"{name}.json")
    try:
        with open(metrics_file, 'r') as f:
            metrics = json.load(f)
    except Exception:
        metrics = {
            'isup': False,
            'total_uptime':   0,
            'total_downtime': 0,
            'last_downtime':  None
        }

    while True:
        up = False
        try:
            # Connect to the share
            conn = SMBConnection(
                # Connect as guest if no username provided
                svc.get('username', 'GUEST'),
                svc.get('password', ''),
                'monitor-client',  # Any client name
                host,
                use_ntlm_v2=True
            )
            if conn.connect(host, port, timeout=interval):
                if path:
                    # If they specified a file/folder, verify it exists
                    dirname, filename = os.path.split(path)
                    files = conn.listPath(share, dirname or '/')
                    up = any(f.filename == filename for f in files)
                else:
                    # Just connecting to the share is enough
                    up = True
                conn.close()
        except Exception:
            up = False

        if up:
            metrics['total_uptime'] += interval
        else:
            metrics['total_downtime'] += interval
            if metrics.get('isup', True):
                metrics['last_downtime'] = datetime.now(timezone.utc).isoformat()
        metrics['isup'] = up

        with open(metrics_file, 'w') as f:
            json.dump(metrics, f, indent=4)

        with open(logfile, 'a+') as lf:
            status = 'UP' if up else 'DOWN'
            lf.write(f"{datetime.now(timezone.utc).isoformat()} - SMB '{name}' ({host}/{share}{('/' + path) if path else ''}): {status}\n")

        time.sleep(interval)

def monitor_ftp_service(name, svc):
    # Check FTP connectivity and optional access to a specific folder/file.

    raw      = svc['target']
    parsed   = urlparse(raw if '://' in raw else f"//{raw}")
    host     = parsed.hostname or raw
    port     = svc.get('port', 21)
    loc      = svc.get('location', '/').strip()
    interval = svc.get('interval', 60)

    # Normalize location
    if not loc.startswith('/'):
        loc = '/' + loc

    os.makedirs(metrics_dir, exist_ok=True)
    metrics_file = os.path.join(metrics_dir, f"{name}.json")
    try:
        with open(metrics_file, 'r') as f:
            metrics = json.load(f)
    except Exception:
        metrics = {
            'isup': False,
            'total_uptime':   0,
            'total_downtime': 0,
            'last_downtime':  None
        }

    while True:
        up = False
        try:
            ftp = FTP()
            ftp.connect(host, port, timeout=interval)
            # Login (anonymous if no creds)
            ftp.login(
                user=svc.get('username') or 'anonymous',
                passwd=svc.get('password') or ''
            )
            # If they specified a path, try to CWD there
            if loc and loc != '/':
                ftp.cwd(loc)
            # Attempt a simple directory listing
            ftp.nlst()
            up = True
            ftp.quit()
        except all_errors:
            up = False

        if up:
            metrics['total_uptime'] += interval
        else:
            metrics['total_downtime'] += interval
            if metrics.get('isup', True):
                metrics['last_downtime'] = datetime.now(timezone.utc).isoformat()
        metrics['isup'] = up

        with open(metrics_file, 'w') as f:
            json.dump(metrics, f, indent=4)

        with open(logfile, 'a+') as lf:
            status = 'UP' if up else 'DOWN'
            lf.write(f"{datetime.now(timezone.utc).isoformat()} - FTP '{name}' ({host}{loc}): {status}\n")

        time.sleep(interval)

def monitor_ssh_service(name, svc):
    # Check SSH connectivity with provided credentials.
    host     = svc['target']
    port     = svc.get('port', 22)
    user     = svc.get('username') or None
    pwd      = svc.get('password') or None
    interval = svc.get('interval', 60)

    os.makedirs(metrics_dir, exist_ok=True)
    metrics_file = os.path.join(metrics_dir, f"{name}.json")
    try:
        with open(metrics_file, 'r') as f:
            metrics = json.load(f)
    except Exception:
        metrics = {
            'isup': False,
            'total_uptime':   0,
            'total_downtime': 0,
            'last_downtime':  None
        }

    while True:
        up = False
        try:
            # Try a TCP-level check first
            sock = socket.create_connection((host, port), timeout=interval)
            sock.close()

            # If creds given, attempt SSH auth
            if user:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(
                    hostname=host,
                    port=port,
                    username=user,
                    password=pwd,
                    timeout=interval,
                    allow_agent=False,
                    look_for_keys=False
                )
                client.close()

            up = True
        except Exception:
            up = False

        if up:
            metrics['total_uptime'] += interval
        else:
            metrics['total_downtime'] += interval
            if metrics.get('isup', True):
                metrics['last_downtime'] = datetime.now(timezone.utc).isoformat()
        metrics['isup'] = up

        with open(metrics_file, 'w') as f:
            json.dump(metrics, f, indent=4)

        with open(logfile, 'a+') as lf:
            status = 'UP' if up else 'DOWN'
            lf.write(f"{datetime.now(timezone.utc).isoformat()} - SSH '{name}' ({host}:{port}): {status}\n")

        time.sleep(interval)

def daemon_worker():
    def handle_term(signum, frame):
        with open(logfile, "a+") as lf:
            lf.write(f"{datetime.now(timezone.utc).isoformat()} - Received termination signal, exiting daemon.\n")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    with open(logfile, 'a+') as lf:
        lf.write(f"{datetime.now(timezone.utc).isoformat()} - Daemon started, spawning threads.\n")

    cfg = load_config()
    services = cfg.get('services', {})
    threads = []
    for name, svc in services.items():
        svc_type = svc.get('service_type')
        if svc_type == 'ICMP':
            t = threading.Thread(target=monitor_icmp_service, args=(name, svc), daemon=True)
            t.start()
            threads.append(t)
        elif svc_type == 'HTTP':
            t = threading.Thread(target=monitor_http_service, args=(name, svc), daemon=True)
            t.start()
            threads.append(t)
        elif svc_type == 'SMB':
            t = threading.Thread(target=monitor_smb_service, args=(name, svc), daemon=True)
            t.start()
            threads.append(t)
        elif svc_type == 'FTP':
            t = threading.Thread(target=monitor_ftp_service, args=(name, svc), daemon=True)
            t.start()
            threads.append(t)
        elif svc_type == 'SSH':
            t = threading.Thread(target=monitor_ssh_service, args=(name, svc), daemon=True)
            t.start()
            threads.append(t)

    for t in threads:
        t.join()

def start_daemon():
    # Ensure at least one service is configured
    cfg = load_config()
    if not cfg.get('services'):
        print(bcolors.WARNING + "No services configured. Please add a service before starting the daemon." + bcolors.ENDC)
        print(bcolors.WARNING + "Example: tum -a Cloudflare -s ICMP -t 1.1.1.1 -i 5" + bcolors.ENDC)
        return

    print("Starting daemon...")
    running, pid = is_daemon_running()
    if running:
        print(bcolors.WARNING + f"Daemon already running (pid {pid})." + bcolors.ENDC)
        return

    os.makedirs(base_dir, exist_ok=True)
    os.makedirs(os.path.dirname(logfile), exist_ok=True)

    with open(logfile, 'w') as logf:
        logf.write(f"{datetime.now(timezone.utc).isoformat()} - Starting new daemon instance.\n")

    lock = PIDLockFile(pidfile)
    with open(logfile, 'a+') as logf:
        ctx = daemon.DaemonContext(pidfile=lock, stdout=logf, stderr=logf,
                                   umask=0o022, working_directory=base_dir)
        with ctx:
            daemon_worker()

def stop_daemon():
    running, pid = is_daemon_running()
    if not running:
        if os.path.exists(pidfile):
            os.remove(pidfile)
        print(bcolors.WARNING + "Daemon is not running." + bcolors.ENDC)
        return
    os.kill(pid, signal.SIGTERM)
    time.sleep(0.2)
    if os.path.exists(pidfile):
        os.remove(pidfile)
    print(f"Stopped daemon (pid {pid}).")


def show_daemon_status():
    running, pid = is_daemon_running()
    if running:
        mtime = os.path.getmtime(pidfile)
        age = datetime.now() - datetime.fromtimestamp(mtime)
        age_str = str(age).split('.')[0]
        print(f"Daemon running (pid {pid}), age {age_str}")
    else:
        print("Daemon is not running.")

# Check if config file exists
if not os.path.exists(config_file):
    print(bcolors.WARNING + f"Config file not found: {config_file}" + bcolors.ENDC)
    print("This seems to be the first run of tum.")
    default_config = {"services": {}}
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    with open(config_file, 'w') as f:
        json.dump(default_config, f, indent=4)
    print(bcolors.OKGREEN + f"Default config file created: {config_file}" + bcolors.ENDC)

# Take in parameters
parser = argparse.ArgumentParser(prog='tum', add_help=False)
group = parser.add_mutually_exclusive_group()
group.add_argument('-a', '--add',    metavar='NAME', help='Add a new service to monitor')
group.add_argument('-r', '--remove', metavar='NAME', help='Remove a service from monitoring')
group.add_argument('-c', '--config', action='store_true', help='Show the current configuration')
group.add_argument('-v', '--version',action='store_true', help='Show the version of tum')
group.add_argument('-d', '--daemon', metavar='ACTION', choices=['start','stop','status'],
                   help='Start, stop, or show status of the background daemon')

parser.add_argument('-s', '--service', metavar='TYPE', type=lambda s: s.upper(),
                    choices=['ICMP','SMB','FTP','HTTP','SSH'],
                    help='Specify the service type (ICMP/SMB/FTP/HTTP/SSH)')
parser.add_argument('-i', '--interval',metavar='SECONDS', type=int, default=60,
                    help='Set the monitoring interval (default: 60 seconds)')
parser.add_argument('-u', '--username',metavar='USER', help='Set the.username for the service (SMB/FTP/SSH)')
parser.add_argument('-P', '--password',metavar='PASS', help='Set the.password for the service (SMB/FTP/SSH)')
parser.add_argument('-p', '--port',    metavar='PORT', type=int, help='Port number for the service')
parser.add_argument('-t', '--target',  metavar='TARGET', help='Target hostname or IP address (required when adding)')
parser.add_argument('-l', '--location', metavar='LOCATION', default='',
                    help='Location/path for HTTP (URL path) or SMB/FTP (folder/file) checks')
parser.add_argument('-h', '--help',    action='store_true', help='Show this help message and exit')

args = parser.parse_args()

if args.help:
    show_help()
    sys.exit(0)

# Determine action
action = None
service_name = None
if args.add:
    action = 'add';    service_name = args.add
elif args.remove:
    action = 'remove'; service_name = args.remove
elif args.config:
    action = 'show_config'
elif args.version:
    action = 'show_version'
elif args.daemon:
    action = f"daemon_{args.daemon}"

service_type = args.service
interval    = args.interval
username    = args.username
password    = args.password
port        = args.port
target      = args.target
location    = args.location

# Dispatch
if action == 'add':
    add_service(service_name, service_type, interval, username, password, target, port, location)
elif action == 'remove':
    remove_service(service_name)
elif action == 'show_config':
    show_config()
elif action == 'show_version':
    print(f"tum version {VERSION}")
elif action == 'daemon_start':
    start_daemon()
elif action == 'daemon_stop':
    stop_daemon()
elif action == 'daemon_status':
    show_daemon_status()
elif action == None:
    show_status_all_services()
