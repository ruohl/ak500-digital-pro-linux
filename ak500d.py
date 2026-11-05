#!/usr/bin/env python3

import argparse
import glob
import os
import signal
import struct
import sys
import time

VID = 0x3633
PID = 0x0011

PACKET_CLOSE = bytes.fromhex("106801040d010005000000000000000000008016")


def build_packet(temp_c: float, usage_pct: int, power_w: int, freq_mhz: int, fahrenheit: bool = False) -> bytes:
    unit = 1 if fahrenheit else 0
    temp = round(temp_c * 1.8 + 32.0, 2) if fahrenheit else float(temp_c)
    power_clamped = max(0, min(65535, int(round(power_w))))
    usage_clamped = max(0, min(100, int(round(usage_pct))))
    freq_clamped = max(0, min(65535, int(round(freq_mhz))))

    body = struct.pack(
        ">BBBBBBBHBLBH",
        0x68,
        0x01,
        0x03,
        0x0D,
        0x01,
        0x02,
        0x08,
        power_clamped,
        unit,
        struct.unpack(">L", struct.pack(">f", temp))[0],
        usage_clamped,
        freq_clamped,
    )
    checksum = sum(body) & 0xFF
    return bytes([0x10]) + body + bytes([checksum, 0x16])


class LinuxMetrics:
    def __init__(self) -> None:
        self.prev_idle = 0
        self.prev_total = 0
        self.prev_energy_uj: int | None = None
        self.prev_energy_ts: float | None = None
        self.temp_path = self._find_temp_sensor()
        self.energy_path, self.power_path = self._find_power_sensor()
        self._read_cpu_times()
        self._sample_power()

    @staticmethod
    def _read_first_line(path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.readline().strip()

    def _find_temp_sensor(self) -> str | None:
        preferred = ("k10temp", "zenpower", "coretemp", "cpu_thermal")
        fallback = None
        for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
            name_file = os.path.join(hwmon, "name")
            if not os.path.isfile(name_file):
                continue
            try:
                name = self._read_first_line(name_file).lower()
            except OSError:
                continue
            for candidate in ("temp1_input", "temp2_input"):
                p = os.path.join(hwmon, candidate)
                if os.path.isfile(p):
                    if any(k in name for k in preferred):
                        return p
                    if fallback is None:
                        fallback = p
        return fallback

    def _find_power_sensor(self) -> tuple[str | None, str | None]:
        rapl_candidates = [
            "/sys/class/powercap/intel-rapl:0/energy_uj",
            "/sys/devices/virtual/powercap/intel-rapl/intel-rapl:0/energy_uj",
        ]
        for p in rapl_candidates:
            if os.path.isfile(p) and os.access(p, os.R_OK):
                return p, None

        for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
            for candidate in ("power1_average", "power1_input"):
                p = os.path.join(hwmon, candidate)
                if os.path.isfile(p) and os.access(p, os.R_OK):
                    return None, p
        return None, None

    def _read_cpu_times(self) -> tuple[int, int]:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            parts = [int(x) for x in f.readline().split()[1:]]
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
        total = sum(parts)
        return idle, total

    def get_usage(self) -> int:
        idle, total = self._read_cpu_times()
        d_idle = idle - self.prev_idle
        d_total = total - self.prev_total
        self.prev_idle, self.prev_total = idle, total
        if d_total <= 0:
            return 0
        return max(0, min(100, int(round((1.0 - d_idle / d_total) * 100.0))))

    def get_temp_c(self) -> float:
        if not self.temp_path:
            self.temp_path = self._find_temp_sensor()
        if not self.temp_path:
            return 0.0
        try:
            return int(self._read_first_line(self.temp_path)) / 1000.0
        except OSError:
            return 0.0

    def _sample_power(self) -> int:
        now = time.monotonic()
        if self.energy_path:
            try:
                uj = int(self._read_first_line(self.energy_path))
                if self.prev_energy_uj is not None and self.prev_energy_ts is not None:
                    dt = now - self.prev_energy_ts
                    duj = uj - self.prev_energy_uj
                    if dt > 0 and duj >= 0:
                        self.prev_energy_uj, self.prev_energy_ts = uj, now
                        return int(round((duj / 1_000_000.0) / dt))
                self.prev_energy_uj, self.prev_energy_ts = uj, now
            except OSError:
                pass
        if self.power_path:
            try:
                return int(round(int(self._read_first_line(self.power_path)) / 1_000_000.0))
            except OSError:
                pass
        return 0

    def get_freq_mhz(self) -> int:
        freqs = []
        for p in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"):
            try:
                freqs.append(int(self._read_first_line(p)) // 1000)
            except OSError:
                continue
        if freqs:
            return max(freqs)
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                for line in f:
                    if "cpu MHz" in line:
                        freqs.append(int(float(line.split(":")[1].strip())))
            return max(freqs) if freqs else 0
        except OSError:
            return 0

    def read_all(self) -> tuple[float, int, int, int]:
        return (
            self.get_temp_c(),
            self.get_usage(),
            self._sample_power(),
            self.get_freq_mhz(),
        )


class WindowsMetrics:
    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        class PROCESSOR_POWER_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("Number", wintypes.ULONG),
                ("MaxMhz", wintypes.ULONG),
                ("CurrentMhz", wintypes.ULONG),
                ("MhzLimit", wintypes.ULONG),
                ("MaxIdleState", wintypes.ULONG),
                ("CurrentIdleState", wintypes.ULONG),
            ]

        self._ctypes = ctypes
        self._FILETIME = FILETIME
        self._PPI = PROCESSOR_POWER_INFORMATION
        self._ncpu = max(1, ctypes.windll.kernel32.GetActiveProcessorCount(0xFFFF))
        self.prev_idle, self.prev_total = self._read_times()

    def _read_times(self) -> tuple[int, int]:
        idle, kern, user = self._FILETIME(), self._FILETIME(), self._FILETIME()
        self._ctypes.windll.kernel32.GetSystemTimes(
            self._ctypes.byref(idle), self._ctypes.byref(kern), self._ctypes.byref(user)
        )
        i = (idle.dwHighDateTime << 32) | idle.dwLowDateTime
        k = (kern.dwHighDateTime << 32) | kern.dwLowDateTime
        u = (user.dwHighDateTime << 32) | user.dwLowDateTime
        return i, k + u

    def read_all(self) -> tuple[float, int, int, int]:
        idle, total = self._read_times()
        d_idle = idle - self.prev_idle
        d_total = total - self.prev_total
        self.prev_idle, self.prev_total = idle, total
        usage = max(0, min(100, int(round((1.0 - d_idle / d_total) * 100.0)))) if d_total > 0 else 0

        arr = (self._PPI * self._ncpu)()
        self._ctypes.windll.powrprof.CallNtPowerInformation(
            11, None, 0, self._ctypes.byref(arr), self._ctypes.sizeof(arr)
        )
        freq_mhz = max((int(p.CurrentMhz) for p in arr), default=0)
        power_w = int(round(25 + (usage / 100.0) * 63))
        temp_c = round(38.0 + (usage / 100.0) * 35.0, 1)
        return temp_c, usage, power_w, freq_mhz


def find_linux_hidraw() -> str | None:
    target = f"{VID:04X}:{PID:04X}"
    for syspath in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        uevent = os.path.join(syspath, "device", "uevent")
        if not os.path.isfile(uevent):
            continue
        try:
            with open(uevent, "r", encoding="utf-8") as f:
                content = f.read().upper()
            if target in content or f"0000{VID:04X}:0000{PID:04X}" in content:
                return os.path.join("/dev", os.path.basename(syspath))
        except OSError:
            continue
    return None


class HidDevice:
    def __init__(self, dev_path: str | None = None) -> None:
        self.dev_path = dev_path
        self.fd: int | None = None
        self._win_handle: int | None = None

    def open(self) -> bool:
        if sys.platform.startswith("linux"):
            path = self.dev_path or find_linux_hidraw()
            if not path:
                return False
            self.fd = os.open(path, os.O_WRONLY)
            return True
        if sys.platform == "win32":
            return self._open_windows()
        return False

    def _open_windows(self) -> bool:
        import ctypes
        from ctypes import wintypes

        setupapi = ctypes.windll.setupapi
        hid = ctypes.windll.hid
        kernel32 = ctypes.windll.kernel32

        setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
        setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p
        ]
        setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
        ]
        setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
        kernel32.CreateFileW.restype = ctypes.c_void_p
        kernel32.WriteFile.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
        ]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD),
                ("Reserved", ctypes.c_void_p),
            ]

        guid = GUID()
        hid.HidD_GetHidGuid(ctypes.byref(guid))
        hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, 0x12)
        if not hdev or hdev == 0xFFFFFFFFFFFFFFFF:
            return False
        try:
            idx = 0
            did = SP_DEVICE_INTERFACE_DATA()
            did.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            target_str = f"vid_{VID:04x}&pid_{PID:04x}"
            while setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(guid), idx, ctypes.byref(did)):
                idx += 1
                req_size = wintypes.DWORD(0)
                setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(did), None, 0, ctypes.byref(req_size), None)
                buf = ctypes.create_string_buffer(req_size.value)
                ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                if setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(did), buf, req_size.value, None, None):
                    path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
                    if target_str in path.lower():
                        h = kernel32.CreateFileW(path, 0x40000000 | 0x80000000, 0x3, None, 3, 0, None)
                        if h and h != 0xFFFFFFFFFFFFFFFF:
                            self._win_handle = h
                            return True
        finally:
            setupapi.SetupDiDestroyDeviceInfoList(hdev)
        return False

    def write(self, packet: bytes) -> None:
        if self.fd is not None:
            os.write(self.fd, packet)
        elif self._win_handle is not None:
            import ctypes
            from ctypes import wintypes

            written = wintypes.DWORD(0)
            buf = packet.ljust(64, b"\x00")
            if not ctypes.windll.kernel32.WriteFile(self._win_handle, buf, len(buf), ctypes.byref(written), None):
                err = ctypes.windll.kernel32.GetLastError()
                raise OSError(f"HID write error: {err}")

    def close(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self._win_handle is not None:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._win_handle)
            self._win_handle = None


