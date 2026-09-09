# YUMTECH Arbitrage v0.2 — Hummingbot Tabanlı Tasarım

Durum: Tasarım ve bağlayıcı geliştirme aşaması. Canlı işlem kapalıdır.

## 1. Temel karar

Üretim tabanı olarak `hummingbot/hummingbot` deposunun sabitlenmiş `v2.16.0`
sürümü kullanılacaktır. `CoinAlpha/hummingbot` deposu yalnızca mimari fikir ve
geçmiş uygulama karşılaştırması amacıyla incelenmiştir. CoinAlpha deposu resmî
deponun fork'udur ve son kod gönderimi 7 Mayıs 2025 tarihindedir; bu nedenle
güvenlik düzeltmeleri ve yeni emir yaşam döngüsü değişiklikleri açısından
üretim tabanı değildir.

BTCTürk ve Binance TR resmî Hummingbot bağlayıcı listesinde bulunmadığı için iki
yerel CLOB bağlayıcısı geliştirilecektir:

- `btcturk`: REST kimlik doğrulama, piyasa bilgileri, emir defteri, bakiye,
  emir açma/iptal, emir ve gerçekleşme sorgulama, WebSocket piyasa akışı.
- `binance_tr`: Binance Spot uyumlu bölümleri güncel Binance bağlayıcısından
  türeten; Binance TR alan adları, semboller, oran sınırları ve kullanıcı akışı
  için ayrı doğrulama yapan bağlayıcı.

## 2. Sistem sınırları

Tek bir Hummingbot süreci bütün ortak aktif TRY paritelerini yönetecektir.
Her parite için ayrı Hummingbot konteyneri çalıştırılmayacaktır. Bu tercih,
Raspberry Pi 5'in 4 GB belleğinde kaynak tüketimini sınırlar.

Sistem dört ana bileşenden oluşur:

1. **Hummingbot çekirdeği:** emir izleme, bakiye, saat eşitleme, hız sınırı ve
   kalıcı işlem kayıtları.
2. **YUMTECH bağlayıcıları:** BTCTürk ve Binance TR API uyarlaması.
3. **SafeArbitrageController:** bütün ortak TRY paritelerini keşfeder, derinlik
   fiyatını ve gerçek net kârı hesaplar, risk koşulları uygunsa yürütücü açar.
4. **Yerel dashboard köprüsü:** Hummingbot olaylarını ve SQLite kayıtlarını
   salt-okunur şekilde API'ye aktarır.

Dashboard borsalara emir gönderemez. Başlatma, durdurma ve acil durdurma
komutları yalnızca yerel kontrol servisine gider; emir yetkisi Hummingbot
çekirdeğinde kalır.

## 3. Parite keşfi

Her iki borsadan piyasa bilgisi alınır ve şu koşulları sağlayan kesişim çıkarılır:

- kotasyon varlığı `TRY`;
- piyasa durumu işlem yapılabilir;
- spot alım ve satım destekleniyor;
- minimum tutar, miktar adımı ve fiyat adımı çözümlenebiliyor;
- iki borsadaki taban varlık aynı kanonik varlığa eşleniyor.

Liste başlangıçta ve daha sonra 30 dakikada bir yenilenir. Bir borsa piyasayı
durdurursa ilgili paritede yeni işlem açılmaz; mevcut emirler güvenli kapanış
akışına alınır.

## 4. Fırsat hesabı

Son işlem fiyatı kullanılmaz. Hedef TRY tutarı için iki emir defterinde gerçek
derinlik yürütülerek hacim ağırlıklı ortalama fiyat hesaplanır.

Net sonuç aşağıdaki kalemleri içerir:

- alış tutarı ve alış komisyonu;
- satış geliri ve satış komisyonu;
- tahmini kayma;
- gecikme/güvenlik tamponu;
- miktar ve fiyat adımlarından doğan yuvarlama farkı;
- gerçekleşebilecek ortak taban-varlık miktarı.

