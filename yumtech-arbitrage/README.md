# YUMTECH Arbitrage

BTCTürk ve Binance TR arasında ortak aktif TRY paritelerini izleyen, Hummingbot
tabanlı ve Umbrel için paketlenen yerel arbitraj uygulaması.

## v0.3.1 mühendislik önizlemesi

Bu sürüm Umbrel paketi, mobil dashboard, bütün ortak TRY pariteleri için public
derinlik taraması, WebSocket öncelikli piyasa verisi, Decimal tabanlı net kâr
hesabı, çok kullanıcılı oturumlar ve AES-256-GCM şifreli yerel API anahtar kasası
içerir. Resmî ARM64 `hummingbot/hummingbot:v2.16.0` motoru ayrı bir servis olarak
telemetrisi kapalı, test kontrol supervisor'ı ile hazır tutulur; gerçek strateji
başlatma ve canlı emir bu sürümde kapalıdır.

## Ürün kuralları

- Varsayılan çalışma modu her kurulum ve yeniden başlatmada `test`tir.
- Canlı moda geçiş, test yeterliliği ve açık kullanıcı onayı gerektirir.
- Kullanıcıların API anahtarları birbirinden ayrılmış biçimde cihazda şifrelenir.
- Çekim yetkisine ihtiyaç yoktur; borsa tarafında bu yetki kapatılmalıdır.
- Hummingbot anonim metrikleri ve hata raporlaması kapalıdır.
- BTCTürk market BUY için TRY dönüşümü, bakiye/precision/minimum/maksimum
  preflight'i olmadan emir payload'ı üretilemez.
- API anahtarı, parola ve erişim jetonları Git deposuna yazılmaz.
- Raspberry Pi 5 4 GB kurulumunda aynı anda tek aktif işlem profili çalışır.

## Umbrel'e kurulum

Dal ana dala alınıp `0.3.0` çok-mimarili imajları oluşturulduktan sonra Umbrel'de
Community App Store kaynağı olarak şu adres eklenir:

```text
https://github.com/yumtech-mining/yumtech-umbrel-apps
```

Ardından **YUMTECH Arbitrage** kurulur ve `http://umbrel.local:8098` açılır.
İlk açılışta cihaz yöneticisi hesabı oluşturulur. API anahtarları yalnızca bu
yerel ekrandan girilir; sohbet, `.env` veya GitHub'a yazılmaz. Borsalarda çekim
yetkisi kapalı, yalnızca spot al-sat ve okuma izinli anahtar kullanılmalıdır.

## Yerel geliştirme

```bash
python -m pip install -e '.[test]'
pytest -q
uvicorn app.main:app --host 127.0.0.1 --port 8098
```

Docker ile:

```bash
docker build -t yumtech-arbitrage:dev .
docker run --rm -p 8098:8098 -v yumtech-arbitrage-data:/data yumtech-arbitrage:dev
```

## Güvenlik sınırı

Dashboard hiçbir borsa emri göndermez. `/api/live/enable` sunucu
tarafında `423 Locked` döndürür; HTML/JavaScript değiştirilerek aşılamaz.
Hummingbot servisi `v2.16.0` ile aynı upstream motoru kullanır ve telemetri/hata
raporlaması kapalıdır. Servis varsayılan olarak kontrol supervisor'ı ile test
hostu olarak çalışır; dashboard veya ortam değişkeni bu sürümde canlı strateji
başlatamaz. Canlı yürütme ancak
BTCTürk market BUY için TRY dönüşümü, IOC emir ve tek-bacak kurtarma testleri
tamamlandıktan sonra ayrı bir sürümde açılacaktır.

## Kaynak tabanları

- Hummingbot çekirdeği: `hummingbot/hummingbot` v2.16.0
- BTCTürk API alan eşleme fikri: `atillayurtseven/BTCTurk` (MIT)

Atilla Yurtseven projesi doğrudan kopyalanmaz. Eski ve senkron istemci kodu,
güncel API belgelerine göre asenkron Hummingbot bağlayıcısı olarak yeniden
uygulanır. Lisans gereği kullanılan parçaların atfı korunacaktır.
