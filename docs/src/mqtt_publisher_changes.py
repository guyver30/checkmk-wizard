#!/usr/bin/env python3
"""
MQTT Publisher with Change Detection
Only publishes when service states change
"""

import socket
import os
import json
import logging
from logging.handlers import RotatingFileHandler
import paho.mqtt.client as mqtt
from datetime import datetime
import time

# ========== CONFIGURATION ==========
MQTT_BROKER = "192.168.10.51"  # Your Raspberry Pi
MQTT_PORT = 1883
MQTT_BASE_TOPIC = "checkmk"

# State file to track previous states
STATE_FILE = "/omd/sites/monitoring/tmp/mqtt_last_state.json"
HISTORY_FILE = "/omd/sites/monitoring/tmp/mqtt_change_history.json"
LOG_FILE = "/omd/sites/monitoring/var/log/mqtt_publisher.log"
MAX_HISTORY = 10  # Keep last 10 changes
# ===================================

# ========== LOGGING SETUP ==========
logger = logging.getLogger("mqtt_publisher")
logger.setLevel(logging.DEBUG)

# File handler — rotating, 5MB max, keep 3 backups
fh = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

# Console handler — INFO level
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('%(message)s'))

logger.addHandler(fh)
logger.addHandler(ch)
# ====================================

def query_livestatus(query):
    """Query LiveStatus via Unix socket"""
    omd_root = os.environ.get("OMD_ROOT", "/omd/sites/monitoring")
    socket_path = omd_root + "/tmp/run/live"
    
    if not query.endswith('\n\n'):
        query = query.rstrip('\n') + '\n\n'
    
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(socket_path)
    s.send(query.encode('utf-8'))
    s.shutdown(socket.SHUT_WR)
    
    response = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        response += chunk
    
    s.close()
    return response.decode('utf-8')

def get_monitoring_data():
    """Get monitoring data from CheckMK"""
    
    # Query services
    services_result = query_livestatus(
        "GET services\n"
        "Columns: host_name host_address description state plugin_output\n"
    )
    
    # Query statistics
    stats_result = query_livestatus(
        "GET services\n"
        "Stats: state = 0\n"
        "Stats: state = 1\n"
        "Stats: state = 2\n"
        "Stats: state = 3\n"
    )
    
    stats = stats_result.strip().split(';')

    # Query host states (0=UP, 1=DOWN, 2=UNREACHABLE)
    # Needed because a down host still reports stale/cached OK service
    # results - the host's own state is the only reliable "is it alive" signal.
    # "labels" returns CheckMK host labels (e.g. cmk/os_family:linux) as
    # comma-separated "key|value" pairs, e.g. "cmk/os_family|linux,cmk/site|monitoring"
    # (NOT JSON, despite what CheckMK's docs/werks might imply for other output formats).
    hosts_result = query_livestatus(
        "GET hosts\n"
        "Columns: name state plugin_output labels\n"
    )
    host_state_text = ['UP', 'DOWN', 'UNREACHABLE']
    hosts = []
    for line in hosts_result.strip().split('\n'):
        if line:
            parts = line.split(';')
            if len(parts) >= 3:
                state = int(parts[1])
                labels = {}
                if len(parts) >= 4 and parts[3]:
                    for pair in parts[3].split(','):
                        if '|' in pair:
                            key, _, value = pair.partition('|')
                            labels[key] = value
                hosts.append({
                    'host': parts[0],
                    'state': state,
                    'state_text': host_state_text[state] if 0 <= state <= 2 else 'UNKNOWN',
                    'output': parts[2],
                    'labels': labels
                })
    
    # Parse services
    services = []
    for line in services_result.strip().split('\n'):
        if line:
            parts = line.split(';')
            if len(parts) >= 5:
                services.append({
                    'host': parts[0],
                    'address': parts[1],
                    'service': parts[2],
                    'state': int(parts[3]),
                    'state_text': ['OK', 'WARN', 'CRIT', 'UNKNOWN'][int(parts[3])],
                    'output': parts[4]
                })
    
    data = {
        'timestamp': datetime.now().isoformat(),
        'source': 'checkmk_monitoring',
        'location': '192.168.10.42',
        'stats': {
            'total_services': int(stats[0]) + int(stats[1]) + int(stats[2]) + int(stats[3]),
            'services_ok': int(stats[0]),
            'services_warn': int(stats[1]),
            'services_crit': int(stats[2]),
            'services_unknown': int(stats[3])
        },
        'services': services,
        'hosts': hosts
    }
    
    return data

