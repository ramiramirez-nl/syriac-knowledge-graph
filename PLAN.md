# Syriac Studies Bilgi Ağı — Proje Planı

> Son güncelleme: 2026-07-05
> Durum: Faz 0 + Faz 1 tamamlandı (kümeleme, benzerlik ağı, işbirliği adayları çalışıyor). Sıradaki: Faz 2 (küratörlük).

## 1. Vizyon

Syriac Studies (Süryani Çalışmaları) alanındaki yayınları ve araştırmacıları tek bir
interaktif platformda toplamak. Amaç yalnızca atıf ağı değil:

1. **İlişki keşfi** — hangi çalışma hangisiyle ilişkili (atıf, ortak yazar, ortak konu).
2. **Örüntü ve kümeleme** — alanın alt kümelerini (tematik okullar, dönemler, coğrafyalar)
   otomatik tespit etmek ve görselleştirmek.
3. **İşbirliği keşfi** — birbirinden habersiz ama kesişen konularda çalışan araştırmacıları
   eşleştirmek ("bu iki kişi benzer konuda çalışıyor ama birbirine hiç atıf yapmamış" sinyali).
4. **Topluluk platformu** — araştırmacıların e-posta ile üye olup profil açabildiği,
   kendi verilerini girebildiği/düzeltebildiği yaşayan bir sistem.

Strateji: **basitten karmaşığa.** Önce sağlam çekirdek veri + prototip; üyelik ve
topluluk özellikleri sonraki fazlarda bu çekirdeğin üzerine inşa edilir.

## 2. Doğrulanmış Bulgular (2026-07-05)

OpenAlex API (ücretsiz, anahtar gerekmez, `https://api.openalex.org`):

- Başlığında "syriac" geçen **4.538** yayın; tam metinde geçen **22.237** yayın.
  1904 tarihli eserler bile indekste (örn. Nöldeke, *Compendious Syriac Grammar*, W1481040678).
- Her yayın kaydında `referenced_works` alanı var → **atıf ağı hazır geliyor**,
  elle kaynakça işlemeye gerek yok.
- Her yazarın kalıcı OpenAlex Author ID'si var → isim varyantları ("S.P. Brock" /
  "Sebastian Brock") büyük ölçüde otomatik birleşir.
- Hazır "Syriac Studies" topic/concept etiketi **yok** → alan sınırını kendimiz çizeceğiz:
  arama terimi listesi + elle küratörlük.

### Bilinen riskler

| Risk | Etki | Önlem |
|------|------|-------|
| OpenAlex'te kitap/kitap bölümü kapsaması zayıf | Önemli monografiler eksik kalabilir | Elle ekleme mekanizması baştan tasarlanır (Faz 2) |
| Batı dışı dillerdeki yayınlar (Arapça, Süryanice, Türkçe) eksik | Alanın bir kısmı görünmez | Topluluk katkısı ile tamamlama (Faz 3) |
| Yanlış pozitifler (alakasız tıp/dilbilim makaleleri) | Ağ kirlenir | Küratörlük adımı + dışlama listesi |
| Yazar disambiguation hataları | Aynı kişi iki düğüm olur | OpenAlex ID temel alınır; elle birleştirme aracı |

## 3. Fazlar

### Faz 0 — Çekirdek Veri + Prototip  ✅ TAMAMLANDI (2026-07-05)

Hedef: Elle veri girmeden, gerçek veriyle çalışan interaktif graf demosu.

- [x] Python ETL script'i (`uv` ile): `scripts/fetch_openalex.py` — OpenAlex'ten
      `config/terms.yaml` içindeki 17 terimle yayın + yazar + atıf verisi çekiyor →
      SQLite (`data/syriac.db`). Sonuç: **5.733 yayın, 2.671 yazar, 1.753 atıf kenarı**
      (kenarlar yalnızca her iki ucu da korpus içinde olan "iç" atıflar).
- [x] Veri modeli kuruldu: `works`, `authors`, `authorship` (N-N), `citations`
      (work→work). Her kayıtta `source` (openalex/manual) ve `status` (auto/curated)
      alanları var — Faz 2/3'teki elle besleme bu şemaya doğrudan oturur.
- [x] `scripts/export_json.py`: SQLite'ı `site/data.json`'a aktarıyor; layout'u
      networkx `spring_layout` ile önceden hesaplıyor (client-side layout kütüphanesi
      gerekmiyor). Bağlantısız (atıfsız) düğümler ayrı ele alınıp çekirdek ağın
      etrafına halka şeklinde yerleştiriliyor — yoksa ~4.000 izole düğüm koordinat
      uzayını devasa büyütüp bağlantılı ağı ekranda görünmez hale getiriyordu.
