# YUMTECH

YUMTECH; Bitcoin Core veya Bitcoin Knots ile çalışan, self-hosted solo
madencilik altyapısıdır. Stratum V1, Stratum V2, vardiff, gerçek share
difficulty, Best Share, Round Effort, blok takibi ve canlı dashboard sunar.
Bitcoin Core 30+ multiprocess kurulumlarında mining IPC'yi kullanabilir; IPC
kullanılamadığında RPC/ZMQ yoluna otomatik döner.

## Linux

Debian/Ubuntu, Raspberry Pi 5 (`arm64`) ve Intel/AMD (`amd64`) sistemlerde tek
komutla kurulum:

```bash
curl -fsSL https://raw.githubusercontent.com/yumtech-mining/yumtech-umbrel-apps/main/install-linux.sh | sudo bash
```

Ayrıntılı node yapılandırması ve yönetim komutları için
[`linux/README.md`](linux/README.md) dosyasına bakın.

## Umbrel

Topluluk mağazası adresi:

```text
https://github.com/yumtech-mining/yumtech-umbrel-apps
```

Umbrel uygulaması `yumtech/` altında bulunur. Linux kurulumu ayrı dosyaları
kullanır; mevcut Umbrel kurulumu ve verileri etkilenmez.

## CKPool Dashboard

Raspberry Pi 5 üzerinde hâlihazırda çalışan güncel native CKPool için ayrı,
salt-okunur dashboard projesi [`ckpool-dashboard/`](ckpool-dashboard/) altında
bulunur. CKPool'u veya YUMTECH pool motorunu değiştirmez.

```bash
curl -fsSL https://raw.githubusercontent.com/yumtech-mining/yumtech-umbrel-apps/main/ckpool-dashboard/install.sh | sudo bash
```
