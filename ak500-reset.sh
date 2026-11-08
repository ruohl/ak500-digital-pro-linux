#!/usr/bin/env bash
# Reset tool for DeepCool AK500 Digital Pro (3633:0011) USB port / hub
set -euo pipefail

TARGET_VID="3633"
TARGET_PID="0011"
HUB_VID="05e3"
HUB_PID="0608"

# Self-elevate if not running as root
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        exec sudo "$0" "$@"
    else
        echo "Error: root privileges required." >&2
        exit 1
    fi
fi

is_device_present() {
    lsusb -d "${TARGET_VID}:${TARGET_PID}" >/dev/null 2>&1
}

if is_device_present && [ "${1:-}" != "--force" ]; then
    echo "AK500 (${TARGET_VID}:${TARGET_PID}) is already detected and enumerated."
    exit 0
fi

echo "AK500 display not responding. Resetting USB bus/port..."

# Step 1: Find and reset any USB hub ports stuck in 'default' state
found_stuck=0
for state_file in /sys/bus/usb/devices/*/*-port*/state; do
    [ -f "$state_file" ] || continue
    state=$(cat "$state_file" 2>/dev/null || true)
    if [ "$state" = "default" ]; then
        port_dir=$(dirname "$state_file")
        disable_file="$port_dir/disable"
        if [ -w "$disable_file" ]; then
            echo "-> Resetting stuck port: $(basename "$port_dir")"
            echo 1 > "$disable_file" 2>/dev/null || true
            sleep 0.5
            echo 0 > "$disable_file" 2>/dev/null || true
            found_stuck=1
        fi
    fi
done

if [ "$found_stuck" -eq 1 ]; then
    sleep 2
    if is_device_present; then
        echo "Success: AK500 detected after port disable/enable cycle."
        systemctl restart ak500d.service 2>/dev/null || true
        exit 0
    fi
fi

# Step 2: Rebind the parent USB hub (Genesys Logic 05e3:0608)
for hub_dir in /sys/bus/usb/devices/*; do
    [ -f "$hub_dir/idVendor" ] || continue
    [ -f "$hub_dir/idProduct" ] || continue
    v=$(cat "$hub_dir/idVendor" 2>/dev/null || true)
    p=$(cat "$hub_dir/idProduct" 2>/dev/null || true)
    if [ "$v" = "$HUB_VID" ] && [ "$p" = "$HUB_PID" ]; then
        hub_name=$(basename "$hub_dir")
        echo "-> Rebinding internal hub: $hub_name ($HUB_VID:$HUB_PID)..."
        if [ -w "/sys/bus/usb/drivers/usb/unbind" ]; then
            echo "$hub_name" > /sys/bus/usb/drivers/usb/unbind 2>/dev/null || true
            sleep 1
            echo "$hub_name" > /sys/bus/usb/drivers/usb/bind 2>/dev/null || true
            sleep 2
        fi
    fi
done

if is_device_present; then
    echo "Success: AK500 detected after hub rebind."
    systemctl restart ak500d.service 2>/dev/null || true
    exit 0
fi

# Step 3: Use usbreset ioctl if available
if command -v usbreset >/dev/null 2>&1; then
    echo "-> Issuing hardware USB reset to hub $HUB_VID:$HUB_PID..."
    usbreset "${HUB_VID}:${HUB_PID}" >/dev/null 2>&1 || true
    sleep 2
fi

if is_device_present; then
    echo "Success: AK500 detected after hardware usbreset."
    systemctl restart ak500d.service 2>/dev/null || true
    exit 0
fi

echo "Failure: AK500 did not enumerate."
echo "If the microcontroller brownout persists, shutdown and cut AC power switch for 10s to fully drain capacitors."
exit 1
