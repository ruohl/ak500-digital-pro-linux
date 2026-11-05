# DeepCool AK500 Digital Pro Display Daemon (`ak500d`)

Reemplazo ligero y sin dependencias externas para controlar la pantalla digital del cooler **DeepCool AK500 Digital Pro** (`VID 0x3633`, `PID 0x0011`) en **Linux (CachyOS / Arch)** y **Windows**, sin necesidad del software oficial de DeepCool (Electron).

Incluye dos implementaciones:
- **Go (`main.go`)**: Demonio nativo estático (`CGO_ENABLED=0`), **0 asignaciones de memoria en el ciclo principal (0 allocs/op)**, ~2 MB de RAM y 0.00% de uso de CPU. Ideal para correr 24/7 con `systemd` en Linux CachyOS.
- **Python (`ak500d.py`)**: Script 100% librería estándar (cero `pip install`) compatible tanto con Linux (`/dev/hidraw*`) como con Windows (Win32 `hid.dll` / `setupapi.dll`).

---

## Instalación en Linux (CachyOS / Arch Linux)

1. Asegurate de tener `go` instalado (opcional pero recomendado para compilar el binario nativo):
   ```bash
   sudo pacman -S --needed go
   ```
2. Cloná el repositorio e instalá el servicio `systemd` y la regla `udev`:
   ```bash
   git clone <URL_DE_TU_REPO_PRIVADO>
   cd AK500DgPro
   sudo bash install.sh
   ```

Qué hace `install.sh`:
- Si encuentra `go`, compila el binario estático optimizado en `/usr/local/bin/ak500d` (`CGO_ENABLED=0 go build -trimpath -ldflags="-s -w"`). Si no, instala `ak500d.py`.
- Instala la regla udev `/etc/udev/rules.d/99-deepcool-ak500.rules` para el dispositivo `3633:0011`.
- Instala y activa el servicio `/etc/systemd/system/ak500d.service` (arranca automáticamente con el sistema y apaga la pantalla del cooler al apagar o detener el servicio).

### Comandos útiles en Linux
```bash
# Ver estado del servicio
systemctl status ak500d.service

# Detener el servicio (apaga automáticamente la pantalla del cooler)
sudo systemctl stop ak500d.service

# Ejecutar manualmente (binario Go o script Python)
sudo /usr/local/bin/ak500d -interval 1s
sudo /usr/local/bin/ak500d -off
```

---

## Prueba y uso en Windows

Podés probar el funcionamiento ahora mismo en Windows sin desinstalar nada:

1. **Cerrá la aplicación de DeepCool** desde el ícono de la bandeja del sistema (abajo a la derecha -> *Exit*), para que deje de enviar tramas cada 1 segundo.
2. Abrí PowerShell en la carpeta del proyecto (`D:\respos\AK500DgPro`) y probá:

```powershell
# 1. Probar apagando la pantalla del cooler:
python .\ak500d.py --off

# 2. Enviar valores fijos de prueba (77°C, 88% uso, 120W, 5200 MHz) durante 5 segundos:
python .\ak500d.py --test 77 88 120 5200

# 3. Correr en bucle continuo (Ctrl+C para detener y apagar la pantalla):
python .\ak500d.py

# 4. Ejecutar test de verificación del protocolo:
python .\test_ak500d.py
```

---

## Especificación del Protocolo USB HID (`3633:0011`)

Ingeniería inversa realizada sobre `resources/app.asar` (`out/main/index.jsc` -> `ak500ProUsbService`).

- **Vendor ID**: `0x3633` (DeepCool)
- **Product ID**: `0x0011` (AK500 Digital Pro)
- **Interfaz**: USB HID (`hidraw` en Linux, `HidD` / `WriteFile` de 64 bytes en Windows)

### Trama de actualización de sensores (20 bytes)

| Byte(s) | Valor / Tipo | Descripción |
|---------|--------------|-------------|
| `0` | `0x10` | HID Report ID (`16`) |
| `1` | `0x68` | Header mágico (`104`) |
| `2` | `0x01` | Grupo de comando |
| `3` | `0x03` | Modelo (`0x02` = AK400 Pro, `0x03` = AK500 Pro, `0x04` = AK620 Pro) |
| `4` | `0x0d` | Longitud del payload (`13` bytes, índices `5..17`) |
| `5` | `0x01` | Categoría |
| `6` | `0x02` | Comando (`0x02` = mostrar datos, `0x00` = apagar pantalla) |
| `7` | `0x08` | Modo (`0x08` activo, `0x05` reposo) |
| `8..9` | `uint16 BE` | Potencia de CPU en Watts (ej. `65` -> `00 41`) |
| `10` | `uint8` | Unidad de temperatura (`0x00` = Celsius, `0x01` = Fahrenheit) |
| `11..14` | `float32 BE` | Temperatura de CPU en IEEE-754 Big-Endian (ej. `45.6` -> `42 36 66 66`) |
| `15` | `uint8` | Uso de CPU en porcentaje `0..100` (ej. `35` -> `23`) |
| `16..17` | `uint16 BE` | Frecuencia de CPU en MHz (ej. `4850` MHz / `4.85 GHz` -> `12 f2`) |
| `18` | `uint8` | Checksum: `sum(bytes[1..17]) & 0xFF` |
| `19` | `0x16` | Byte de cierre (`22`) |

### Trama para apagar la pantalla (`displayClose`)
```text
10 68 01 04 0d 01 00 05 00 00 00 00 00 00 00 00 00 00 80 16
```