Bir fırsat yalnızca her iki borsada da aynı taban miktarı karşılanabiliyorsa ve
tüm kesintilerden sonra net kâr eşiğini geçiyorsa yürütülebilir sayılır.

## 5. Güvenli emir yaşam döngüsü

Standart Hummingbot ArbitrageExecutor iki piyasa emrini eşzamanlı başlatır.
YUMTECH `SafeArbitrageExecutor`, bu çekirdeği aşağıdaki ek durumlarla genişletir:

| Durum | Anlamı | Sonraki hareket |
| --- | --- | --- |
| `READY` | Fırsat ve bakiyeler doğrulandı | İki IOC limit emrini hazırla |
| `SUBMITTING` | Emirler gönderiliyor | Emir kimliklerini ayrı ayrı izle |
| `BALANCED_FILL` | İki bacak aynı miktarda gerçekleşti | Kârı kesinleştir ve kaydet |
| `PARTIAL_IMBALANCE` | Gerçekleşen miktarlar farklı | Kalan emri iptal et, farkı sınırla |
| `RECOVERY` | Tek taraflı açık pozisyon var | Önceden belirlenen zarar sınırıyla dengele |
| `FAILED_SAFE` | Kurtarma tamamlanamadı | Yeni işlemleri kilitle, operatör uyarısı üret |
| `HALTED` | Acil durdurma etkin | Yeni emir gönderme |

Piyasa emri yerine fiyat korumalı IOC limit emri tercih edilir. Böylece kabul
edilebilir en kötü fiyat önceden sınırlandırılır. İki borsadaki emirler atomik
olmadığından risk tamamen yok olmaz; maksimum tek-bacak tutarı ve maksimum
kurtarma zararı zorunlu ayarlardır.

## 6. Risk kuralları

Canlı modun açılabilmesi için bütün kontrollerin geçmesi gerekir:

- son order-book güncellemesi belirlenen yaştan küçük;
- iki borsa saati ile yerel saat farkı sınır içinde;
- API gecikmesi ve hata oranı sınır içinde;
- her iki borsada yeterli TRY ve taban varlık stoğu;
- günlük zarar ve ardışık hata limiti aşılmamış;
- aynı varlıkta başka aktif yürütücü yok;
- hesaplanan net kâr, minimum eşik ve güvenlik tamponunun üzerinde;
- `LIVE_TRADING_ARMED=true` ve ikinci yerel onay mevcut.

İlk kurulum `monitor`, sonra `paper`, ardından küçük tutarlı `shadow-live`
aşamalarıyla ilerler. Doğrudan tam canlı moda geçiş yoktur.

## 7. Telemetri ve mahremiyet

Hummingbot ayarları:

```yaml
anonymized_metrics_mode: anonymized_metrics_disabled
send_error_logs: false
```

Ek savunmalar:

- metrik toplayıcı varsayılanı kaynak yamamızda `disabled` olur;
- `api.coinalpha.com` ve `reporting.hummingbot.org` konteyner içinde yerel
  geçersiz adrese yönlendirilir;
- dashboard analitiği, hata izleme SaaS'ı veya harici CDN kullanmaz;
- API anahtarları loglara, dashboard yanıtlarına ve SQLite'a yazılmaz;
- kurulum doğrulaması sırasında dışarı giden DNS/HTTPS hedefleri denetlenir.

Borsa API bağlantıları zorunlu olarak dışarı çıkar; bunun dışındaki Hummingbot
raporlama trafiği başarısızlık kabul edilir ve canlı modu kilitler.

## 8. Dashboard bilgi modeli

Ana ekran şu bilgileri gösterir:

- bot modu, çalışma süresi, son başarılı veri zamanı ve acil durdurma;
- iki borsadaki TRY ve kripto bakiyeleri: kullanılabilir, kilitli, toplam;
- tüm ortak TRY pariteleri ve iki yönlü net fırsat sıralaması;
- alış/satış borsası, VWAP, derinlik, komisyon, tampon ve beklenen net kâr;
- her iki emir kimliği, gönderim/onay/gerçekleşme zamanları;
- beklenen kâr, gerçekleşen brüt kâr, komisyonlar, kurtarma maliyeti ve net PnL;
- günlük/haftalık/aylık sonuç, başarı oranı ve tek-bacak olay sayısı;
- borsa gecikmeleri, WebSocket yaşı, REST hata oranı ve saat sapması;
- değiştirilemez denetim günlüğü.

