# YUMTECH CKPool Dashboard

Raspberry Pi 5 üzerinde çalışan **native CKPool** için YUMTECH madencilik
dashboard'u. CKPool'u değiştirmez; canlı durumu yerel Unix socket'ten,
istatistikleri CKPool'un kendi dosyalarından veya destekleniyorsa ayrıntılı API'den, share
ve blok olaylarını CKPool logundan, node telemetrisini Bitcoin JSON-RPC'den
salt okunur olarak alır.

## Özellikler

- 1/5 dakika pool hashrate'i ve aktif worker'lar
- Her share'in gerçek ulaştığı difficulty değeri ve hash'i
- Yeniden başlatmalarda silinmeyen tüm-zamanlar best share
- Round effort, accepted/rejected oranları ve 30 günlük hashrate geçmişi
- Bulunan blokların yüksekliği, hash'i, bulucu worker'ı, ödülü ve round effort'u
- Bitcoin Core ve Bitcoin Knots otomatik algılama
- Stratum V1/V2 portları ve CKPool SV2 authority public key'i
- PostgreSQL, Docker, Node.js veya Python paketi gerektirmez

## Gereksinimler

- Raspberry Pi OS 64-bit veya Debian 12/13
- Python 3.11+
- Çalışan native `ckpool.service`
- Varsayılan kurulumda `/etc/ckpool/ckpool.conf`, `/tmp/ckpool/stratifier` ve
  `/var/log/ckpool/ckpool.log`

Proje CKPool'un 4 bayt little-endian uzunluk başlıklı Unix-socket arayüzündeki
`stats` sorgusuyla havuzun çalıştığını doğrular. Bazı native sürümlerde
`send_api_yyresponse` boş olduğundan `clients`, `poolstats`, `workers` ve `uptime`
komutları yanıt vermeden bağlantıyı kapatır. **1.0.1 bu sürümleri destekler:**
`/var/log/ckpool/pool/pool.status` içindeki üç JSON satırını ve
`/var/log/ckpool/users/` dosyalarını salt okunur olarak kullanır. CKPool'un
derlenmesi, yeniden başlatılması veya ayarlarının değiştirilmesi gerekmez.

Dosya istatistikleri CKPool tarafından genellikle dakikada bir yenilenir.
180 saniyeden eski istatistikler güncel sayılmaz; eksik değerler `—` gösterilir
ve grafiğe sahte sıfır örnekleri eklenmez. Kısa süreli dosya yazımı sırasında
son tamamlanmış örnek, yalnızca güncellik süresi içinde korunur.

Dosya modunda worker listesi **son 3 dakikadaki share etkinliğine** dayanır;
anlık TCP oturum listesi değildir. Worker etiketi `AKTİF` olur. Havuz genelindeki
bağlantı sayısı canlı `stats` yanıtından alınır. Dosyalarda bulunmayan cihaz
başına bağlantı sayısı, protokol, bağlantı süresi ve atanmış diff `—` gösterilir.
User/worker dosyalarındaki `shares` alanı toplam difficulty olduğu için gönderim
adedi olarak gösterilmez; adetler yalnızca dashboardun topladığı share
kayıtlarından alınır. Ayrıntılı API destekleniyorsa bu bilgiler doğrudan okunur.

## Tek komutla kurulum veya güncelleme

```bash
curl -fsSL https://raw.githubusercontent.com/yumtech-mining/yumtech-umbrel-apps/main/ckpool-dashboard/install.sh | sudo bash
```

Sonra tarayıcıdan açın:

```text
http://RASPBERRY_PI_IP:8096
```

Kurucu CKPool systemd servisinin kullanıcı/grup bilgisini otomatik algılar,
dosyaları sürümlü biçimde `/opt/yumtech-ckpool-dashboard` altına yerleştirir ve
kalıcı geçmişi `/var/lib/yumtech-ckpool-dashboard/dashboard.db` içinde korur.
Güncelleme yalnızca dashboard servisini yeniden başlatır; mevcut ayar dosyası,
paylaşım/blok kayıtları ve CKPool/node servisleri korunur.

## Özel yollar

Standart dışı bir CKPool kurulumu için kurulmadan önce veya
`/etc/default/yumtech-ckpool-dashboard` içinde şu değerleri kullanabilirsiniz:

```bash
CKPOOL_CONFIG=/etc/ckpool/ckpool.conf
CKPOOL_STRATIFIER_SOCKET=/tmp/ckpool/stratifier
CKPOOL_LOG=/var/log/ckpool/ckpool.log
CKPOOL_USERS_DIR=/var/log/ckpool/users
CKPOOL_POOL_STATUS=/var/log/ckpool/pool/pool.status
DASHBOARD_PORT=8096
```

Değişiklikten sonra:

```bash
sudo systemctl restart yumtech-ckpool-dashboard
```

## Kontrol ve sorun giderme

```bash
sudo systemctl status yumtech-ckpool-dashboard --no-pager
sudo journalctl -u yumtech-ckpool-dashboard -n 100 --no-pager
sudo -u "$(systemctl show -p User --value ckpool.service)" test -r /var/log/ckpool/ckpool.log
sudo ss -lx | grep /tmp/ckpool/stratifier
curl -s http://127.0.0.1:8096/healthz
curl -s http://127.0.0.1:8096/api/overview
```

CKPool servisi farklı kullanıcıyla çalıştırılıyor ve log/soket o kullanıcıdan
okunamıyorsa dashboard canlı verilere erişemez. Kurucuyu yeniden çalıştırmak
servis kullanıcısını tekrar algılar.

`/healthz` çalışan dashboard sürümünü gösterir. `/api/overview` içinde
`online: true`, havuzun `stats` sorgusuna yanıt verdiğini; `metrics_available: true`,
güncel hashrate istatistiği bulunduğunu belirtir. `data_source: status-files`
bu CKPool sürümleri için normaldir. Veriler gelmiyorsa `CKPOOL_POOL_STATUS`
yolunu ve servis kullanıcısının okuma erişimini kontrol edin; RPC parolasını veya
SV2 private key'i paylaşmayın.

## Güvenlik

Dashboard varsayılan olarak LAN'da `0.0.0.0:8096` dinler. Portu doğrudan
internete yönlendirmeyin. Tailscale veya kimlik doğrulamalı TLS reverse proxy
kullanın. İsterseniz `/etc/default/yumtech-ckpool-dashboard` dosyasında
`DASHBOARD_USER` ve `DASHBOARD_PASSWORD` değerlerini birlikte tanımlayarak
Basic Auth açabilirsiniz. Bitcoin RPC parolası ve SV2 private key hiçbir API
yanıtında yayınlanmaz.

## Veri saklama

Share ve hashrate kayıtları varsayılan 30 gün tutulur; bulunan bloklar kalıcıdır.
Süre `DASHBOARD_RETENTION_DAYS` ile değiştirilebilir. CKPool'un kendi log
döndürme ayarları dashboard veritabanını silmez.

## Kaldırma

```bash
sudo bash /opt/yumtech-ckpool-dashboard/current/uninstall.sh
```

Kaldırma betiği geçmişi otomatik silmez; veri yollarını ayrıca bildirir.

## Kaynaklar ve lisans

- CKPool: https://github.com/ckolivas/ckpool
- [Dashboard attribution](ATTRIBUTION.md)
- [MIT License](LICENSE)

YUMTECH CKPool Dashboard, CKPool projesinin parçası veya resmi arayüzü değildir.
