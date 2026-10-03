#!/usr/bin/env python3
"""Send a Wake-on-LAN magic packet, on demand or every day at a set time.

Settings (MAC address, wake time, broadcast address, port) live in
config.json next to this script. Edit that file directly, or use the
`set-mac` / `set-time` commands. A running scheduler re-reads the file
every loop, so changes take effect without restarting it.

Usage:
    python3 wol.py send                  # wake the computer right now
    python3 wol.py run                   # stay running, wake daily at the configured time
    python3 wol.py set-mac AA:BB:CC:DD:EE:FF
    python3 wol.py set-time 07:30
    python3 wol.py show                  # print the current settings

Uses only the Python standard library.
"""

import argparse
import json
import logging
import re
import socket
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

DEFAULT_CONFIG = {
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "wake_time": "07:00",
    "broadcast_address": "255.255.255.255",
    "port": 9,
}

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:\-.]?[0-9A-Fa-f]{2}){5}$")
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

log = logging.getLogger("wol")


# --- config -----------------------------------------------------------------

def normalize_mac(mac):
    """Return the MAC as 12 hex digits, or raise ValueError."""
    mac = mac.strip()
    if not MAC_RE.match(mac):
        raise ValueError(f"Invalid MAC address: {mac!r} (expected e.g. AA:BB:CC:DD:EE:FF)")
    return re.sub(r"[:\-.]", "", mac).upper()


def parse_time(value):
    """Parse 'HH:MM' (24-hour) into (hour, minute), or raise ValueError."""
    match = TIME_RE.match(value.strip())
    if not match:
        raise ValueError(f"Invalid time: {value!r} (expected 24-hour HH:MM, e.g. 07:30)")
    return int(match.group(1)), int(match.group(2))


def load_config(path):
    if not path.exists():
        save_config(path, DEFAULT_CONFIG)
        log.warning("Created default config at %s - edit it with your computer's MAC address.", path)
    with path.open() as f:
        config = {**DEFAULT_CONFIG, **json.load(f)}
    # Validate early so mistakes show up immediately, not at wake time.
    normalize_mac(config["mac_address"])
    parse_time(config["wake_time"])
    config["port"] = int(config["port"])
    return config


def save_config(path, config):
    with path.open("w") as f:
        json.dump(config, f, indent=4)
        f.write("\n")


def update_config(path, key, value):
    config = load_config(path)
    config[key] = value
    save_config(path, config)
    print(f"Updated {key} = {value} in {path}")


# --- wake-on-lan ------------------------------------------------------------

def send_magic_packet(mac, broadcast="255.255.255.255", port=9):
    """Broadcast a magic packet: 6 x 0xFF followed by the MAC repeated 16 times."""
    mac_bytes = bytes.fromhex(normalize_mac(mac))
    packet = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))
    log.info("Sent magic packet to %s via %s:%d", mac, broadcast, port)


def send_from_config(config):
    send_magic_packet(config["mac_address"], config["broadcast_address"], config["port"])


# --- scheduler --------------------------------------------------------------

def next_run(wake_time, now):
    hour, minute = parse_time(wake_time)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def run_scheduler(config_path):
    """Wake the computer every day at the configured time.

    The config is re-read on every loop, so edits to the MAC address or wake
    time are picked up within about 30 seconds without a restart.
    """
    config = load_config(config_path)
    target = next_run(config["wake_time"], datetime.now())
    log.info("Scheduler started. Next wake for %s at %s",
             config["mac_address"], target.strftime("%Y-%m-%d %H:%M"))

    while True:
        time.sleep(min(30, max(1, (target - datetime.now()).total_seconds())))
        now = datetime.now()

        try:
            new_config = load_config(config_path)
        except (ValueError, json.JSONDecodeError) as e:
            log.error("Config error, keeping previous settings: %s", e)
            new_config = config

        if new_config["wake_time"] != config["wake_time"]:
            target = next_run(new_config["wake_time"], now)
            log.info("Wake time changed to %s. Next wake at %s",
                     new_config["wake_time"], target.strftime("%Y-%m-%d %H:%M"))
        if new_config["mac_address"] != config["mac_address"]:
            log.info("MAC address changed to %s", new_config["mac_address"])
        config = new_config

        if now >= target:
            try:
                send_from_config(config)
            except OSError as e:
                log.error("Failed to send magic packet: %s", e)
            target = next_run(config["wake_time"], now)
            log.info("Next wake at %s", target.strftime("%Y-%m-%d %H:%M"))


# --- cli --------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Wake-on-LAN sender and daily scheduler.")
    parser.add_argument("-c", "--config", type=Path, default=DEFAULT_CONFIG_PATH,
                        help=f"path to config file (default: {DEFAULT_CONFIG_PATH})")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("send", help="send a magic packet now")
    sub.add_parser("run", help="run continuously and wake daily at the configured time")
    sub.add_parser("show", help="show current settings")
    p = sub.add_parser("set-mac", help="change the target MAC address")
    p.add_argument("mac")
    p = sub.add_parser("set-time", help="change the daily wake time (24-hour HH:MM)")
    p.add_argument("time")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    try:
        if args.command == "send":
            send_from_config(load_config(args.config))
        elif args.command == "run":
            run_scheduler(args.config)
        elif args.command == "show":
            print(json.dumps(load_config(args.config), indent=4))
        elif args.command == "set-mac":
            normalize_mac(args.mac)
            update_config(args.config, "mac_address", args.mac.strip())
        elif args.command == "set-time":
            hour, minute = parse_time(args.time)
            update_config(args.config, "wake_time", f"{hour:02d}:{minute:02d}")
    except (ValueError, json.JSONDecodeError) as e:
        log.error("%s", e)
        return 1
    except KeyboardInterrupt:
        log.info("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