def main() -> int:
    parser = argparse.ArgumentParser(description="DeepCool AK500 Digital Pro display daemon")
    parser.add_argument("--device", help="path to /dev/hidrawX")
    parser.add_argument("--interval", type=float, default=1.0, help="poll interval in seconds")
    parser.add_argument("--fahrenheit", action="store_true", help="use Fahrenheit")
    parser.add_argument("--off", action="store_true", help="turn off display and exit")
    parser.add_argument("--once", action="store_true", help="send one update and exit")
    parser.add_argument(
        "--test",
        nargs=4,
        type=float,
        metavar=("TEMP", "USAGE", "WATTS", "MHZ"),
        help="send test values for 5 seconds",
    )
    args = parser.parse_args()

    dev = HidDevice(args.device)
    if args.off:
        if not dev.open():
            print("Device 3633:0011 not found.", file=sys.stderr)
            return 1
        try:
            dev.write(PACKET_CLOSE)
        finally:
            dev.close()
        return 0

    if args.test:
        if not dev.open():
            print("Device 3633:0011 not found.", file=sys.stderr)
            return 1
        t_c, u_pct, p_w, f_mhz = args.test
        pkt = build_packet(t_c, int(u_pct), int(p_w), int(f_mhz), fahrenheit=args.fahrenheit)
        try:
            for _ in range(10):
                dev.write(pkt)
                time.sleep(0.5)
        finally:
            dev.close()
        return 0

    running = True

    def _stop(signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    metrics = LinuxMetrics() if sys.platform.startswith("linux") else WindowsMetrics()

    while running:
        if dev.fd is None and dev._win_handle is None:
            if not dev.open():
                if args.once:
                    print("Device 3633:0011 not found.", file=sys.stderr)
                    return 1
                time.sleep(2.0)
                continue

        try:
            temp_c, usage, power_w, freq_mhz = metrics.read_all()
            pkt = build_packet(temp_c, usage, power_w, freq_mhz, fahrenheit=args.fahrenheit)
            dev.write(pkt)
        except OSError:
            dev.close()
            if args.once:
                return 1
            time.sleep(1.0)
            continue

        if args.once:
            dev.close()
            return 0
        time.sleep(args.interval)

    try:
        if dev.fd is not None or dev._win_handle is not None:
            dev.write(PACKET_CLOSE)
    except OSError:
        pass
    finally:
        dev.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
