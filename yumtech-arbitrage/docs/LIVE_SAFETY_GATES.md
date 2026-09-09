# Canlı işlem güvenlik kapıları

Canlı işlem yalnızca tüm kapılar otomatik olarak doğrulandığında açılabilir. Bir
UI anahtarı veya ortam değişkeni bu kontrolleri atlayamaz.

## Engelleyici: BTCTürk market BUY miktarı

BTCTürk market alış emrindeki `quantity` alanı TRY (quote) tutarıdır. Hummingbot
strateji ve kurtarma hesapları ise coin (base) miktarı üretir. Aşağıdaki zincir
tamamlanıp test edilene kadar canlı mod kilitli kalır:

- hedef coin miktarını güncel satış defterinden TRY tutarına dönüştür;
- ücret ve kayma güvenlik payını ekle;
- kullanılabilir TRY, minimum emir, hassasiyet ve azami kurtarma zararı
  kontrollerini uygula;
- BTCTürk'e yalnızca doğrulanmış TRY `quantity` değerini gönder;
- gerçekleşen işlemlerden edinilen gerçek coin miktarını ve ücreti mutabık et;
- kalan tek-bacak riskini yeniden hesapla ve limit içindeyse kontrollü kurtar;
- tüm hesapları ve ham borsa kimliklerini kalıcı işlem günlüğüne yaz.

Market satışta `quantity` coin (base) miktarı olarak kalır. Bu iki yön aynı
dönüştürücü yolundan körlemesine geçirilemez.

v0.3'te bu davranış `btcturk_order_semantics.py` içindeki bağımsız dönüştürücü
ve `BtcTurkExchange.place_market_recovery_order` ön kontrolüyle uygulanmıştır.
Genel Hummingbot emir yolu hâlâ yalnızca limit emir kabul eder; market BUY
ancak açıkça taze TRY bakiyesi ve fiyatıyla çağrılan kurtarma yolundan geçer.
Bu kodun bulunması tek başına canlı yeterlilik sayacını geçirmez; gerçek
hesapta dolum/mutabakat tatbikatı yapılana kadar kapı `false` kalır.

## Diğer zorunlu kapılar

- iki borsanın anahtar ve bakiye doğrulaması;
- en az 72 saat kesintisiz gözlem, 100 paper fırsatı ve 20 paper işlem;
- bağlantı kesilmesi, kısmi gerçekleşme ve yeniden başlatma tatbikatları;
- işlem, günlük zarar ve tek-bacak kurtarma limitleri;
- Hummingbot telemetri ve hata raporlamasının kapalı olduğunun doğrulanması.

BOT sayfasındaki BTCTürk ve Binance TR TRY bütçeleri iki ayrı üst sınırdır.
Paper yürütme, seçilen yönün alış ve satış bacaklarını bu sınırların altında
tutar; daha küçük genel risk limiti veya kullanılabilir bakiye varsa en küçük
limit uygulanır. Kullanıcının girdiği TRY tutarı doğrudan `quantity` olarak
gönderilmez; güncel VWAP ve piyasa hassasiyeti ile base miktarına çevrilir.
