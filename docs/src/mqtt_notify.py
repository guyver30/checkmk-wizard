#!/usr/bin/env python3
"""
CheckMK Notification Script - MQTT Publisher
Triggers MQTT publish on service state changes
"""

import sys
import os
import json
import paho.mqtt.client as mqtt
from datetime import datetime

# ========== CONFIGURATION ==========
MQTT_BROKER = "192.168.10.51"
MQTT_PORT = 1883
MQTT_BASE_TOPIC = "checkmk"
HISTORY_FILE = "/omd/sites/monitoring/tmp/mqtt_change_history.json"
MAX_HISTORY = 10
# ===================================

def load_history():
    """Load change history"""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        return []
    except:
        return []

def save_history(history):
    """Save change history"""
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f)
    except Exception as e:
        sys.stderr.write(f"Error saving history: {e}\n")

def add_to_history(change_data):
    """Add change to history"""
    history = load_history()
    history_entry = {
        'timestamp': datetime.now().isoformat(),
        'change_count': 1,
        'changes': [change_data]
    }
    history.insert(0, history_entry)
    history = history[:MAX_HISTORY]
    save_history(history)
    return history

def publish_to_mqtt(notification_context):
    """Publish notification to MQTT"""

    def get_var(key, default=None):
        """Get env var, treating unexpanded macros ($VAR$) as missing"""
        val = notification_context.get(key, default)
        if isinstance(val, str) and val.startswith('$') and val.endswith('$'):
            return default
        return val

    # All CheckMK notification vars use NOTIFY_ prefix
    notification_type = get_var('NOTIFY_NOTIFICATIONTYPE', 'PROBLEM')
    host_name        = get_var('NOTIFY_HOSTNAME', 'unknown')
    host_address     = get_var('NOTIFY_HOSTADDRESS', 'unknown')
    service_desc     = get_var('NOTIFY_SERVICEDESC', None)

    # NOTIFY_WHAT is the reliable way to distinguish HOST vs SERVICE
    notify_what = get_var('NOTIFY_WHAT', 'HOST')

    if notify_what == 'SERVICE' and service_desc:
        # Service notification
        old_state = get_var('NOTIFY_PREVIOUSSERVICEHARDSTATE', 'UNKNOWN')
        new_state = get_var('NOTIFY_SERVICESTATE', 'UNKNOWN')
        output    = get_var('NOTIFY_SERVICEOUTPUT', '')

        state_map = {'OK': 0, 'WARNING': 1, 'CRITICAL': 2, 'UNKNOWN': 3}
        change_data = {
            'host': host_name,
            'address': host_address,
            'service': service_desc,
            'old_state': state_map.get(old_state, 3),
            'old_state_text': old_state,
            'new_state': state_map.get(new_state, 3),
            'new_state_text': new_state,
            'output': output,
            'notification_type': notification_type
        }
    else:
        # Host notification
        old_state = get_var('NOTIFY_PREVIOUSHOSTHARDSTATE', 'UP')
        new_state = get_var('NOTIFY_HOSTSTATE', 'UP')
        output    = get_var('NOTIFY_HOSTOUTPUT', '')

        state_map = {'UP': 0, 'DOWN': 1, 'UNREACHABLE': 2}
        change_data = {
            'host': host_name,
            'address': host_address,
            'service': 'HOST',
            'old_state': state_map.get(old_state, 0),
            'old_state_text': old_state,
            'new_state': state_map.get(new_state, 0),
            'new_state_text': new_state,
            'output': output,
            'notification_type': notification_type
        }

    # Connect to MQTT and publish
    try:
        client = mqtt.Client(client_id="checkmk_notify")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)

        # Start network loop to process messages
        client.loop_start()

        timestamp = datetime.now().isoformat()

        # 1. Publish individual change
        msg1 = client.publish(
            f"{MQTT_BASE_TOPIC}/events/change",
            json.dumps({'timestamp': timestamp, 'change': change_data}),
            qos=1, retain=False
        )

        # 2. Add to history and publish
        history = add_to_history(change_data)
        msg2 = client.publish(
            f"{MQTT_BASE_TOPIC}/history",
            json.dumps(history),
            qos=1, retain=True
        )

        # 3. Publish state change details
        msg3 = client.publish(
            f"{MQTT_BASE_TOPIC}/state_changes",
            json.dumps({'timestamp': timestamp, 'count': 1, 'changes': [change_data]}),
            qos=1, retain=False
        )

        # Wait for all messages to be transmitted before disconnecting
        msg1.wait_for_publish()
        msg2.wait_for_publish()
        msg3.wait_for_publish()

        client.loop_stop()
        client.disconnect()

        sys.stdout.write(f"Published to MQTT: {host_name} - {service_desc if service_desc else 'HOST'} {old_state} -> {new_state}\n")
        return 0

    except Exception as e:
        sys.stderr.write(f"MQTT publish error: {e}\n")
        return 2

def main():
    """Main notification handler"""
    notification_context = dict(os.environ)
    sys.stdout.write("MQTT Notification triggered\n")
    exit_code = publish_to_mqtt(notification_context)
    sys.exit(exit_code)

if __name__ == '__main__':
    main()
