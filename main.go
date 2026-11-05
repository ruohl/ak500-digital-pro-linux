package main

import (
	"encoding/binary"
	"flag"
	"fmt"
	"math"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

var packetClose = [20]byte{
	0x10, 0x68, 0x01, 0x04, 0x0d, 0x01, 0x00, 0x05,
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
	0x00, 0x00, 0x80, 0x16,
}

func buildPacket(dst *[20]byte, tempC float32, usagePct uint8, powerW uint16, freqMHz uint16, fahrenheit bool) {
	temp := tempC
	unit := uint8(0)
	if fahrenheit {
		unit = 1
		temp = float32(math.Round(float64(tempC)*180.0+3200.0) / 100.0)
	}
	if usagePct > 100 {
		usagePct = 100
	}

	dst[0] = 0x10
	dst[1] = 0x68
	dst[2] = 0x01
	dst[3] = 0x03
	dst[4] = 0x0d
	dst[5] = 0x01
	dst[6] = 0x02
	dst[7] = 0x08
	binary.BigEndian.PutUint16(dst[8:10], powerW)
	dst[10] = unit
	binary.BigEndian.PutUint32(dst[11:15], math.Float32bits(temp))
	dst[15] = usagePct
	binary.BigEndian.PutUint16(dst[16:18], freqMHz)

	var sum uint8
	for i := 1; i <= 17; i++ {
		sum += dst[i]
	}
	dst[18] = sum
	dst[19] = 0x16
}

func parseUint64Fast(b []byte) uint64 {
	var v uint64
	for _, c := range b {
		if c >= '0' && c <= '9' {
			v = v*10 + uint64(c-'0')
		} else if v > 0 || c == '\n' {
			break
		}
	}
	return v
}

func readSmallFile(path string, buf []byte) int {
	f, err := os.Open(path)
	if err != nil {
		return 0
	}
	n, _ := f.Read(buf)
	f.Close()
	return n
}

type linuxSensors struct {
	tempPath   string
	energyPath string
	powerPath  string
	freqPaths  []string
	prevIdle   uint64
	prevTotal  uint64
	prevEnergy uint64
	prevTime   time.Time
	buf        [512]byte
}

func newLinuxSensors() *linuxSensors {
	s := &linuxSensors{
		tempPath:  findTempSensor(),
		freqPaths: findFreqPaths(),
	}
	s.energyPath, s.powerPath = findPowerSensor()
	s.readUsage()
	s.readPowerW()
	return s
}

func findTempSensor() string {
	preferred := []string{"k10temp", "zenpower", "coretemp", "cpu_thermal"}
	hwmons, _ := filepath.Glob("/sys/class/hwmon/hwmon*")
	var fallback string
	for _, h := range hwmons {
		raw, err := os.ReadFile(filepath.Join(h, "name"))
		if err != nil {
			continue
		}
		name := strings.ToLower(strings.TrimSpace(string(raw)))
		for _, cand := range []string{"temp1_input", "temp2_input"} {
			p := filepath.Join(h, cand)
			if _, err := os.Stat(p); err == nil {
				for _, pref := range preferred {
					if strings.Contains(name, pref) {
						return p
					}
				}
				if fallback == "" {
					fallback = p
				}
			}
		}
	}
	return fallback
}

func findPowerSensor() (string, string) {
	for _, p := range []string{
		"/sys/class/powercap/intel-rapl:0/energy_uj",
		"/sys/devices/virtual/powercap/intel-rapl/intel-rapl:0/energy_uj",
	} {
		if f, err := os.Open(p); err == nil {
			f.Close()
			return p, ""
		}
	}
	hwmons, _ := filepath.Glob("/sys/class/hwmon/hwmon*")
	for _, h := range hwmons {
		for _, cand := range []string{"power1_average", "power1_input"} {
			p := filepath.Join(h, cand)
			if f, err := os.Open(p); err == nil {
				f.Close()
				return "", p
			}
		}
	}
	return "", ""
}

func findFreqPaths() []string {
	paths, _ := filepath.Glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")
	return paths
}

func (s *linuxSensors) readUsage() uint8 {
	n := readSmallFile("/proc/stat", s.buf[:])
	if n == 0 {
		return 0
	}
	b := s.buf[:n]
	if idx := strings.IndexByte(string(b), '\n'); idx > 0 {
		b = b[:idx]
	}
	i := 0
	for i < len(b) && (b[i] < '0' || b[i] > '9') {
		i++
	}
	var fields [10]uint64
	fIdx := 0
	for i < len(b) && fIdx < len(fields) {
		var val uint64
		for i < len(b) && b[i] >= '0' && b[i] <= '9' {
			val = val*10 + uint64(b[i]-'0')
			i++
		}
		fields[fIdx] = val
		fIdx++
		for i < len(b) && b[i] == ' ' {
			i++
		}
	}
	if fIdx < 4 {
		return 0
	}
	idle := fields[3] + fields[4]
	var total uint64
	for j := 0; j < fIdx; j++ {
		total += fields[j]
	}
	dIdle := idle - s.prevIdle
	dTotal := total - s.prevTotal
	s.prevIdle = idle
	s.prevTotal = total
	if dTotal == 0 || dIdle >= dTotal {
		return 0
	}
	return uint8(((dTotal - dIdle) * 100 + dTotal/2) / dTotal)
}

func (s *linuxSensors) readTempC() float32 {
	if s.tempPath == "" {
		return 0
	}
	n := readSmallFile(s.tempPath, s.buf[:])
	if n == 0 {
		return 0
	}
	milli := parseUint64Fast(s.buf[:n])
	return float32(milli) / 1000.0
}

func (s *linuxSensors) readPowerW() uint16 {
	now := time.Now()
	if s.energyPath != "" {
		n := readSmallFile(s.energyPath, s.buf[:])
		if n > 0 {
			uj := parseUint64Fast(s.buf[:n])
			if !s.prevTime.IsZero() && uj >= s.prevEnergy {
				dt := now.Sub(s.prevTime).Seconds()
				if dt > 0 {
					w := float64(uj-s.prevEnergy) / 1e6 / dt
					s.prevEnergy = uj
					s.prevTime = now
					if w > 65535 {
						return 65535
					}
					return uint16(math.Round(w))
				}
			}
			s.prevEnergy = uj
			s.prevTime = now
		}
	}
	if s.powerPath != "" {
		n := readSmallFile(s.powerPath, s.buf[:])
		if n > 0 {
			uw := parseUint64Fast(s.buf[:n])
			return uint16((uw + 500_000) / 1_000_000)
		}
	}
	return 0
}

func (s *linuxSensors) readFreqMHz() uint16 {
	var maxKHz uint64
	for _, p := range s.freqPaths {
		n := readSmallFile(p, s.buf[:])
		if n > 0 {
			khz := parseUint64Fast(s.buf[:n])
			if khz > maxKHz {
				maxKHz = khz
			}
		}
	}
	return uint16(maxKHz / 1000)
}

func findHidraw() string {
	devs, _ := filepath.Glob("/sys/class/hidraw/hidraw*")
	for _, d := range devs {
		raw, err := os.ReadFile(filepath.Join(d, "device", "uevent"))
		if err != nil {
			continue
		}
		u := strings.ToUpper(string(raw))
		if strings.Contains(u, "3633:0011") || strings.Contains(u, "00003633:00000011") {
			return filepath.Join("/dev", filepath.Base(d))
		}
	}
	return ""
}

func main() {
	devFlag := flag.String("device", "", "hidraw device path")
	interval := flag.Duration("interval", time.Second, "poll interval")
	fahrenheit := flag.Bool("fahrenheit", false, "use Fahrenheit")
	off := flag.Bool("off", false, "turn off display and exit")
	once := flag.Bool("once", false, "send one update and exit")
	flag.Parse()

	openDev := func() (*os.File, error) {
		p := *devFlag
		if p == "" {
			p = findHidraw()
		}
		if p == "" {
			return nil, fmt.Errorf("device 3633:0011 not found")
		}
		return os.OpenFile(p, os.O_WRONLY, 0)
	}

	if *off {
		f, err := openDev()
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		_, _ = f.Write(packetClose[:])
		_ = f.Close()
		return
	}

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	sensors := newLinuxSensors()
	ticker := time.NewTicker(*interval)
	defer ticker.Stop()

	var dev *os.File
	var pkt [20]byte

	for {
		if dev == nil {
			var err error
			dev, err = openDev()
			if err != nil {
				if *once {
					fmt.Fprintln(os.Stderr, err)
					os.Exit(1)
				}
				select {
				case <-sigCh:
					return
				case <-time.After(2 * time.Second):
					continue
				}
			}
		}

		buildPacket(
			&pkt,
			sensors.readTempC(),
			sensors.readUsage(),
			sensors.readPowerW(),
			sensors.readFreqMHz(),
			*fahrenheit,
		)

		if _, err := dev.Write(pkt[:]); err != nil {
			_ = dev.Close()
			dev = nil
			if *once {
				os.Exit(1)
			}
			continue
		}

		if *once {
			_ = dev.Close()
			return
		}

		select {
		case <-sigCh:
			_, _ = dev.Write(packetClose[:])
			_ = dev.Close()
			return
		case <-ticker.C:
		}
	}
}