Dashboard masaüstünde dolu bir operasyon yüzeyi, telefonda ise özet kartlar ve
alt gezinme çubuğu kullanır. Sağ sütun boş dekoratif kartlardan oluşmaz; işlem
koruması, borsa bakiyeleri, bağlantı gecikmeleri ve son hata bilgileri gösterir.

## 8.1 Kullanıcı ve anahtar ayrımı

Uygulama birden fazla yerel kullanıcı hesabı destekler. Her kullanıcı için:

- ayrı parola özeti ve oturum;
- ayrı BTCTürk ve Binance TR API anahtar kasası;
- ayrı test portföyü, ayarlar, işlemler ve kâr/zarar kayıtları;
- ayrı günlük zarar ve işlem büyüklüğü limitleri bulunur.

Anahtarlar uygulamanın veri birimindeki cihaz anahtarıyla şifrelenir. Arayüz
gizli anahtarı tekrar göstermez; yalnızca maskelenmiş anahtar kimliği ve son
bağlantı testi görünür. Anahtar testi bakiye ve işlem iznini doğrular, çekim
yetkisi istemez.

Raspberry Pi 5 4 GB hedefinde iki Hummingbot süreci eşzamanlı çalıştırılmaz.
İki kullanıcı tanımlanabilir fakat aynı anda yalnızca bir aktif canlı işlem
profili seçilebilir. Eşzamanlı iki profil için daha fazla bellekli ayrı bir
sunucu gerekir.

## 8.2 Testten canlı moda geçiş

Her yeni kullanıcı ve her yeniden kurulum `test` modunda başlar. Canlı düğmesi
aşağıdaki yeterlilik kaydı oluşmadan etkinleşmez:

1. İki API bağlantı testi başarılı.
2. En az 72 saat kesintisiz public veri gözlemi.
3. En az 100 paper fırsatı ve 20 tamamlanmış paper işlem.
4. Eski veri, bağlantı kesintisi ve tek-bacak senaryoları başarılı.
5. Günlük zarar, işlem büyüklüğü ve kurtarma limiti kullanıcı tarafından girilmiş.
6. Kullanıcı `CANLI İŞLEMİ AÇ` ifadesiyle ikinci onayı vermiş.

Canlı seçim kalıcı bir otomatik yetki değildir. Uygulama yeniden başladığında
motor güvenli şekilde durur ve kullanıcı oturumundan tekrar başlatılır.

## 9. Umbrel yerleşimi

Servisler yalnızca yerel ağda yayınlanır:

- `yumtech-hummingbot`: işlem motoru ve özel bağlayıcılar;
- `yumtech-dashboard`: FastAPI ve statik arayüz;
- kalıcı birim: Hummingbot yapılandırmaları, loglar ve SQLite verileri.

Dashboard portu `8098` olarak korunur. Hummingbot kontrol arabirimi internete
açılmaz. Tailscale erişimi kullanılacaksa yalnızca dashboard'a izin verilir.

## 10. Kabul kapıları

Canlı işleme geçmeden önce aşağıdakiler tamamlanmalıdır:

1. Her bağlayıcının birim testleri ve kaydedilmiş API yanıt testleri.
2. En az 72 saat public WebSocket/REST kesintisiz gözlem.
3. Salt-okunur anahtarlarla bakiye ve saat eşitleme testi.
4. Paper modda kısmi gerçekleşme, bağlantı kesintisi ve eski order-book testi.
5. Minimum tutarla kontrollü iki yönlü gerçek emir testi.
6. Tek-bacak kurtarma ve günlük zarar kilidi testi.
7. Ağ trafiğinde Hummingbot raporlama isteği bulunmadığının doğrulanması.

Bu kapılardan biri geçmezse canlı mod açılamaz.
