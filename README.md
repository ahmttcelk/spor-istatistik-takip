# Spor istatistik takip

Tablet üzerinden yönetilen futbol ve NBA alarm sistemi. Çalışma GitHub Actions üzerinde yaklaşık beş dakikada birdir; tablet açık kalmaz. Alarm tercihi boş olduğunda spor API isteği ve bildirim yapılmaz.

## Durum ve veri kaynağı

- API-Sports Football ve Basketball ücretsiz hesaplarıyla bağlantı doğrulandı, ancak güncel sezon erişimi reddedildi. Bu iki API canlı takipte kullanılmıyor; mevcut API_SPORTS_KEY Secret'ı kodda yer almıyor.
- ESPN'in anahtarsız, resmî geliştirici destek garantisi olmayan veri uçları kullanılır. Erişim, veri sürekliliği, gecikme veya her maçta her istatistik garantisi yoktur. Bir kaynak erişimi reddederse erişim engeli aşılmaya çalışılmaz.
- Süper Lig, Premier League, La Liga, Serie A, Bundesliga, Champions League fikstürlerine erişim görüldü. Canlı örnek La Liga ve Bundesliga'da; bitmiş maç örnekleri Süper Lig, Premier League, Serie A ve NBA'de doğrulandı. Bu gözlem tüm liglerin her canlı metrik desteğini garanti etmez.
- EuroLeague doğrulanamadı. Editörde kapalıdır ve takip kodu bu lig için aktif kural kabul etmez.
- Yalnızca canlı durumdaki maçtan o anda alınan takım/oyuncu verileri kullanılır. Maç öncesi sezon ortalamaları, eski maçlar, eksik istatistikler ve oynamayan oyuncular bildirim üretmez. Eksik veri sıfır yapılmaz.
- Gol, asist, şut, isabetli şut, kart/faul/kurtarış; takım korner ve topa sahip olma; NBA sayı/ribaund/asist/blok/top çalma/top kaybı/faul/üçlük seçenekleri bulunur. Kullanılabilirlik maçtaki gerçek kaynağa bağlıdır.

## Tablet ekranı

GitHub Settings > Pages > Source > GitHub Actions seçilir. Ardından Actions > Alarm Ekranini Yayinla > Run workflow ile statik alarm hazırlama ekranı yayınlanır. Anahtar/token girişi yoktur. Takım listeleri yayınlama sırasında ESPN'den alınır ve ekranla birlikte sunulur; tarayıcı erişim kısıtına takılmaz. Oyuncu kadrosu seçilen takım için doğrudan ESPN'den alınır. Yayınlama workflow'u her gün takım listesini yeniler. Kadro yüklenmezse eksik seçimle alarm kaydedilmez.

Ekranda lig, takım, oyuncu veya takım istatistiği, karşılaştırma ve eşik seç. Listeye ekle. Yedeği indir; sayfa tercihi otomatik saklamaz. Listeyi kopyala ve GitHub Settings > Secrets and variables > Actions > ALERTS_JSON kalem simgesi > Secret > Update secret alanına kaydet. Sonraki kontrolde uygulanır.

Yeni alarm eklerken önce önceki yedek JSON dosyasını yükle. Aksi durumda yalnızca yeni listedeki alarmlar kalır. Bir alarmı kapatmak için ekranda Kapat'a basıp güncel listeyi yeniden Secret'a kaydet. Hepsini kapatmak için ALERTS_JSON değerini [] yap. Alarm kimliğini değiştirmeden aynı alarmı kapatıp açmak, aynı maç için yeni bildirim oluşturmaz.

## Secrets

- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- ALERTS_JSON
- API_SPORTS_KEY yalnızca ayrı kurulum kontrolünde kullanılır.

GITHUB_TOKEN çalışma sırasında GitHub tarafından otomatik sağlanır. Hiçbir Secret değeri kodda, HTML'de veya logda yazılmaz. Secret ayarını bağlantı kontrolü dışındaki kodlara kopyalama.

## Kalıcı kayıt ve tekrar bildirimi

sports-private-state dalındaki tracker-state.enc, token'dan alan ayrımıyla türetilen anahtarla Fernet üzerinden şifrelenir. Fikstür önbelleği, günlük istek bütçesi ve gönderim kayıtları bunun içindedir. Şifreli dosya herkese açık depodadır; anahtar olmadan tercih içerikleri okunamaz. Commit zamanları ve genel çalışma bilgisi açıktır. Bot token değişirse eski kayıt açılamaz ve sistem güvenli biçimde durur; dosya otomatik sıfırlanmaz. Bu dosyayı veya dalı silme.

Bildirim GitHub'a kalıcı olarak rezerve edildikten sonra Telegram'a bir kez gönderilir. Böylece aynı alarm kimliği + lig + maç için otomatik tekrar önlenir. Telegram'ın uçtan uca exactly-once garantisi yoktur: rezervasyon sonrası kesinti veya belirsiz gönderim hatası bildirimin kaçmasına yol açabilir. Belirsiz gönderimler otomatik tekrar edilmez. Başarısız kalıcı yazma durumunda hiçbir mesaj gönderilmez. Eşzamanlı çalışmalar tek concurrency grubuyla sıraya alınır; kayıt SHA çakışmasında üzerine körlemesine yazılmaz.

## Sorgu planı

Takip edilen liglerin önceki, bugünkü ve sonraki takvim günü fikstürü günde bir kez alınır ve şifreli saklanır; NBA gece geçişi kapsanır. ESPN lig fikstüründeki maçlar toplu gelir. Yalnızca seçili takımın maçında başlama saatinden 15 dakika önce başlayıp futbol için 4, NBA için 6 saat süren pencerede maç özeti istenir. Aynı maçtaki farklı alarmlar tek özet yanıtını paylaşır. Bitmiş maç sonraki kontrollerde yeniden istenmez. Günlük 450 veri isteği dahili emniyet sınırıdır; ESPN tarafından ilan edilmiş bir kota değildir. Sınıra gelince o gün başka veri isteği yapılmaz.

Bu işlem API-Sports'un 100 istek/gün kotasını tüketmez. GitHub kamuya açık depoda standart Linux runner kullanır; ücretli büyük runner seçilmez. Zamanlama dakika 2,7,12,... şeklindedir. GitHub gecikmeleri olabilir; kesin beş dakika garantisi yoktur. Public depoda uzun hareketsizlikte GitHub zamanlamayı devre dışı bırakabilir. Actions ekranındaki durum düzenli kontrol edilmeli.

## Testler ve çalıştırma

Spor Takip workflow'u bütün Python testlerini çalıştırır, ardından Secret yapılandırmasını kullanır. İlk kod push'u bildirim göndermeyen dry-run modundadır. Zamanlanmış çalışma canlı moddur; boş listede mesaj yoktur. Run workflow menüsündeki "Bildirim gondermeden dene" varsayılan olarak açıktır. Deneme modu eşiğin gerçekleştiğini genel bir metinle bildirir; tercih/değer yazdırmaz.

Testler; eksik veri, DNP, maç öncesi/sonrası, yanlış maç/oyuncu, şifreleme, bozuk kalıcı kayıt, önbellek, bütçe, iki ardışık kontrolde tek bildirim, kaydetme hatası ve belirsiz gönderim hatasında tekrar etmeme durumlarını kapsar.

Kurulum - Baglanti Kontrolu yalnızca elle çalıştırılmalı; her çalıştırmada bir Telegram kurulum mesajı gönderir ve API-Sports kotasından az sayıda istek harcar. Bu test mesajları canlı alarm sayılmaz.