- [x] Statik prototip site (`site/index.html`, İngilizce arayüz): Sigma.js (CDN, UMD,
      derleme aracı yok) ile graf; düğüme tıkla → detay paneli (başlık, yıl, dergi,
      yazarlar, "cites"/"cited by" listeleri); yazar adına tıkla → o yazarın korpustaki
      tüm diğer eserleri listelenir (istenen "profile sayfası" davranışının çekirdeği);
      arama kutusu (başlık + yazar adında canlı filtre); "show works with no citation
      link" anahtarı; yıl ondalığına göre renk skalası + legend.
- [x] Yerelde `preview` sunucusuyla test edildi: düğüm tıklama, yazar gezinme, atıf
      listelerinden düğümler arası gezinme, arama, izole düğüm anahtarı — hepsi
      doğrulandı.

Teknoloji: Python (uv, requests, networkx, sqlite3) + saf HTML/JS + Sigma.js UMD.
Backend yok, derleme adımı yok, sunucu maliyeti yok.

**Dosyalar:** `config/terms.yaml`, `scripts/fetch_openalex.py`, `scripts/export_json.py`,
`data/syriac.db`, `site/index.html`, `site/data.json`, `.claude/launch.json` (preview sunucusu).

**Bilinen sınırlar / sonraki iyileştirmeler:**
- Sadece 17 arama terimi kullanıldı; alan sınırı hâlâ kaba. Terim listesi genişletilebilir.
- 5.733 yayından yalnızca 1.753 atıf kenarı iç korpusta — çoğu atıf korpus dışına
  (kitaplar, OpenAlex'te olmayan eserler) gidiyor. Bu, Faz 1'deki bibliographic
  coupling / co-citation / embedding benzerliği kenarlarının neden önemli olduğunu
  doğruluyor: salt atıf ağı çok seyrek kalıyor.
- `window.__debug` içinde geliştirme/test amaçlı bir hook bırakıldı (graph, renderer,
  data erişimi) — üretime taşınırken kaldırılabilir ama zararsız.

### Faz 1 — Analiz Katmanı: Kümeleme ve Örüntüler  ✅ TAMAMLANDI (2026-07-05)

Hedef: "Alan neye benziyor?" sorusuna otomatik cevap.

- [x] Benzerlik kenarları (`scripts/compute_analysis.py`):
      - **Bibliographic coupling**: `work_references` tablosu (korpus dışı referanslar
        dahil, ör. iki makale aynı kitaba atıf yapıyorsa bağlantı kurulur) — 4.841 çift.
        Aşırı jenerik referanslar (>30 çalışma tarafından atıf alan) elendi.
      - **Co-citation**: aynı üçüncü çalışma tarafından birlikte atıf alan çift —
        7.587 çift.
      - **TF-IDF başlık benzerliği** (scikit-learn, unigram+bigram): 23.183 eşik-üstü
        çift. Not: gerçek çok dilli embedding (multilingual-e5) yerine başlık-only
        TF-IDF kullanıldı — bkz. "Bilinen sınırlar".
      - Üç sinyal ağırlıklı toplanıp (atıf 0.35, coupling 0.30, co-citation 0.20,
        tfidf 0.15), düğüm başına en güçlü 6 kenar tutuldu → **12.764 kenarlı**
        birleşik benzerlik grafiği (bağlantılı düğüm: 5.733'ün 4.589'u — atıf-only
        grafikteki 1.161'e kıyasla çok daha zengin bir yapı).
- [x] **Leiden algoritması** (python-igraph + leidenalg, RBConfigurationVertexPartition,
      resolution=0.4) ile küme çıkarımı: **96 anlamlı küme** (≥3 üye). TF-IDF merkez
      vektöründen otomatik etiketleme (en yüksek ağırlıklı terimler). Çıkan kümeler
      alan uzmanlığıyla örtüşüyor: "ephrem, ephrem syrian, syrian" (660), "peshitta,
      old testament" (569), "church of the east" (441), "syriac grammar" (414),
      "syriac orthodox" (219), "syro-malabar" (133), "incantation bowls" (117),
      "galen, syriac galen" (87), "assyrian church" (74) vb.
- [x] İşbirliği fırsatı sinyali (`collaboration_candidates` tablosu): yazar merkezi
      TF-IDF vektörleri arası kosinüs benzerliği ≥0.35, mevcut ortak yazarlık/atıf
      bağlantısı olmayan çiftler, 300 aday üretildi. Sitede "Potential Collaborations"
      paneli olarak gösteriliyor, tıklanınca iki yazarın eserleri karşılaştırmalı listelenir.
- [x] Görselleştirme (`site/index.html`): "Similarity & clusters" / "Citations only"
      görünüm anahtarı (aynı düğüm konumlarını paylaşıyor); küme rengine göre
      boyama (golden-angle HSL, 96 küme için otomatik renk); küme listesi tıklanınca
      o kümenin üyeleri vurgulanıp kameraya odaklanıyor.

Teknoloji: Python (scikit-learn TfidfVectorizer, python-igraph, leidenalg). Hâlâ
statik site, backend yok.

**Dosyalar:** `scripts/compute_analysis.py` (ana analiz), güncellenmiş
`scripts/fetch_openalex.py` (yeni `work_references` tablosu — korpus dışı referanslar
dahil tam referans listesi), güncellenmiş `scripts/export_json.py` (layout artık
benzerlik grafiğinden hesaplanıyor, cluster/similarity/collaboration verisi export
ediliyor).

**Bilinen sınırlar (ciddiye alınmalı):**
- **Başlık-only TF-IDF gerçek bir zayıflık.** Kısa başlıklar ("The Church of the East",
  2-3 kelime) neredeyse rastgele başka kısa başlıklarla %100 kozinüs benzerliği
  üretebiliyor (vektör yönü çok az terimle tam belirleniyor). ≥3 ayırt edici terim
  şartı ve bir "tavan" filtresi (>0.97 benzerlik = muhtemelen gürültü, dışlanıyor)
  ile hafifletildi ama tam çözülmedi.
- **Kitap eleştirisi kirliliği:** Aynı kitabı eleştiren iki farklı yazarın eleştiri
  başlıkları neredeyse birebir aynı oluyor (her ikisi de eleştirilen kitabın başlığını
  tekrarlıyor) — bu, gerçek bir "ortak ilgi" sinyali değil, veri örüntüsü. `work_type`
  ve başlık örüntüsü (ISBN, "pp.", "ed. by", ". By AUTHOR." vb.) ile 503 çalışma
  TF-IDF sinyalinden dışlandı, ama tüm varyasyonları yakalamıyor — **"Potential
  Collaborations" panelindeki adaylar özellikle en yüksek skorlu olanlarda hâlâ
  yanlış pozitif içerebilir; el ile doğrulama gerektiren "ipucu listesi" olarak
  sunulmalı, kesin sonuç olarak değil** (site arayüzünde bu uyarı zaten var).
- **OpenAlex'te mükerrer kayıt bulundu:** Aynı makale iki farklı work ID ile
  indekslenmiş ve farklı yazar adlarına atanmış örnek doğrulandı (`W2080959781` /
  `W4255695122`, "Two Palestinian Syriac Texts..."). Tam başlık eşleşmesi olan
  çiftler işbirliği adaylarından elendi, ama yakın-ama-tam-olmayan eşleşmeler
  (ör. "...Volume I" / "..." kesilmiş başlık) hâlâ sızabiliyor. Genel mükerrer-kayıt
  temizliği Faz 2'nin küratörlük kapsamına alındı.
- **Küme-layout uyumu kusurlu:** Bir kümenin üyeleri grafikte her zaman mekânsal
  olarak bitişik durmuyor (spring_layout tüm birleşik grafiğe göre hesaplandığı
  için, büyük kümelerin üyeleri farklı bölgelere dağılabiliyor). Kümeyi tıklayınca
  vurgulama doğru çalışıyor, sadece görsel yerleşim mükemmel değil.
- Üstteki tüm sınırlar, gerçek çok dilli semantik embedding (örn. multilingual-e5)
  ve/veya özet metni (abstract) kullanımıyla önemli ölçüde iyileşecek — bu, Faz 1'in
  doğal bir sonraki iyileştirme adımı (bkz. bölüm 5).

### Faz 2 — Küratörlük ve Elle Besleme  ← SIRADAKİ ADIM

Hedef: Eksikleri kapatma altyapısı; veri kalitesi.

- [ ] Basit yönetim arayüzü: kayıt ekle/düzelt/sil, yazar birleştir, yanlış pozitif işaretle.
- [ ] İçe aktarma: BibTeX / RIS / Zotero export → veri modeline dönüştürme.
- [ ] Otomatik güncelleme: OpenAlex'ten periyodik artımlı çekim (yeni yayınlar).
- [ ] Bu noktada backend gerekir: **FastAPI + SQLite** (ölçek büyürse Postgres'e geçiş).

### Faz 3 — Topluluk Platformu

Hedef: Yaşayan sistem; araştırmacılar kendi verilerini yönetir.

- [ ] Üyelik: e-posta ile kayıt (magic link veya şifre + doğrulama).
- [ ] Profil sayfaları: araştırmacı kendi OpenAlex/ORCID kaydını sahiplenir ("claim"),
      biyografi, ilgi alanları, yayın listesi düzenleme.
- [ ] Katkı akışı: üyeler yayın ekleyebilir/düzeltme önerebilir → moderasyon kuyruğu →
      onay sonrası ana veriye işlenir (Wikipedia benzeri, doğrudan yazma yok).
- [ ] Bildirimler: "senin çalışmanla kesişen yeni yayın/araştırmacı" uyarıları.
- [ ] Barındırma: küçük VPS veya ücretsiz katman (Fly.io / Railway benzeri); alan adı.

### Faz 4 — (İleride, isteğe bağlı)

- ORCID OAuth ile giriş, Zotero senkronizasyonu, İngilizce/Türkçe arayüz,
  API açma (başka araştırmacılar veriyi kullanabilsin), DOI olmayan eski eserler
  için el yazması/edisyon kayıtları.

## 4. Mimari İlkeler

1. **Veri modeli baştan geleceğe uyumlu**: `source` (openalex/manual/member),
   `status` (auto/curated/pending) alanları Faz 0'dan itibaren şemada. Prototip
   verisi çöpe gitmez, üzerine inşa edilir.
2. **Statik kaldığı sürece statik kal**: Faz 0-1'de backend yok → maliyet sıfır,
   bakım sıfır. Backend ancak yazma ihtiyacı doğunca (Faz 2) gelir.
3. **OpenAlex ID'leri birincil anahtar** olarak korunur; elle eklenen kayıtlara
   kendi öneğimizle ID üretilir (örn. `manual:0001`).
4. **Her faz tek başına yayınlanabilir ürün** — Faz 0 bile kendi başına faydalı.

## 5. Sonraki Somut Adım

Faz 2 küratörlük: (a) mükerrer kayıt tespiti/birleştirme (yaklaşık başlık eşleştirme,
Levenshtein/token-set-ratio), (b) yanlış pozitif çalışmaları (alakasız tıp/dilbilim
makaleleri) ayıklama arayüzü, (c) BibTeX/RIS/Zotero içe aktarma. Ayrıca Faz 1
kalitesini yükseltmek isteniyorsa: gerçek çok dilli embedding (multilingual-e5)
ile TF-IDF'in değiştirilmesi, kitap-eleştirisi tespitinin sağlamlaştırılması.

## 6. Kararlar Günlüğü

- 2026-07-05: Veri kaynağı = OpenAlex (kapsama testi olumlu). Crossref yedek.
- 2026-07-05: Prototip görselleştirme = Sigma.js (binlerce düğümde performanslı).
- 2026-07-05: Basitten karmaşığa fazlama; üyelik/profil Faz 3'e ertelendi.
- 2026-07-05: Model Fable 5 → Sonnet 5'e geçirildi (uygulama işi için yeterli;
  Fable 5 mimari/analiz kararları için saklanıyor).
- 2026-07-05: Faz 0 tamamlandı. Layout için client-side kütüphane yerine
  Python tarafında (networkx spring_layout) önceden hesaplanmış koordinat
  tercih edildi — daha basit, bağımlılık yok, prototip için yeterince hızlı (~11sn).
- 2026-07-05: Faz 1 tamamlandı. Semantik embedding yerine v1 için TF-IDF tercih
  edildi (hız, bağımlılık ağırlığı); test sırasında ciddi bir zayıflık ortaya
  çıktı (kısa başlıklar + kitap eleştirileri sahte %100 benzerlik üretiyor) —
  kısmen düzeltildi, kalan sınır PLAN.md'de açıkça belgelendi ve site arayüzünde
  kullanıcıya uyarı olarak gösteriliyor.
- 2026-07-05: Tema koyu → açık (light) çevrildi (kullanıcı isteği).
- 2026-07-05: Gözden geçirmede bulunan ve düzeltilen hatalar: (1) Sigma WebGL
  hsl() renk stringlerini çözemiyor, kümeli düğümler siyah basılıyordu → hex
  dönüşümü eklendi; (2) benzerlik görünümünde kümesiz düğümler onyıl rengine
  düşüyordu (iki renk dili karışıyordu) → nötr gri + legend'a açıklama satırı;
  (3) programatik görünüm geçişi (küme/aday tıklaması) legend'ı güncellemiyordu
  → tek `setViewMode` yardımcısına toplandı; (4) yazar sıralaması alfabetikti
  ('first'<'last'<'middle'), orta yazarlar sona düşüyordu → CASE ile düzeltildi;
  (5) aday görünümünden yazar görünümüne geçişte bayat panel başlığı → sıfırlanıyor.
