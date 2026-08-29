#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "sudo bash uninstall.sh" >&2
  exit 1
fi

systemctl disable --now yumtech-ckpool-dashboard.service 2>/dev/null || true
rm -f /etc/systemd/system/yumtech-ckpool-dashboard.service
systemctl daemon-reload
echo "Servis kaldırıldı."
echo "Geçmişi de silmek isterseniz ayrıca şunları kaldırın:"
echo "  /var/lib/yumtech-ckpool-dashboard"
echo "  /etc/default/yumtech-ckpool-dashboard"
echo "  /opt/yumtech-ckpool-dashboard"
