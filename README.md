# WOL-Script

A small Python script that sends a Wake-on-LAN "magic packet" to a computer on
your network. It can do this right away or every day at a set time. It uses only
the Python standard library, so there's nothing to install.

## Requirements

The only requirement is **Python 3.7 or newer**. The script uses only modules
that come with Python, so you don't need `pip install` or any other packages.

### Installing Python on Windows 11

Windows 11 doesn't come with Python. Install it one of these ways:

- **python.org (recommended):** download the latest Python 3 installer from
  <https://www.python.org/downloads/windows/> and run it. On the first screen,
  check **"Add python.exe to PATH"**, then click **Install Now**.
- **winget:** open Terminal or PowerShell and run
  `winget install Python.Python.3.13`. If a newer version is out, run
  `winget search Python.Python` to find its ID.
- **Microsoft Store:** search for "Python 3.13" (or the latest version) and
  install it.

To check that it worked, open a new Terminal window and run:

```powershell
python --version
```

It should print `Python 3.x.x`. If `python` isn't found, try the `py` launcher
(`py --version`), which the python.org installer adds. Then use `py wol.py send`
in place of `python3 wol.py send` in the commands below.

On Windows, replace `python3` with `python` (or `py`) in all the examples in
this README.

## Setup

1. Turn on Wake-on-LAN for the target computer, in its BIOS/UEFI and in the
   network adapter settings of its operating system.
2. Find the target computer's MAC address:
   - Windows: `ipconfig /all` (look for "Physical Address")
   - macOS: `ifconfig en0 | grep ether`
   - Linux: `ip link`
3. Put the MAC address and the wake time in `config.json`:

```json
{
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "wake_time": "07:00",
    "broadcast_address": "255.255.255.255",
    "port": 9
}
```

| Setting             | Meaning                                                                                  |
|---------------------|------------------------------------------------------------------------------------------|
| `mac_address`       | MAC of the computer to wake. `:`, `-`, `.` or no separators all work.                    |
| `wake_time`         | Daily wake time in 24-hour `HH:MM`, in the local time of the machine running the script. |
| `broadcast_address` | Usually fine as is. If the packet doesn't arrive, try your subnet's broadcast address, e.g. `192.168.1.255`. |
| `port`              | UDP port, normally `9` (sometimes `7`).                                                  |

## Usage

```bash
python3 wol.py send                      # wake the computer now (good for testing)
python3 wol.py run                       # keep running and wake it every day at wake_time
python3 wol.py show                      # print the current settings
python3 wol.py set-mac 11:22:33:44:55:66 # change the MAC address
python3 wol.py set-time 06:45            # change the wake time
```

To use a different config file, pass `-c path/to/config.json` before the command.

You can change the time or MAC address while `run` is going, by editing
`config.json` or with `set-time` / `set-mac`. The scheduler re-reads the file
about every 30 seconds and picks up the change without a restart.

## Running it automatically

Run the script on a machine that stays on and is on the same network as the
target, such as a Raspberry Pi, a NAS or a home server.

### Option A: built-in scheduler (any OS)

Start `python3 wol.py run` when the machine boots. On Linux with systemd, create
`/etc/systemd/system/wol.service`, replacing the paths with your own:

```ini
[Unit]
Description=Daily Wake-on-LAN
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/WOL-Script/wol.py run
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Then run `sudo systemctl enable --now wol.service`. To see the log, run
`journalctl -u wol -f`.

### Option B: your OS scheduler

You can also have the OS run `wol.py send` once a day. With this option, the
wake time is set in the OS scheduler and `wake_time` in `config.json` is
ignored.

- **Linux/macOS (cron):** `crontab -e`, then add
  `0 7 * * * /usr/bin/python3 /path/to/WOL-Script/wol.py send`
- **Windows (Task Scheduler):** create a daily task whose action is
  `python` with arguments `C:\path\to\WOL-Script\wol.py send`.

To use Option A on Windows instead, create a Task Scheduler task triggered
"At startup" (or "At log on"). Set its program to `pythonw.exe`, which runs
without a console window, and its arguments to
`C:\path\to\WOL-Script\wol.py run`.
