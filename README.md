# AK500 Digital Pro

Daemon for the **DeepCool AK500 Digital Pro** (`3633:0011`) cooler display on Linux (CachyOS / Arch) and Windows.

Includes a static **Go** implementation (`main.go`) and a zero-dependency **Python** implementation (`ak500d.py`).

## Linux Installation (CachyOS / Arch)

```bash
sudo pacman -S --needed go
sudo bash install.sh
```

`install.sh` builds `/usr/local/bin/ak500d` (or installs `ak500d.py` if `go` is not present), installs `/etc/udev/rules.d/99-deepcool-ak500.rules`, and enables `ak500d.service`.

### Manual Usage (Linux)

```bash
systemctl status ak500d.service
sudo systemctl stop ak500d.service

sudo /usr/local/bin/ak500d -interval 1s
sudo /usr/local/bin/ak500d -off
```

## Windows Usage

Close the official DeepCool application from the system tray before running.

```powershell
# Turn off display
python .\ak500d.py --off

# Send fixed test values (Temp, Usage %, Watts, MHz) for 5 seconds
python .\ak500d.py --test 77 88 120 5200

# Continuous loop (Ctrl+C turns off the display and exits)
python .\ak500d.py
```

## USB HID Protocol (`3633:0011`)

20-byte frame:

| Bytes | Type | Description |
|-------|------|-------------|
| `0` | `0x10` | Report ID |
| `1..7` | `68 01 03 0d 01 02 08` | Header (`0x02` AK400 Pro, `0x03` AK500 Pro, `0x04` AK620 Pro) |
| `8..9` | `uint16 BE` | CPU Power (W) |
| `10` | `uint8` | Unit (`0x00` Celsius, `0x01` Fahrenheit) |
| `11..14` | `float32 BE` | CPU Temperature (IEEE-754) |
| `15` | `uint8` | CPU Usage (`0..100`) |
| `16..17` | `uint16 BE` | CPU Frequency (MHz) |
| `18` | `uint8` | Checksum (`sum(bytes[1..17]) & 0xFF`) |
| `19` | `0x16` | Frame terminator |

Display off frame:

```text
10 68 01 04 0d 01 00 05 00 00 00 00 00 00 00 00 00 00 80 16
```
