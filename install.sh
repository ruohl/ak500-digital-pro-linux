#!/usr/bin/env bash
set -euo pipefail

if command -v go >/dev/null 2>&1; then
    echo "Building Go binary..."
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /usr/local/bin/ak500d .
else
    echo "Installing Python script..."
    install -Dm755 ak500d.py /usr/local/bin/ak500d
fi

install -Dm755 ak500-reset.sh /usr/local/bin/ak500-reset
install -Dm440 99-ak500-reset.sudoers /etc/sudoers.d/99-ak500-reset
install -Dm644 99-deepcool-ak500.rules /etc/udev/rules.d/99-deepcool-ak500.rules
install -Dm644 ak500d.service /etc/systemd/system/ak500d.service

udevadm control --reload-rules
udevadm trigger
systemctl daemon-reload
systemctl enable --now ak500d.service
systemctl status ak500d.service --no-pager
