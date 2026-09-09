# YUMTECH Arbitrage yol haritası

Bu dosya v0.4.0 kurulumu ile gerçek canlı yürütme arasındaki adımları takip
eder. Varsayılan hedef **test/paper** modudur; canlı emir sunucu tarafında
kilitli kalır.

## Durum özeti

| Aşama | Durum | Kabul ölçütü |
| --- | --- | --- |
| 1. Güvenli temel | Tamamlandı | Yerel kullanıcı, AES-256-GCM anahtar kasası, çekim yetkisi yok |
| 2. Piyasa taraması | Tamamlandı | BTCTürk + Binance TR ortak aktif TRY pariteleri, WebSocket önceliği |
| 3. Paper yürütme | Tamamlandı | Hummingbot PaperTrade, 5 sn gecikme, canlı derinlik, kısmi dolum, sanal cüzdan, tek-bacak kurtarma, SQLite işlem/audit günlüğü |
| 4. BOT dashboard | Tamamlandı | Sayfa tabanlı mobil arayüz, iki API formu, borsa başına TRY bütçesi |
| 5. Umbrel release | Tamamlandı | PR #5 merge edildi; Actions run 15 ile GHCR amd64/arm64 0.4.0 imajları yayınlandı |
| 6. Kullanıcı testi | Bekliyor | 72 saat kesintisiz gözlem, 100 fırsat, 20 paper işlem |
| 7. Canlı yeterlilik | Kilitli | Bağlayıcı fixture'ları, failure drill'leri ve ikinci onay |

## Kurulumdan sonraki sıra

1. v0.4.0 PR #5 `main` dalına merge edildi; Actions run 15 iki imajı da
   amd64/arm64 olarak GHCR'ye başarıyla yayınladı.
2. Umbrel Community App Store kaynağını yenileyin; **YUMTECH Arbitrage 0.4.0**
   uygulamasını güncelleyin veya kurun (veri klasörünü silmeyin).
3. İlk açılışta cihaz yöneticisi hesabı, ardından gerekirse ayrı aile profili
   oluşturun. Aynı anda yalnızca bir profilin otomatik paper motoru aktif olur.
4. **BOT** sayfasında BTCTürk ve Binance TR anahtarlarını girin. Borsa tarafında
   withdrawal/çekim yetkisini kapatın; okuma + spot işlem izni yeterlidir.
5. Her iki bağlantı testini geçirdikten sonra borsa başına TRY bütçesini ve
   genel risk limitlerini girin. Bütçe, iki bacağın da üst sınırıdır.
6. **Test motorunu hazırla** ile resmi Hummingbot PaperTrade akışını başlatın;
   motorun `Çalışıyor · PaperTrade` durumuna geçtiğini doğrulayın. Fırsat,
  işlem, sanal/gerçek bakiye, komisyon, PnL ve audit sayfalarını düzenli kontrol edin.
   Bütçe veya komisyon profilini değiştirirseniz aynı düğmeye tekrar basarak
   PaperTrade sürecini yeni ayarlarla yeniden başlatın.
7. 72 saatlik gözlem sırasında bağlantı kesintisi, eski veri, kısmi dolum ve
   yeniden başlatma tatbikatlarını kaydedin. Bir kesinti gözlem sayaçlarını
   sıfırlar.

## TRY bütçesi nasıl uygulanır?

Hummingbot PaperTrade stratejisi ve ArbitrageExecutor emir büyüklüğünü base varlık miktarı ile izler.
Dashboard kullanıcının girdiği TRY limitini güncel VWAP'a böler, iki bacakta
en küçük bütçeyi seçer; PaperTrade stratejisi de aynı dönüşümü kendi taze
order-book VWAP'ı ile tekrar doğrulayarak base miktarını market kuyruğuna verir.
BTCTürk market alışında ayrıca quote-TRY payload dönüşümü ve precision /
bakiye ön kontrolü gerekir; bu gerçek emir kapısı geçilene kadar canlı mod
`false` kalır.

## Canlıya geçmeden önce zorunlu imza listesi

- [ ] İki API anahtarı bağlantı + bakiye testleri başarılı.
- [ ] 72 saat kesintisiz veri gözlemi tamamlandı.
- [ ] 100 paper fırsatı ve 20 dengeli paper işlem kaydedildi.
- [ ] BTCTürk market BUY TRY dönüşümü gerçek fixture ve küçük tutarla doğrulandı.
- [ ] Tek-bacak kurtarma, rate-limit, stale-data ve restart tatbikatları geçti.
- [ ] Telemetri/hata raporlaması kapalı ve raporlama hostları engelli.
- [ ] Günlük zarar, işlem ve kurtarma limitleri incelendi.
- [ ] Ayrı bir canlı-yürütme sürümü ve ikinci yerel onay yayınlandı.
