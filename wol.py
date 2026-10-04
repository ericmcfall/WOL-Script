#!/usr/bin/env python3
"""Send Wake-on-LAN magic packets, on demand or every day at a set time.

Settings (MAC addresses, wake time, broadcast address, port) live in
config.json next to this script. Every computer listed in "mac_addresses"
is woken at the same time. Edit that file directly, or use the commands
below. A running scheduler re-reads the file every loop, so changes take
effect without restarting it.

Usage:
    python3 wol.py send                  # wake all computers right now
    python3 wol.py run                   # stay running, wake all daily at the configured time
    python3 wol.py add-mac AA:BB:CC:DD:EE:FF
    python3 wol.py remove-mac AA:BB:CC:DD:EE:FF
    python3 wol.py set-mac AA:BB:CC:DD:EE:FF 11:22:33:44:55:66   # replace the whole list
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
    "mac_addresses": ["AA:BB:CC:DD:EE:FF"],
    "wake_time": "07:00",
    "broadcast_address": "255.255.255.255",
    "port": 9,
    "delay_seconds": 1,
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
        log.warning("Created default config at %s - edit it with your computers' MAC addresses.", path)
    with path.open() as f:
        raw = json.load(f)
    # Older configs had a single "mac_address" string instead of a list.
    old_mac = raw.pop("mac_address", None)
    if old_mac and "mac_addresses" not in raw:
        raw["mac_addresses"] = [old_mac]
    config = {**DEFAULT_CONFIG, **raw}
    if isinstance(config["mac_addresses"], str):
        config["mac_addresses"] = [config["mac_addresses"]]
    # Validate early so mistakes show up immediately, not at wake time.
    if not config["mac_addresses"]:
        raise ValueError(f'No MAC addresses listed in "mac_addresses" in {path}')
    for mac in config["mac_addresses"]:
        normalize_mac(mac)
    parse_time(config["wake_time"])
    config["port"] = int(config["port"])
    try:
        delay = float(config["delay_seconds"])
    except (TypeError, ValueError):
        delay = -1
    if delay < 0:
        raise ValueError(f'"delay_seconds" must be a number of seconds, 0 or more, in {path}')
    return config


def save_config(path, config):
    with path.open("w") as f:
        json.dump(config, f, indent=4)
        f.write("\n")


def update_config(path, key, value):
    config = load_config(path)
    config[key] = value
    save_config(path, config)
    print(f"Updated {key} = {json.dumps(value)} in {path}")


def add_macs(path, macs):
    current = load_config(path)["mac_addresses"]
    known = {normalize_mac(m) for m in current}
    for mac in macs:
        if normalize_mac(mac) in known:
            print(f"{mac} is already in the list")
        else:
            current.append(mac)
            known.add(normalize_mac(mac))
    update_config(path, "mac_addresses", current)


def remove_macs(path, macs):
    current = load_config(path)["mac_addresses"]
    to_remove = {normalize_mac(m) for m in macs}
    remaining = [m for m in current if normalize_mac(m) not in to_remove]
    missing = to_remove - {normalize_mac(m) for m in current}
    for mac in macs:
        if normalize_mac(mac) in missing:
            print(f"{mac} was not in the list")
    if not remaining:
        raise ValueError("Can't remove every MAC address; at least one must remain")
    update_config(path, "mac_addresses", remaining)


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
    """Wake every listed computer, pausing delay_seconds between each one.

    A failure for one computer doesn't stop the rest. Returns True if every
    packet was sent.
    """
    ok = True
    for i, mac in enumerate(config["mac_addresses"]):
        if i > 0:
            time.sleep(float(config["delay_seconds"]))
        try:
            send_magic_packet(mac, config["broadcast_address"], config["port"])
        except OSError as e:
            log.error("Failed to send magic packet to %s: %s", mac, e)
            ok = False
    return ok


# --- scheduler --------------------------------------------------------------

def next_run(wake_time, now):
    hour, minute = parse_time(wake_time)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def run_scheduler(config_path):
    """Wake the computer every day at the configured time.

    The config is re-read on every loop, so edits to the MAC addresses or wake
    time are picked up within about 30 seconds without a restart.
    """
    config = load_config(config_path)
    target = next_run(config["wake_time"], datetime.now())
    log.info("Scheduler started. Next wake for %s at %s",
             ", ".join(config["mac_addresses"]), target.strftime("%Y-%m-%d %H:%M"))

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
        if new_config["mac_addresses"] != config["mac_addresses"]:
            log.info("MAC addresses changed to %s", ", ".join(new_config["mac_addresses"]))
        config = new_config

        if now >= target:
            send_from_config(config)
            target = next_run(config["wake_time"], now)
            log.info("Next wake at %s", target.strftime("%Y-%m-%d %H:%M"))


# --- cli --------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Wake-on-LAN sender and daily scheduler.")
    parser.add_argument("-c", "--config", type=Path, default=DEFAULT_CONFIG_PATH,
                        help=f"path to config file (default: {DEFAULT_CONFIG_PATH})")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("send", help="wake all listed computers now")
    sub.add_parser("run", help="run continuously and wake all listed computers daily at the configured time")
    sub.add_parser("show", help="show current settings")
    p = sub.add_parser("add-mac", help="add one or more MAC addresses to the list")
    p.add_argument("macs", nargs="+", metavar="MAC")
    p = sub.add_parser("remove-mac", help="remove one or more MAC addresses from the list")
    p.add_argument("macs", nargs="+", metavar="MAC")
    p = sub.add_parser("set-mac", help="replace the whole list with the given MAC address(es)")
    p.add_argument("macs", nargs="+", metavar="MAC")
    p = sub.add_parser("set-time", help="change the daily wake time (24-hour HH:MM)")
    p.add_argument("time")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    try:
        if args.command == "send":
            if not send_from_config(load_config(args.config)):
                return 1
        elif args.command == "run":
            run_scheduler(args.config)
        elif args.command == "show":
            print(json.dumps(load_config(args.config), indent=4))
        elif args.command in ("add-mac", "remove-mac", "set-mac"):
            macs = [m.strip() for m in args.macs]
            for mac in macs:
                normalize_mac(mac)
            if args.command == "add-mac":
                add_macs(args.config, macs)
            elif args.command == "remove-mac":
                remove_macs(args.config, macs)
            else:
                update_config(args.config, "mac_addresses", macs)
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
