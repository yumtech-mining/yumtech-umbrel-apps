# YUMTECH Arbitrage

BTCTürk ve Binance TR arasında ortak aktif TRY paritelerini izleyen, Hummingbot
tabanlı ve Umbrel için paketlenen yerel arbitraj uygulaması.

## v0.4.2 gerçekçi PaperTrade önizlemesi

Bü sürüm Umbrel paketi, sayfa tabanlı ve mobil dashboard, bütün ortak TRY pariteleri için public
derinlik taraması, WebSocket öncelikli piyasa verisi, Decimal tabanlı net kâr
hesabı, çok kullanıcılı oturumlar ve AES-256-GCM şifreli yerel API anahtar kasası
içerir. Resmî ARM64 `hummingbot/hummingbot:v2.16.0` motoru PaperTrade modunda
gerçek strateji olarak çalışır: beş saniyelik eşleşme gecikmesi, order-book
derinliği, kısmi dolum, sanal bakiye ve connector ücret şeması dashboard'a
aktarılır. Canlı emir yolu hâlâ kapalıdır.

## Ürün kuralları

- Varsayılan çalışma modu her kurulum ve yeniden başlatmada `test`tir.
- Canlı moda geçiş, test yeterliliği ve açık kullanıcı onayı gerektirir.
- Kullanıcıların API anahtarları birbirinden ayrılmış biçimde cihazda şifrelenir.
- **BOT** sayfasında BTCTürk ve Binance TR anahtarları cihaza gönderilmeden şifrelenir,
  bağlantı testi yapılır ve her profil için borsa başına TRY kotası ayarlanır.
- Kullanıcı TRY bütçesi girer; paper motoru bunu güncel VWAP ile Hummingbot'un
  kullandığı base miktarına çevirir. Bütçe iki bacakta da üst sınırdır.
- Çekim yetkisine ihtiyaç yoktur; borsa tarafında bu yetki kapatılmalıdır.
- Hummingbot anonim metrikleri ve hata raporlaması kapalıdır.
- BOT sayfasında maker/taker oranları yüzde olarak ayarlanabilir; seçili oran
  fırsat hesabı, paper dolumu ve gerçekleşen PnL'de aynı şekilde kullanılır.
- Paper motoru resmi Hummingbot olaylarını yerel, idempotent JSONL köprüsüyle
  SQLite günlüğüne aktarır. Bu dosyada anahtar veya dış raporlama verisi yoktur.
- BTCTürk market BUY için TRY dönüşümü, bakiye/precision/minimum/maksimum
  preflight'i olmadan emir payload'ı üretilemez.
- API anahtarı, parola ve erişim jetonları Git deposuna yazılmaz.
- Raspberry Pi 5 4 GB kurulumunda aynı anda tek aktif işlem profili çalışır.

## Umbrel'e kurulum

Dal ana dala alınıp `0.4.2` çok-mimarili imajları oluşturulduktan sonra Umbrel'de
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

Dashboard hiçbir gerçek borsa emri göndermez. `/api/live/enable` sunucu
tarafında `423 Locked` döndürür; HTML/JavaScript değiştirilerek aşılamaz.
Hummingbot servisi `v2.16.0` ile aynı upstream motoru kullanır ve telemetri/hata
raporlaması kapalıdır. Servis varsayılan olarak boşta başlar; kullanıcı **Test
motorunu hazırla** dediğinde yalnızca `btcturk_paper_trade` ve
`binance_tr_paper_trade` connector'larını kullanan PaperTrade stratejisini
başlatır. Dashboard veya ortam değişkeni bu sürümde canlı strateji başlatamaz. Canlı yürütme ancak
BTCTürk market BUY için TRY dönüşümü, IOC emir ve tek-bacak kurtarma testleri
tamamlandıktan sonra ayrı bir sürümde açılacaktır.

## Kaynak tabanları

- Hummingbot çekirdeği: `hummingbot/hummingbot` v2.16.0
- BTCTürk API alan eşleme fikri: `atillayurtseven/BTCTurk` (MIT)

Atilla Yurtseven projesi doğrudan kopyalanmaz. Eski ve senkron istemci kodu,
güncel API belgelerine göre asenkron Hummingbot bağlayıcısı olarak yeniden
uygulanır. Lisans gereği kullanılan parçaların atfı korunacaktır.
