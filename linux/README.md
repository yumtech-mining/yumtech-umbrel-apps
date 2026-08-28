# YUMTECH Linux kurulumu

YUMTECH, Debian ve Ubuntu tabanlı `amd64` veya `arm64` Linux sistemlerinde
Docker ile çalışır. Raspberry Pi 5 de `arm64` imajını kullanır.

## Tek komutla kurulum

```bash
curl -fsSL https://raw.githubusercontent.com/yumtech-mining/yumtech-umbrel-apps/main/install-linux.sh | sudo bash
```

Kurucu Bitcoin Core/Knots RPC ve ZMQ bilgilerini terminalden sorar. RPC parolası
ekranda gösterilmez. Kurulum tamamlandığında:

- Dashboard: `http://SUNUCU_IP:8095`
- Stratum V1: `stratum+tcp://SUNUCU_IP:3333`
- Stratum V2: `SUNUCU_IP:3340`
- Kalıcı veriler: `/var/lib/yumtech`
- Yapılandırma: `/opt/yumtech/.env`

## Bitcoin Core/Knots ayarı

Node aynı Linux makinesindeyse örnek `bitcoin.conf` ayarları:

```ini
server=1
rpcuser=YUMTECH_RPC_KULLANICI
rpcpassword=GUCLU_BIR_PAROLA
rpcbind=0.0.0.0
rpcallowip=172.16.0.0/12
zmqpubrawblock=tcp://0.0.0.0:28332
zmqpubhashblock=tcp://0.0.0.0:28334
```

Node yeniden başlatıldıktan sonra kurulumda varsayılan
`host.docker.internal`, RPC `8332`, rawblock `28332` ve hashblock `28334`
değerleri kullanılabilir. RPC ve ZMQ portlarını internete yönlendirmeyin.

Node başka bir makinedeyse `host.docker.internal` yerine node'un yerel IP
adresini girin ve `rpcallowip` değerini yalnızca YUMTECH sunucusunun IP'siyle
sınırlayın.

## Yönetim komutları

```bash
sudo yumtech status
sudo yumtech logs
sudo yumtech update
sudo yumtech configure
sudo yumtech uninstall
```

`update`, Compose dosyasını ve sabitlenmiş imaj tanımını günceller; mevcut
veritabanını, Best Share geçmişini ve SV2 kimlik anahtarını korur.

`configure`, RPC/ZMQ bilgilerini yeniden sorar ve önceki `.env` dosyasını
`/opt/yumtech/.env.backup` olarak yedekler.

`uninstall`, konteynerleri kaldırır ancak madencilik verilerini güvenlik için
`/var/lib/yumtech` altında bırakır.

## Güvenlik

Dashboard salt okunurdur ancak madenci ve havuz verilerini gösterir. `8095`
portunu kimlik doğrulamalı bir ters proxy veya VPN olmadan doğrudan internete
açmayın. Dış madenciler için yalnızca gereken Stratum portlarını yönlendirin.
