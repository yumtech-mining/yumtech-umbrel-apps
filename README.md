# YUMTECH

YUMTECH; Bitcoin Core veya Bitcoin Knots ile çalışan, self-hosted solo
madencilik altyapısıdır. Stratum V1, Stratum V2, vardiff, gerçek share
difficulty, Best Share, Round Effort, blok takibi ve canlı dashboard sunar.

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