#Added functions to have history of states file. 
def load_history():
    """Load change history from file"""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        logger.warning(f"Could not load history: {e}")
        return []

def save_history(history):
    """Save change history to file"""
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f)
    except Exception as e:
        logger.warning(f"Could not save history: {e}")

def add_to_history(changes, current_data):
    """Add state changes to history"""
    if len(changes['state_changes']) == 0:
        return
    
    history = load_history()
    
    # Create history entry
    history_entry = {
        'timestamp': datetime.now().isoformat(),
        'change_count': len(changes['state_changes']),
        'changes': changes['state_changes']
    }
    
    # Add to front of list
    history.insert(0, history_entry)
    
    # Keep only last MAX_HISTORY entries
    history = history[:MAX_HISTORY]
    
    # Save
    save_history(history)
    
    return history

def load_previous_state():
    """Load previous state from file"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        return None
    except Exception as e:
        logger.warning(f"Could not load previous state: {e}")
        return None

def save_current_state(data):
    """Save current state to file"""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"Could not save state: {e}")

def create_service_key(service):
    """Create unique key for service"""
    return f"{service['host']}::{service['service']}"

def detect_changes(current_data, previous_data):
    """
    Detect changes between current and previous data
    Returns dict with changes information
    """
    
    if previous_data is None:
        return {
            'has_changes': True,
            'is_first_run': True,
            'stats_changed': True,
            'new_services': [],
            'removed_services': [],
            'state_changes': [],
            'message': 'First run - sending all data'
        }
    
    # Create lookup dictionaries
    current_services = {create_service_key(s): s for s in current_data['services']}
    previous_services = {create_service_key(s): s for s in previous_data['services']}
    
    # Check for stats changes
    stats_changed = (
        current_data['stats']['services_ok'] != previous_data['stats']['services_ok'] or
        current_data['stats']['services_warn'] != previous_data['stats']['services_warn'] or
        current_data['stats']['services_crit'] != previous_data['stats']['services_crit'] or
        current_data['stats']['services_unknown'] != previous_data['stats']['services_unknown']
    )
    
    # Find new services
    new_services = []
    for key, service in current_services.items():
        if key not in previous_services:
            new_services.append(service)
    
    # Find removed services
    removed_services = []
    for key, service in previous_services.items():
        if key not in current_services:
            removed_services.append(service)
    
    # Find state changes
    state_changes = []
    for key, current_service in current_services.items():
        if key in previous_services:
            previous_service = previous_services[key]
            if current_service['state'] != previous_service['state']:
                state_changes.append({
                    'host': current_service['host'],
                    'service': current_service['service'],
                    'old_state': previous_service['state'],
                    'old_state_text': previous_service['state_text'],
                    'new_state': current_service['state'],
                    'new_state_text': current_service['state_text'],
                    'output': current_service['output']
                })
    
    # Determine if there are any changes
    has_changes = stats_changed or len(new_services) > 0 or len(removed_services) > 0 or len(state_changes) > 0
    
    # Create message
    if has_changes:
        change_summary = []
        if len(state_changes) > 0:
            change_summary.append(f"{len(state_changes)} state change(s)")
        if len(new_services) > 0:
            change_summary.append(f"{len(new_services)} new service(s)")
        if len(removed_services) > 0:
            change_summary.append(f"{len(removed_services)} removed service(s)")
        
        message = f"Changes detected: {', '.join(change_summary)}"
    else:
        message = "No changes"
    
    return {
        'has_changes': has_changes,
        'is_first_run': False,
        'stats_changed': stats_changed,
        'new_services': new_services,
        'removed_services': removed_services,
        'state_changes': state_changes,
        'message': message
    }

def on_connect(client, userdata, flags, rc):
    """Callback when connected"""
    if rc == 0:
        logger.info(f"Connected to broker: {MQTT_BROKER}:{MQTT_PORT}")
    else:
        logger.error(f"Connection failed: rc={rc}")

def publish_to_mqtt(current_data, changes):
    """Publish data to MQTT broker — simplified to 3 core topics"""
    
    client = mqtt.Client(client_id="checkmk_publisher_changes")
    client.on_connect = on_connect
    
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        time.sleep(1)
        
        timestamp = datetime.now().isoformat()

        # 1. ALWAYS publish status (stats + message)
        status_topic = f"{MQTT_BASE_TOPIC}/status"
        status_data = {
            'timestamp': timestamp,
            'message': changes['message'],
            'stats': current_data['stats']
        }
        client.publish(status_topic, json.dumps(status_data), qos=1, retain=True)
        logger.info(f"Status → {status_topic}: {changes['message']}")
        logger.debug(f"Status payload: {json.dumps(status_data)}")

        # 2. ALWAYS publish ALL services + host states
        all_topic = f"{MQTT_BASE_TOPIC}/services/all"
        all_data = {
            'timestamp': timestamp,
            'count': len(current_data['services']),
            'services': current_data['services'],
            'hosts': current_data.get('hosts', [])
        }
        client.publish(all_topic, json.dumps(all_data), qos=1, retain=True)
        logger.info(f"All Services → {all_topic} ({len(current_data['services'])} services)")
        logger.debug(f"Services payload: {json.dumps(all_data)}")

        # 3. Publish history on state changes
        if changes['has_changes'] and len(changes['state_changes']) > 0:
            for change in changes['state_changes']:
                logger.info(f"State Change: {change['host']} - {change['service']} "
                            f"{change['old_state_text']} → {change['new_state_text']}")
            
            history = add_to_history(changes, current_data)
            history_topic = f"{MQTT_BASE_TOPIC}/history"
            client.publish(history_topic, json.dumps(history), qos=1, retain=True)
            logger.info(f"History → {history_topic} ({len(history)} entries)")
        
        time.sleep(2)
        client.loop_stop()
        client.disconnect()
        
        logger.info(f"Published successfully at {datetime.now().strftime('%H:%M:%S')}")
        return True
        
    except Exception as e:
        logger.error(f"Publish error: {e}", exc_info=True)
        return False

def main():
    """Main function"""
    try:
        logger.info("=" * 60)
        logger.info("CheckMK → MQTT Publisher (Change Detection)")
        logger.info("=" * 60)
        
        # Get current monitoring data
        logger.info("Collecting current data...")
        current_data = get_monitoring_data()
        logger.info(f"Services: {current_data['stats']['total_services']} | "
                     f"OK: {current_data['stats']['services_ok']} | "
                     f"WARN: {current_data['stats']['services_warn']} | "
                     f"CRIT: {current_data['stats']['services_crit']}")
        
        # Load previous state
        logger.info("Checking for changes...")
        previous_data = load_previous_state()
        
        # Detect changes
        changes = detect_changes(current_data, previous_data)
        
        if changes['is_first_run']:
            logger.info("First run - will send all data")
        elif changes['has_changes']:
            logger.info(changes['message'])
        else:
            logger.info("No changes detected")
        
        # Publish to MQTT
        logger.info("Publishing to MQTT...")
        success = publish_to_mqtt(current_data, changes)
        
        # Save current state for next run
        if success:
            save_current_state(current_data)
            logger.info("State saved for next comparison")
        
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)

if __name__ == "__main__":
    main()