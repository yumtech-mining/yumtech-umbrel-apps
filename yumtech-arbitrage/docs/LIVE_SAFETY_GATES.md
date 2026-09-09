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

## Diğer zorunlu kapılar

- iki borsanın anahtar ve bakiye doğrulaması;
- en az 72 saat kesintisiz gözlem, 100 paper fırsatı ve 20 paper işlem;
- bağlantı kesilmesi, kısmi gerçekleşme ve yeniden başlatma tatbikatları;
- işlem, günlük zarar ve tek-bacak kurtarma limitleri;
- Hummingbot telemetri ve hata raporlamasının kapalı olduğunun doğrulanması.
