# Öğretim Programı Kontrol Aracı

Türkiye Yüzyılı Maarif Modeli öğretim programı PDF'lerinden tema/ünite içeriğini **metni değiştirmeden**
çıkaran, PDF'in kendi içindeki tutarlılığı kontrol eden ve müfredat sisteminden indirilen Excel ile iki yönlü
karşılaştıran Streamlit uygulaması.

- Kod: `curriculum_checker/`
- Kurallar: `claude.md` / `AGENTS.md` (aşağıda "Temel kurallar")
- Gereksinimler: `curriculum_checker/requirements.txt`
- Testler: `curriculum_checker/tests/` (örnek PDF'ler `samples/` klasöründe, repoda yoktur)

---

## İçindekiler

1. [Temel kurallar](#1-temel-kurallar)
2. [Kurulum, çalıştırma, dağıtım](#2-kurulum-çalıştırma-dağıtım)
3. [Arayüz: sekmeler ve iş akışı](#3-arayüz-sekmeler-ve-iş-akışı)
4. [PDF'den veri nasıl çıkarılıyor (ayrıntılı)](#4-pdften-veri-nasıl-çıkarılıyor-ayrıntılı)
5. [PDF iç kontrolleri ve bulgular](#5-pdf-iç-kontrolleri-ve-bulgular)
6. [Sistem Excel'i ile karşılaştırma](#6-sistem-excelii-ile-karşılaştırma)
7. [Gemini'nin işlevi](#7-gemininin-işlevi)
8. [Kullanıcı kararları (neden böyle?)](#8-kullanıcı-kararları-neden-böyle)
9. [Dosya haritası](#9-dosya-haritası)
10. [Testler ve örnek dosyalar](#10-testler-ve-örnek-dosyalar)
11. [Bilinen sınırlamalar ve yeni bir PDF'te sorun çıkarsa](#11-bilinen-sınırlamalar-ve-yeni-bir-pdfte-sorun-çıkarsa)

---

## 1. Temel kurallar

- PDF'de olmayan hiçbir metin üretilmez; PDF metni düzeltilmez, yeniden yazılmaz, çevrilmez, tamamlanmaz.
- Bölüm başlıkları PDF'de geçtiği şekilde korunur.
- Yalnızca düzenli ifadeye (regex) dayalı ayrıştırıcı yok: PDF'in **yerleşim bilgisi** (bbox, font, renk, boyut) kullanılır.
- Program bazında önek/başlık **hardcode edilmez**; her şey PDF'in kendisinden öğrenilir.
- Beklenen ve çıkarılan öğrenme çıktısı (ÖÇ) sayısı uyuşmuyorsa PASS verilmez.
- Belirsizlikte tahmin yapılmaz; **NEEDS_REVIEW** (inceleme gerekli) üretilir.
- Öncelik: çıkarım doğruluğu > doğrulama > Excel karşılaştırması > arayüz.
- Login, Docker, veritabanı, REST API eklenmez.
- Kapsam dışı: Türkçe ve İngilizce programları (yapıları farklı).

Bütün eşleştirmeler **yalnızca karşılaştırma anahtarları** üzerinde yapılır (ör. `norm_label`, `compare_key`);
ekranda, Excel'de ve raporda her zaman PDF'in **ham** metni gösterilir.

---

## 2. Kurulum, çalıştırma, dağıtım

```bash
pip install -r curriculum_checker/requirements.txt
```

```bash
python -m streamlit run curriculum_checker/app.py
```

- Komut satırından tek PDF raporu (`curriculum_checker` klasöründen): `python validators.py ../samples/müzik.pdf`
  — metin rapor ekrana, tam çıkarım JSON olarak `temp/extracted.json` dosyasına yazılır.
- **PyMuPDF sürümü sabittir: `PyMuPDF==1.23.26`.** 1.24 ve sonrası bazı fontlarda noktalı "İ" glifini "I" okuyor
  (Arnavutça s.103 "MEVSİMLER"), satır sonu tiresini U+00AD, görünmez glifleri `\x07` gibi kontrol karakterleri
  olarak veriyor; 13 test düşüyordu. 1.23.x yalnızca Python ≤ 3.12 için paketli olduğundan
  **Streamlit Cloud'da uygulama Python 3.12 ile oluşturulmalıdır** (Advanced settings; sürüm sonradan
  değiştirilemez, uygulama silinip yeniden oluşturulur). Kenar çubuğu farklı sürümde uyarı gösterir.
- Dağıtım: GitHub `FiratKiziltepe/programkontrol`, dal `main`, ana dosya `curriculum_checker/app.py`.

---

## 3. Arayüz: sekmeler ve iş akışı

| Sekme | Ne yapar |
|---|---|
| **1. PDF Analizi** | PDF yüklenir ve analiz edilir. Temalar/üniteler, bölümler, ÖÇ'ler tablo olarak gösterilir. PDF'den üretilen Excel indirilir (1. sayfa sistem Excel'iyle aynı 13 sütun). Yapı otomatik tanınamazsa **elle yapı formu** açılır; başarılı analizde de "Program yapısı … yanlışsa elle düzeltin" bölümü vardır. |
| **2. PDF Kontrolleri** | Sayı kontrolleri, bütün bulgular (önem/kontrol/birim filtresi), kod kontrolleri (tanımlanan ↔ kullanılan, kategori bazında "Kullanılmış ama tanımlı değil"), tema dışı bırakılan bölgeler. |
| **3. Gemini Doğrulama** | İsteğe bağlı. Seçilen temaların sayfa görüntüleri **tarayıcıdan** Gemini'ye gider; Gemini'nin gördüğü başlık/kod yerleşimi çıkarımla karşılaştırılır. |
| **4. Excel Karşılaştırma** | Sistem Excel'i (bir ya da **birden çok** dosya) yüklenir; **karşılaştırma kapsamı** seçilir; öğe bazında iki yönlü karşılaştırma (Aynı, Biçim farkı, PDF'de var/Excel'de yok, …). |
| **5. Rapor** | Özet ve karşılaştırma raporu (Excel). |
| **6. Tablo Karşılaştırma** | Sistem Excel'i ↔ PDF Excel'i **hücre hücre yan yana** (renkli farklar, çoklu durum filtresi, satır ayrıntı penceresi). Eksik PDF hücreleri PDF metin katmanından, isteğe bağlı Gemini ile (metin katmanında doğrulanarak) tamamlanır. İnceleme raporu (Word) ve nihai tablo (Excel). |

---

## 4. PDF'den veri nasıl çıkarılıyor (ayrıntılı)

Akış (`validators.analyze_pdf`):

```
extract_spans  →  detect_schema  →  parse_expected_tables  →  extract_units  →  kontroller  →  ExtractionResult
(pdf_extract)     (schema_detect)   (schema_detect)            (unit_extract)    (validators)
```

### 4.1 Span çıkarımı — `pdf_extract.extract_spans`

- PyMuPDF `page.get_text("dict")` ile her metin parçası (**span**) alınır: metin, bbox, font adı, boyut, renk,
  bayraklar. Her span'ın kalıcı kimliği `P{sayfa}_S{sıra}`; bütün çıkarılan metinler bu kimliklere bağlıdır
  (`TextField.source_spans`) ve metin sadakati bununla denetlenir.
- `fitz.TOOLS.set_small_glyph_heights(False)` her çıkarımda sabitlenir: `find_tables()` bu global ayarı açık
  bırakıp span yüksekliklerini (dolayısıyla dikey hizalamayı) değiştirebiliyordu; sonuçlar işlem sırasından
  bağımsız olsun diye.
- Görünmez kontrol karakterleri (`\x00-\x08`, `\x0b`, `\x0c`, `\x0e-\x1f`, `\x7f`) atılır, sayısı
  `CONTROL_CHARS_REMOVED` (INFO) ile raporlanır. Sekme ve satır sonu korunur.
- **Sayfa mobilyası** (`detect_furniture`): sayfanın üst/alt %7,5'lik bandında 3+ sayfada (ya da sayfaların
  %30'unda) tekrar eden metin (üst bilgi) ve sayfa numarasına eşit sayı; çıkarımda yok sayılır.
- Metin yardımcıları: `group_rows` span'ları (sayfa, dikey merkez ±3pt) ile görsel satırlara dizer;
  `row_text` span'lar arasında görsel boşluk varsa tek boşluk ekler; `make_field` satırları `\n` ile birleştirir.
- Anahtarlar (yalnızca eşleştirme): `norm_label` (yalnızca harf/rakam, küçük harf, ı/i farkı yok, NFC),
  `compare_key` (yumuşak tire, satır sonu tiresi, tireler ve fazla boşluk yok), `tr_lower/tr_upper`
  (Türkçe İ/I), `nfc` (ayrışık harfleri birleştirir: "C"+U+0327 → "Ç").

### 4.2 Program yapısının keşfi — `schema_detect.detect_schema`

Her program kendi yapısını anlatır; araç bunu PDF'ten öğrenir (`ProgramSchema`).

1. **Gövde rengi**: en çok karakter taşıyan renk; ona kanal başına ±40 yakın renkler de gövde sayılır
   (Fen'de #000000/#000C14 açıklamaları ve #221F1F gövde).
2. **Birim başlıkları** (`find_unit_titles`): gövde renginde olmayan ve `N. KELİME: Ad` biçimindeki satırlar.
   Anahtar kelime tek ya da birkaç sözcük olabilir (TEMA, ÜNİTE, ÖĞRENME ALANI). Başlık aynı satırda
   parçalara bölünmüş olabilir ("1. ÜNİTE: " + "DİN HİZMETLERİ …"): aynı satırdaki aynı renkli ardışık
   parçalar birleştirilerek denenir. En çok sayfada geçen anahtar kelime seçilir. `KELİME N: Ad` biçimi
   standart dışı sayılır (birim olur + `UNIT_TITLE_FORMAT` NEEDS_REVIEW).
3. **Yapı/tanıtım sayfası** (`locate_structure`) — tema sayfasının küçültülmüş örneği:
   - İçindekiler elenir: ilk birim başlığından önceki **son** "…YAPISI" ipucu alınır;
   - ipucundan sonraki ilk birim başlıklı sayfa (en fazla 10 sayfa sonra; Matematik'te başlık s.12, şema s.17);
     kabul koşulu: başlıkla aynı sayfada **ya da** hemen sonraki birim başlığı aynı metin **ya da** başlık
     belirgin küçük **ya da** sayfadaki kalın/renkli metinler diğer tema sayfalarındakilerden belirgin
     küçük (`_scaled_down_page`, %85);
   - ipucu yoksa ilk birim sayfası aynı küçültme ölçütleriyle denenir;
   - sayfa, büyük başlık ya da yeni birim başlığı görülene kadar sonraki sayfalara uzatılır.
4. **Bölüm başlığı sözlüğü** (`learn_labels`): yapı sayfasındaki gövde/başlık renginde olmayan, yapı başlığından
   küçük metinler. Harf/rakam içermeyen işaretler ("-") ve kod biçimindeki metinler ("HMU.11.1.1.") alınmaz.
   Çok satırlı başlıklar `merge_label_lines` ile birleştirilir (aynı renk, dikey yakınlık, yatay örtüşme,
   aynı font kalınlığı; "(" ile başlayan devam satırı istisna). Bileşik başlık ("Genellemeler/ İlkeler/
   Anahtar Kavramlar/ Semboller vb.") parçalarıyla (`parts`) saklanır. Tema sayfalarında hiç geçmeyen metin
   sözlükten çıkarılır (`_labels_used_in_units`).
5. **Başlık renklerinin doğrulanması** (`confirm_label_colors`): yapı sayfasındaki renk tema sayfalarında
   farklı olabilir (Kimya #0098B9 → #01B49C). Tema sayfalarında ≥2 farklı sözlük başlığıyla birebir eşleşen
   renkler başlık rengidir; onlara ±20 yakın ve sözlükle eşleşen tonlar da eklenir (Hayat Bilgisi #A04D84).
6. **ÖÇ kodu deseni** (`learn_lo_code`): yapı sayfasındaki gövde renginde örnek koddan önek ve segment tipleri
   ("MÜZ.5.1.1." → MÜZ, [n,n,n]; "ARN.5.1.D." → ARN, [n,n,a]). Yoksa tema sayfalarında satır başında en sık
   geçen biçim (`learn_lo_code_from_units`).
7. **Yapı sayfası hiç yoksa**: sözlük tema sayfalarından öğrenilir (`learn_labels_from_units`): kalın/orta,
   renkli ve birimlerin en az yarısında tekrar eden başlıklar; çok satırlı başlıklar birimin kendi başlık içi
   satır aralığına göre birleştirilir (`_adaptive_label_groups`: en sık aralık ×1,4 + 0,5pt). Rapor:
   `STRUCTURE_PAGE_NOT_FOUND` (NEEDS_REVIEW).
8. **Elle verilen bilgiler** (`SchemaOverrides`, arayüzdeki form): örnek başlık PDF'te aranır
   (`find_titles_from_example`; aynı renk + anahtar kelimedeki bütün başlıklar), örnek ÖÇ kodu desene çevrilir
   (`lo_code_from_example`), yapı sayfaları / ilk tema sayfası verilebilir. Boş alan otomatik algılanır.
   Rapor: `MANUAL_SCHEMA` (INFO).

### 4.3 Özet/süre tabloları — `schema_detect.parse_expected_tables`

- Yapı sayfasından (yoksa ilk tema sayfasından) önceki, "öğrenme çıktı" ipucu geçen sayfalarda PyMuPDF
  `find_tables()`.
- Sütun rolleri başlık hücrelerinden: ÖÇ sayısı, ders saati, sıra, ad (anahtar kelimeyi içeren en soldaki sütun).
  Başlıksız "N." hücresi ya da ad hücresindeki "N." sıra sayılır. Toplam satırı ayrılır.
- Tablo başlığı: tablonun ilk satırı tam genişlikte tek hücreyse o (Matematik); yoksa üstündeki en yakın
  başlık renkli satır bloğu (Afet: başlık ile tablo arasında açıklama cümlesi var); o da yoksa hemen üstteki satır.
- **Roller**: aynı başlıklı birden çok tablo varsa toplam ders saati en büyük olan **esas** (SUMMARY), diğerleri
  **sınırlı/alternatif** (Afet: haftada 2 saat tam, 1 saat sınırlı). Birim → ÖÇ kodu listesi veren yatay tablolar
  `LO_LIST` (Afet s.12).
- Tablo yoksa/okunamazsa analiz durmaz: `EXPECTED_TABLE_NOT_FOUND` vb. **INFO**, beklenen sayı "?".

### 4.4 Birimlere ve bölümlere ayırma — `unit_extract.extract_units`

Veri başlangıç sayfasından itibaren, mobilya dışı span'lar okuma sırasıyla (satır satır) gezilir:

- **Başlık renginde span** → yeni birim başlığı (tek parça ya da aynı satırdaki parçaların birleşimi).
  Başlığın hemen altındaki aynı boyuttaki devam satırı başlığa, farklı satır alt başlığa (subtitle) eklenir.
  Başlıktan önceki, özet tablosu başlığıyla eşleşen tema dışı başlık **bağlam** olur ("5. SINIF (A1.1)",
  "9. SINIF TEMALARI", "I. DÜZEY"); bağlam yeni bağlam gelene kadar sonraki birimlere taşınır.
- **Bölüm başlığı renginde span** → `merge_labels` ile çok satırlı başlıklar birleştirilir (sözlüğün öneki
  olduğu sürece; satır aralığı geniş başlıklar için boşluk/yazı boyu ölçütü; yazım varyantı ≤1–2 harf
  → `LABEL_TEXT_VARIANT`; bileşik başlığın parçaları → o başlık; sözlükte olmayan → `UNKNOWN_LABEL` ama ayrı
  bölüm olarak korunur).
- **Gövde metni** → son bölümün içeriği. Başlık sütununun sağ kenarının belirgin solunda başlayan gövde satırı
  **sayfa notu** sayılır ve tema dışı bırakılır.
- **Hizalama düzeltmesi** (`_pull_aligned_rows`): içerik bloğu başlığa göre dikey ortalanmışsa ilk satırlar
  başlığın biraz üstünde başlar; önceki bölümün sonundaki, yeni başlıkla aynı hizadaki ve önceki içerikten
  **paragraf boşluğuyla** ayrılan satırlar yeni başlığa taşınır (Matematik s.57 "E1.1. Merak…" yc=312,
  "EĞİLİMLER" y0=313). Normal satır aralığıyla devam eden paragraf satırı taşınmaz (Arnavutça s.218).
- **Tema dışı başlık stili** (gövde, bölüm ve birim rengi dışında, kalın/büyük) → birim kapanır; ekler, kaynakça
  gibi bölgeler `excluded_regions`'a gider.
- **Gruplar** (`_assign_groups`): içeriksiz üst başlıklar (PROGRAMLAR ARASI BİLEŞENLER, FARKLILAŞTIRMA)
  temaların çoğunluğundan öğrenilir; alt başlıklar "ÜST > alt" yolu alır. Grup başlığının altında içerik varsa
  `GROUP_HAS_CONTENT`.
- **Bölüm türleri** (`_classify_sections`): tanım bölümleri (kod listesi: Eğilimler, Değerler …), öğrenme
  çıktıları, uygulamalar, diğer. Başlığı eksik uygulama bölümü ilk kod satırından ayrılır (`APPLICATIONS_LABEL_MISSING`).
- **İçerik ayrıştırma** (`_parse_unit_content`):
  - *Tanımlar*: "KB2.8. Sorgulama, …" girdileri; iç içe tanımlar ("KB2.16. Muhakeme (KB2.16.1. …)") üst koduyla;
    satır sonu tiresi birleştirilerek; standart dışı yazımlar ("E1.1 Merak") tanımlı sayılır + `CODE_FORMAT_ANOMALY`.
  - *Öğrenme çıktıları* (`_parse_los`): kod başlığı (öğrenilen desen; segmenti eksik başlıklar gevşek desenle),
    başlık metni, süreç bileşenleri "a) b) c) ç) …" (Türk alfabesi). İşaretsiz tek bileşen font farkıyla ayrılır
    (Arnavutça DBS/SÖS/SES). **Bileşeni olmayan ÖÇ geçerlidir**, bulgu üretilmez (Hayat Bilgisi).
  - *Uygulamalar* (`_parse_applications`): ÖÇ kodu satırıyla başlayan bloklar; blokta parantez içinde kullanılan
    kodlar (`extract_used_codes`; küçük harfli önek kod değildir: "(cm3)"; noktadan sonra satır sonunda bölünmüş
    kod "KB2.\n14" birleştirilir); bozuk yazımlar ("KB2,4", "E,2.4", tek başına "SDB") ayrı listelenir.
- Başlık devamı mı alt başlık mı (`validators.merge_title_continuations`): başlık adı + alt satır süre
  tablosundaki bir satır adıyla birebir eşleşiyorsa alt satır başlığın devamıdır (Matematik "OLAYLARIN
  OLASILIĞI VE / VERİYE DAYALI ARAŞTIRMA"; Adigece "Alt Temalar: …" alt başlık kalır).

### 4.5 Metin sadakati ve kapsama

- `check_fidelity`: her çıkarılan metin, kaynak span'larının metninde (boşluklar hariç) birebir geçmeli
  (`TEXT_NOT_IN_SOURCE`, FAIL).
- `check_coverage`: veri bölgesindeki her span tam olarak bir yere atanmış olmalı (`UNASSIGNED_SPANS`,
  `DOUBLE_ASSIGNED_SPANS`).

---

## 5. PDF iç kontrolleri ve bulgular

Önem dereceleri: **INFO** (bilgi, durumu etkilemez) < **WARNING** (geçer) < **NEEDS_REVIEW** < **FAIL**.
Birim/program durumu en ağır bulguya göre: PASS / WARNING / NEEDS_REVIEW / FAIL.

| Kontrol | Başlıca bulgular |
|---|---|
| Sayılar (süre tablosu) | `LO_COUNT_MISMATCH`, `LO_TOTAL_MISMATCH`, `UNIT_COUNT_MISMATCH`, `MISSING_UNIT`, `HOURS_MISMATCH` (FAIL); tablo eşleşmezse `EXPECTED_*`, `HOURS_NOT_FOUND` (INFO); `UNIT_NAME_MISMATCH`, `TABLE_TOTAL_INCONSISTENT` (NEEDS_REVIEW). Tablo satırları önce adla, sonra sıra ile eşleşir. Toplamlar yalnızca bütün özet tabloları birimlerle eşleştiyse karşılaştırılır. |
| Sınırlı tablolar (Afet) | `LIMITED_LO_COUNT_MISMATCH`, `LIMITED_LO_NOT_FOUND`, `LIMITED_*_AMBIGUOUS`, `LO_LIST_UNPARSED` (NEEDS_REVIEW) |
| Bölümler | `MISSING_SECTION`, `DUPLICATE_SECTION`, `SECTION_ORDER`, `UNKNOWN_LABEL`, `LABEL_TEXT_VARIANT`, `ORPHAN_LABEL`, `GROUP_HAS_CONTENT` (NEEDS_REVIEW); `SECTION_LEAKAGE` (FAIL; bileşik başlığın kendi parçaları hariç); `EMPTY_SECTION` (WARNING) |
| ÖÇ kodları | `LO_CODE_IDENTITY`, `DUPLICATE_LO_CODE` (FAIL). **Numaralandırma şeması programın çoğunluğundan öğrenilir** (`learn_code_scheme`): sondan ikinci segment tema sırası mı (Matematik'te içerik alanı), son segment birim içinde mi yoksa kod grubu içinde mi artıyor. `COMPONENT_LETTER_SEQUENCE`, `LO_SKILL_ORDER` (NEEDS_REVIEW) |
| Uygulamalar | `APPLICATION_MISSING`, `APPLICATION_DUPLICATE`, `APPLICATION_UNKNOWN_CODE` (FAIL); `APPLICATION_EMPTY`, `APPLICATION_ORDER` (NEEDS_REVIEW) |
| Kod çapraz kontrolü | `USED_NOT_DECLARED` (FAIL), `DECLARED_NOT_USED` (WARNING), `USED_CODE_INCOMPLETE`, `USED_CODE_MALFORMED` (NEEDS_REVIEW). Alan becerileri kontrol dışıdır. Hiyerarşik eşleşme: D11.2 kullanımı D11 tanımını karşılar. Kod kontrol tablosunda tanımsız kodlar önek + ilk numarayla ilgili kategoriye yazılır. |
| Biçim | `CODE_FORMAT_ANOMALY` (WARNING), `DECLARATION_NAME_MISSING`, `DECLARATION_UNPARSED_CODE` (NEEDS_REVIEW) |
| Yapı | `STRUCTURE_PAGE_NOT_FOUND` (NEEDS_REVIEW), `MANUAL_SCHEMA`, `CONTROL_CHARS_REMOVED` (INFO) |

---

## 6. Sistem Excel'i ile karşılaştırma

### 6.1 Sistem Excel'inin okunması — `excel_import`

- 13 sütun (`excel_export.SYSTEM_HEADERS`). Sütun düzeyi (tema / ÖÇ / bileşen) sütun adından değil, **hangi
  satırlarda dolu olduğundan** öğrenilir. Boş tema/ÖÇ + dolu bileşen satırı önceki ÖÇ'nin devamıdır.
- Sistemin her hücreye eklediği "Sayfa(lar)/e-içerik(ler):" satırı karşılaştırmada yok sayılır.
- **Birden çok dosya** (`merge_system_excels`): sınıf sınıf indirilen dosyalar birleştirilir; hücre adresine dosya
  adı eklenir ("6.sinif.xlsx!A2").

### 6.2 Karşılaştırma kapsamı — `scope.py`, `scope_panel.py`

Sistem Excel'i çoğu zaman tek sınıfı içerir, PDF ise bütün sınıfları. PDF temaları bağlamlarına (sınıf/düzey)
göre gruplanır; Excel temaları PDF temalarıyla **ÖÇ kodlarının çoğunluğu** üzerinden eşleşir (sınıf yazısına
bakılmaz). Varsayılan kapsam: Excel'de teması bulunan grupların bütün temaları. Kullanıcı grupları ve tek tek
temaları değiştirebilir; seçim 4. ve 6. sekmede ortaktır. Kapsam dışı temalar **fark sayılmaz**
(4. sekmede `KAPSAM_DIŞI`, 6. sekmede ve raporda tek satırlık liste). Kapsama alınıp Excel'de olmayan tema
gerçek fark olarak kalır. Tüm sınıflar tek Excel'de ise sonuç kapsamsızla aynıdır.

### 6.3 Öğe bazında karşılaştırma (4. sekme) — `compare.Comparer`

Temalar ÖÇ kodu çoğunluğuyla; ÖÇ'ler kod kimliğiyle (başlığı aynı kodu farklı ise `KOD_FARKLI`); bileşenler
sırayla eşleşir. Uygulamalar hücresi ÖÇ kod satırlarından bloklara bölünür. Tanım/kod sütunları **kod + ad**
olarak, kısa öğe listeleri (Disiplinler Arası İlişkiler) öğe kümesi olarak karşılaştırılır. ÖÇ düzeyi kod
sütunları = o ÖÇ'nün uygulama bloğunda kullanılan ve ilgili bölümde tanımlı kodlar.

Durumlar: `AYNI` · `SADECE_BİÇİM_FARKI` (boşluk, satır sonu tiresi, büyük/küçük harf) · `PDF_DE_VAR_EXCELDE_YOK`
· `EXCELDE_VAR_PDF_DE_YOK` · `YANLIŞ_BÖLÜM` · `KOD_FARKLI` · `METİN_FARKLI` (harf/noktalama farkı dahil) ·
`SAYI_FARKLI` · `İNCELEME_GEREKLİ` · `KAPSAM_DIŞI`.

Kod adlarında **yalnızca sondaki "Becerisi" eki** yok sayılır (sistem: "KB2.2. Gözlemleme Becerisi", PDF:
"KB2.2. Gözlemleme"); not düşülür. Başka hiçbir ad farkı yok sayılmaz. PDF'de adı olmayan alt kodlarda
(D3.1 kullanılmış, yalnızca D3 tanımlı) ad karşılaştırılamaz, not düşülür.

### 6.4 Hücre bazında yan yana tablo (6. sekme) — `grid_compare`, `grid_table_component`, `grid_tab`

- Satır = süreç bileşeni; her alan için **Sistem | PDF** yan yana. Hücre durumları: `AYNI`, `BİÇİM`, `FARKLI`,
  `YALNIZCA_SİSTEM`, `YALNIZCA_PDF`, `BOŞ`. Kod listeleri kod kümesi + ad, öğe listeleri öğe kümesi olarak.
- **Deterministik tamamlama**: PDF tarafı boş, sistem dolu hücrede sistem metni, hücrenin sayfalarının (+ bir
  sonraki sayfa; bilinmiyorsa temanın bütün sayfaları) **PDF metin katmanında** aranır (boşluk/tire/büyük-küçük
  harf farkı hariç, en az 12 karakter). Bulunursa PDF'deki **ham** metin alınır (kaynak: "PDF metin katmanı", **PDF✓**).
- Tablo: sabit sol sütunlar, yatay kaydırma, renkli farklar, **çoklu seçimli durum filtresi** (sayılı çipler;
  Tamamlananlar / Gemini doğrulanamadı; alan filtresi), arama, sütun gizleme, satıra tıklayınca tüm alanlar ve
  kelime düzeyinde fark vurgusu (←/→ ile gezinme).
- İnceleme raporu (`review_report`): Python ile deterministik Markdown → **Word**; ekte deterministik fark
  tablosu her zaman bulunur. Nihai tablo Excel'i (her alan için Sistem | PDF | Durum).

---

## 7. Gemini'nin işlevi

Gemini **yalnızca yerleşim/konum yardımcısıdır**; ürettiği metin hiçbir zaman çıkarıma, PDF Excel'ine veya
karşılaştırma değerlerine doğrudan girmez. Bütün çağrılar **kullanıcının tarayıcısından** yapılır
(`st.components.v2`): kullanıcı kendi API anahtarını girer; anahtar yalnızca o tarayıcı sekmesinin
`sessionStorage`'ında durur (sekme kapanınca silinir), sunucuya gönderilmez ve kaydedilmez. Sunucuya yalnızca
Gemini'nin yanıtları döner. Varsayılan model `gemini-3.5-flash-lite` (arayüzde değiştirilebilir). Hız sınırında
(429/503) birkaç kez beklenip yeniden denenir. API hataları analizi durdurmaz (`GEMINI_ERROR`, INFO).

| Nerede | Ne gönderilir | Gemini'den istenen | Nasıl kullanılır |
|---|---|---|---|
| 3. sekme — yerleşim doğrulaması (`gemini_verify`, `gemini_component`) | Seçilen temaların sayfa görüntüleri (JPEG) | Sayfadaki tema başlıkları, bölüm başlıkları, ÖÇ kodları, uygulama bloğu kodları (JSON şeması) | Çıkarımla karşılaştırılır: çıkarımda var Gemini görmedi → `GEMINI_NOT_CONFIRMED`; Gemini gördü çıkarımda yok → `GEMINI_NOT_EXTRACTED` (NEEDS_REVIEW). Başlıklarda küçük okuma farkına tolerans, kodlar birebir. |
| 6. sekme — eksik/farklı hücrelerin kontrolü (`grid_compare.gemini_tasks/apply_gemini`, `gemini_tasks_component`) | Farklı ya da PDF'de eksik hücrelerin sayfa görüntüleri + alan tarifleri (sistem değeri **gönderilmez**) | Alanın sayfada yazan metni, birebir | Gemini'nin metni sayfaların **metin katmanında birebir** bulunursa PDF'deki **ham** metin tabloya girer (**Gemini✓**); bulunamazsa girmez, "Gemini önerisi — doğrulanamadı" (**Gemini?**) olarak incelemeye düşer. |
| 6. sekme — "Gemini ile raporlaştır" (`review_report.gemini_report_prompt`) | Yalnızca Python'un deterministik rapor metni | Raporun inceleme uzmanları için daha okunaklı yazılması; yeni olgu/sayı/kod eklememe | Ekranda ve Word'de gösterilir; Word'e her zaman deterministik fark tablosu eklenir ve "Gemini ile düzenlenmiştir" notu düşülür. |

---

## 8. Kullanıcı kararları (neden böyle?)

- Belirsiz durumlar kullanıcıya sorularak karara bağlandı; varsayım yapılmaz.
- Repertuvar listesi / EK sayfaları tema dışı; iç içe başlıklar "ÜST > alt" yolu.
- Kod çapraz kontrolü iki yönlü: tanımlı-kullanılmamış WARNING, kullanılmış-tanımsız FAIL; kullanılan kodlar
  yalnızca "Öğrenme-Öğretme Uygulamaları"ndan; hiyerarşik eşleşme.
- Alan becerileri kod çapraz kontrolü dışında (sistem Excel'iyle karşılaştırmada kullanılır).
- Standart dışı tanım yazımları tanımlı sayılır + WARNING; bozuk kullanılan kod NEEDS_REVIEW; önek yazım hatası FAIL.
- Standart dışı birim başlığı ("TEMA 3: SEYAHAT") birim sayılır + NEEDS_REVIEW.
- Başlık yazım varyantı en yakın tek başlığa eşlenir (kısa başlıklarda en fazla 1 harf: "Deneyler" ≠ "Değerler").
- Yapı sayfasında olmayan başlık ("ÖĞRENCİ PROFİLİ", "Deneyler") ayrı bölüm + NEEDS_REVIEW.
- Süreç bileşeni olmayan ÖÇ hata değildir, uyarı da değildir.
- Süre/ders saati tablosu yoksa ya da eşleşmezse analiz durmaz (INFO); tablo varsa ve sayılar tutmuyorsa hata.
- Birden çok süre tablosu (Afet): tam (en çok saatli) tablo esas; sınırlı tablo ÖÇ listesiyle kontrol edilir.
- Karşılaştırma: "Sayfa(lar)/e-içerik(ler):" yok sayılır; kod sütunları kod + ad; yalnızca sondaki "Becerisi" eki yok sayılır.
- Kapsam: çoklu Excel + ÖÇ koduyla otomatik kapsam + kullanıcı düzeltmesi; PDF analizi ve 1. sekme Excel'i tüm PDF'i kapsar.
- Gemini: yalnızca konum/yerleşim yardımcısı, tarayıcıda, anahtar sunucuya gitmez; PDF'e girecek metin ancak PDF metin katmanında doğrulanırsa (ham PDF metni olarak).

---

## 9. Dosya haritası (`curriculum_checker/`)

| Dosya | Görev |
|---|---|
| `app.py` | Streamlit arayüzü (6 sekme) |
| `models.py` | Pydantic veri modelleri (Span, TextField, Code, Unit, Section, LearningOutcome, ProgramSchema, SchemaOverrides, Finding, …) |
| `pdf_extract.py` | Span çıkarımı, mobilya, satır dizme, metin anahtarları, kod ayrıştırma ve desenleri |
| `schema_detect.py` | Program yapısının keşfi, elle yapı bilgileri, özet/süre tablolarının okunması |
| `unit_extract.py` | Birimlere/bölümlere ayırma, tanımlar, ÖÇ'ler, uygulamalar, kullanılan kodlar |
| `validators.py` | Bütün PDF iç kontrolleri, `analyze_pdf`, komut satırı raporu |
| `manual_schema.py` | Elle yapı formu |
| `excel_export.py` | PDF'den Excel (sistem biçimi + tüm bölümler), arayüz tabloları, renkler |
| `excel_import.py` | Sistem Excel'inin okunması ve birden çok dosyanın birleştirilmesi |
| `compare.py` | Öğe bazında karşılaştırma (4. sekme), "Becerisi" kuralı |
| `scope.py`, `scope_panel.py` | Karşılaştırma kapsamı ve paneli, çoklu Excel yükleme |
| `grid_compare.py` | Hücre bazında yan yana karşılaştırma, metin katmanından ve Gemini ile doğrulanmış tamamlama |
| `grid_table_component.py` | Yan yana karşılaştırma tablosu (HTML/JS bileşen) |
| `grid_tab.py` | 6. sekme |
| `review_report.py` | İnceleme raporu (Markdown/Word), nihai tablo Excel'i, Gemini rapor istemi |
| `gemini_verify.py`, `gemini_component.py` | 3. sekme: sayfa görüntüleri, yanıt doğrulama, tarayıcı bileşeni |
| `gemini_tasks_component.py` | Genel tarayıcı Gemini görev bileşeni (6. sekme) |

---

## 10. Testler ve örnek dosyalar

```bash
cd curriculum_checker
```

```bash
python -m pytest -q
```

- Örnek dosyalar `samples/` klasöründedir ve **repoya eklenmez** (`.gitignore`); yoksa ilgili testler atlanır.
- Kullanılan örnekler: müzik, bilisim, biyoloji, temeldinibilgiler, arnavutca, abazaca, adigece, zazaca, lazca,
  kurmanca, fizik, kimya, fen, hayalbilgisi, afet, matematik, dınornek (Din Hizmetleri), `system-example.xlsx`
  (Arnavutça 5. sınıf sistem Excel'i).
- Her programın FAIL/NEEDS_REVIEW bulgu kümesi PDF'te tek tek doğrulanmış kaynak durumlarıdır ve testlerde sabitlenmiştir.
- Sağlamlık testleri: yapı sayfası PDF'ten silinmiş gibi ve "YAPISI" ipucu yokmuş gibi çıkarım
  (`test_science_regression.py`); örnekle verilen yapı ile otomatik yapının aynı sonucu vermesi
  (`test_manual_schema.py`).
- Değişiklik yaparken tavsiye edilen yöntem: bütün örnekleri değişiklikten önce ve sonra çalıştırıp birim /
  ÖÇ / bölüm / bulgu listelerini karşılaştırmak; beklenmeyen her farkı PDF'te doğrulamak.

---

## 11. Bilinen sınırlamalar ve yeni bir PDF'te sorun çıkarsa

- Tema başlıkları gövde metniyle aynı renkteyse ya da başlıkta iki nokta yoksa ("1. ÜNİTE DİN …") birimler
  tanınmaz.
- Tek sütunlu tema sayfası düzeni varsayılır (başlıklar solda, içerik sağda).
- Görüntü (taranmış) PDF'lerde metin katmanı olmadığı için çıkarım yapılamaz.
- Gemini ile tamamlamada hücre sayfası bilinmiyorsa temanın bütün sayfaları gönderilir.

**Yeni bir PDF "yapı tanınamadı" derse:** önce 1. sekmedeki elle yapı formunu deneyin (PDF'te yazdığı gibi bir
tema başlığı ve bir ÖÇ kodu). Yine olmuyorsa ya da sonuç yanlışsa PDF'i `samples/` klasörüne koyup
inceleyin: `extract_spans` ile ilgili sayfanın span'larını (metin, bbox, font, renk, boyut) yazdırmak sorunun
yerleşimden mi (bölünmüş başlık, farklı renk, satır aralığı) yoksa biçimden mi (anahtar kelime, kod) olduğunu
genellikle hemen gösterir. Düzeltmeyi genel bir kural olarak yapın, program adına göre değil; sonra bütün
örneklerde öncesi/sonrası karşılaştırmasını çalıştırın.
