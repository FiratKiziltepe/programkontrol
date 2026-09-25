# Minimal PRD — Öğretim Programı PDF → Excel Doğrulama ve Karşılaştırma Aracı

## 1. Amaç

Tek kullanıcılı, basit bir web uygulaması.

Uygulamanın yalnızca üç işi vardır:

1. Öğretim programı PDF'sini yüklemek ve PDF'deki verileri doğru, eksiksiz ve bölüm karışması olmadan yapılandırılmış tabloya dönüştürmek.
2. PDF'nin kendi iç tutarlılığını kontrol etmek:
   - kaç tema/ünite/öğrenme alanı var,
   - kaç öğrenme çıktısı bekleniyor / çıkarıldı,
   - tema/ünite girişinde tanımlanan değer, eğilim, beceri vb. kodlar öğrenme-öğretme uygulamalarında kullanılmış mı,
   - uygulamalarda kullanılan kodlar tema/ünite girişinde tanımlı mı,
   - eksik, fazla, tekrarlı veya sıra dışı kod var mı.
3. Müfredat sisteminden indirilen Excel dosyasını yükleyip PDF'den üretilen tabloyla karşılaştırmak ve farkları raporlamak.

Login, kullanıcı yönetimi, Docker, queue, ayrı backend/frontend, veritabanı zorunluluğu yoktur.

### Kapsam dışı

Türkçe ve İngilizce öğretim programları, yapıları diğer programlardan farklı olduğu için kapsam dışıdır. İngilizce, diğer programlar tamamlandıktan sonra ayrıca değerlendirilebilir.

---

## 2. Önerilen teknoloji

En uygun basit çözüm:

- Python 3.11+
- Streamlit
- PyMuPDF
- pandas
- openpyxl
- google-genai
- pydantic
- rapidfuzz (yalnızca kontrollü başlık eşleştirme için)

Tek komutla çalışır:

```bash
streamlit run app.py
```

---

## 3. Uygulama akışı

### Ekran 1 — PDF Yükle ve Analiz Et

Kullanıcı PDF yükler.

Buton:
`PDF'yi Analiz Et`

Sistem:

1. PDF'nin metin + layout bilgilerini çıkarır.
2. Programın yapı/tanıtım sayfasını bulur.
3. PDF'de kullanılan gerçek bölüm başlıklarını öğrenir.
4. Gerçek tema/ünite/öğrenme alanlarını bulur.
5. Her birimi çok sayfalı olarak işler.
6. Verileri tabloya dönüştürür.
7. Eksiksizlik ve kod kontrollerini çalıştırır.
8. Sonuçları ekranda gösterir.
9. PDF'den üretilen Excel indirilebilir.

### Ekran 2 — PDF Kontrol Sonuçları

Gösterilecekler:

- Beklenen tema/ünite sayısı
- Bulunan tema/ünite sayısı
- Beklenen öğrenme çıktısı sayısı
- Çıkarılan öğrenme çıktısı sayısı
- Eksik öğrenme çıktıları
- Fazla/tekrarlı kodlar
- Bölüm karışması tespitleri
- Kaynak PDF'deki olası kod anomalileri
- Tanımlanmış ama kullanılmamış kodlar
- Kullanılmış ama tanımlanmamış kodlar

### Ekran 3 — Sistem Excel'i ile Karşılaştır

Kullanıcı müfredat sisteminden indirilen Excel'i yükler.

Buton:
`Karşılaştır`

Sistem iki tabloyu mantıksal olarak eşleştirir ve aşağıdakileri gösterir:

- Aynı
- PDF'de var, sistem Excel'de yok
- Sistem Excel'de var, PDF'de yok
- Yanlış bölüm/sütunda
- Kod farklı
- Metin farklı
- Yalnızca satır/boşluk biçimi farklı
- Öğrenme çıktısı sayısı farklı

### Ekran 4 — Rapor

Renkli hata tablosu:

- yeşil: aynı
- mavi: yalnızca biçim farkı
- sarı: uyarı / kaynak PDF anomalisi
- kırmızı: gerçek hata
- mor: yanlış bölüm

Rapor Excel olarak indirilebilir.

---

## 4. PDF'den veri çıkarma yaklaşımı

### 4.1. Düz metin parser ana yöntem olmayacak

Şu yaklaşım kullanılmayacak:

```python
page.get_text()
```

ile bütün PDF'yi düz metne çevirip başlıklar arasında metin kesmek.

Ana yöntem:

```python
page.get_text("dict")
```

Her metin parçası için saklanacak:

- sayfa
- metin
- bbox
- font
- font size
- block
- line

Bu bilgiler bölüm sınırlarını belirlemek için kullanılacak.

---

## 5. PDF'deki metne yüzde 100 sadakat

Sistem PDF'de olmayan hiçbir metni üretmeyecek.

Her çıkarılan alan için:

```json
{
  "text": "PDF'de geçen gerçek metin",
  "pages": [26, 27],
  "source_spans": ["P26_S44", "P27_S02"]
}
```

tutulacak.

İzin verilen tek normalizasyonlar:

- satır sonu
- gereksiz çoklu boşluk
- PDF kaynaklı soft-hyphen
- görsel satır kayması

Yasak:

- yazım düzeltme
- kod düzeltme
- çeviri
- yeniden ifade etme
- eksik metni modelin tamamlaması

---

## 6. Program yapısının otomatik öğrenilmesi

Her program için elle başlık/kod tanımlanmayacak.

Sistem PDF'deki yapı/tanıtım sayfasını bulacak.

Gemini bu sayfada yalnızca:

- hangi span'ların bölüm başlığı olduğunu,
- hangi span'ların örnek bölüm içeriği olduğunu,
- başlıkların sırasını

belirleyecek.

Gemini yeni başlık üretmeyecek.

Örnek:

```json
{
  "label_span_ids": ["P21_S18", "P21_S19"],
  "value_span_ids": ["P21_S20", "P21_S21"]
}
```

Başlığın metnini Python doğrudan PDF span'larından alacak.

Bu nedenle bir programda başlık (ör. `ALAN BECERİLERİ`) nasıl geçiyorsa öyle kalır.

---

## 7. Şema sayfası ile gerçek veri ayrımı

Program yapısını anlatan örnek sayfalar gerçek tema/ünite olarak tabloya alınmayacak.

Önce:

- `PROGRAMIN YAPISI`
- `STRUCTURE`
- benzeri tanıtım bölümleri

tespit edilir.

Gerçek veri bölümü başladıktan sonra tema/üniteler çıkarılır.

---

## 8. Çok sayfalı tema/ünite işleme

Bir tema tek sayfada olmak zorunda değildir.

Tema/ünite, bir sonraki gerçek tema/ünite başlığına kadar açık tutulur.

Aynı birim içinde aşağıdaki türde bölümler otomatik yakalanır:

- giriş bilgileri
- öğrenme çıktıları
- içerik çerçevesi
- öğrenme kanıtları
- temel kabuller
- ön değerlendirme
- köprü kurma
- öğrenme-öğretme uygulamaları
- zenginleştirme
- destekleme

Ancak kullanıcıya bölüm adları PDF'de yazıldığı şekliyle gösterilir.

---

## 9. Bölüm karışması kontrolü

Bir bölümün hücresinde başka bir bölüm başlığı geçiyorsa:

`SECTION_LEAKAGE`

hatası oluştur.

Örneğin:

bir öğrenme çıktısının son süreç bileşeni ile bir sonraki bölümün başlığı (`İÇERİK ÇERÇEVESİ`) aynı hücrede bulunmamalı.

Sistem bbox ve başlık konumlarını kullanarak yeniden ayırır.

Belirsizlik kalırsa yalnızca o sayfa Gemini'ye doğrulatılır.

---

## 10. Öğrenme çıktısı sayısı kontrolü

Programın özet/süre tablosunda:

```text
Tema 1 = 7 öğrenme çıktısı
```

yazıyorsa sistem bunu expected count olarak saklar.

Extraction sonucu:

```text
6
```

ise:

```text
Beklenen: 7
Bulunan: 6
Eksik: 1
STATUS: FAIL
```

olur.

Program toplamında da aynı kontrol yapılır.

---

## 11. Kodların otomatik keşfi

Kod prefix'leri global olarak hardcode edilmeyecek.

Sistem tema/ünite girişinde her bölümde geçen kodları çıkaracak.

Örneğin PDF'de:

```text
Değerler
D9. ...
D10. ...
D14. ...
```

varsa o belge için bu bölümün kod listesi:

```python
{"D9", "D10", "D14"}
```

olur.

Başka programda `Values` altında `V1`, `V3` varsa onu aynen öğrenir.

---

## 12. Kod normalizasyonu

İki değer saklanır:

```json
{
  "raw": "MÜZ. 5.1.6.",
  "normalized": "MÜZ.5.1.6"
}
```

Raw değer asla değiştirilmez.

Normalized değer yalnızca eşleştirme için kullanılır.

---

## 13. Kod çapraz kontrolü

Her tema/ünite için:

### A. Girişte tanımlanan kodlar

```text
Değerler: D9 D10 D14
Eğilimler: E1.1 E3.2
...
```

### B. Öğrenme-Öğretme Uygulamalarında kullanılan kodlar

Metin içinden tüm kodlar çıkarılır.

### C. İki yönlü kontrol

```text
USED BUT NOT DECLARED
DECLARED BUT NOT USED
MATCHED
```

Hiyerarşik kod desteklenir:

`D11.2` kullanılmış ve `D11` tanımlıysa ilişki kurulabilir.

---

## 14. PDF iç tutarlılık raporu

Her tema için:

```text
Tema: 1. TEMA: ...

Öğrenme çıktısı
Beklenen: 10
Bulunan: 10
PASS

Değerler
Tanımlanan: D9, D10, D14
Kullanılan: D9, D10, D14
PASS

Eğilimler
Tanımlanan: E1.1, E3.2, E3.7
Kullanılan: E1.1, E3.2
Kullanılmayan: E3.7
WARNING
```

---

## 15. PDF'den oluşturulan tablo

İki format saklanabilir:

### A. Geniş tablo
Tema/ünite başına bir satır.

### B. Sistem karşılaştırma tablosu
Müfredat sisteminin Excel yapısına yakın long-format.

Karşılaştırma için asıl kullanılacak olan B'dir.

---

## 16. Sistem Excel'i okuma

openpyxl kullanılacak.

Korunacak:

- sheet
- hücre adresi
- raw hücre değeri

Boş devam satırları doğru parent kayda bağlanacak.

Örneğin Tema ve Öğrenme Çıktısı boş fakat Süreç Bileşeni doluysa bu yeni kayıt değil, önceki öğrenme çıktısının devamıdır.

---

## 17. İki Excel'i karşılaştırma

Doğrudan satır numarasına göre karşılaştırma yapılmayacak.

Öncelik:

1. öğrenme çıktısı kodu
2. tema/ünite
3. bölüm
4. içerik

Durumlar:

- `AYNI`
- `SADECE_BİÇİM_FARKI`
- `PDF_DE_VAR_EXCELDE_YOK`
- `EXCELDE_VAR_PDF_DE_YOK`
- `YANLIŞ_BÖLÜM`
- `KOD_FARKLI`
- `METİN_FARKLI`
- `SAYI_FARKLI`
- `İNCELEME_GEREKLİ`

---

## 18. Kullanıcı arayüzü

Streamlit içinde dört sekme yeterli:

### 1. PDF Analizi
- PDF yükle
- Analiz et
- progress bar
- sonuç tablosu
- PDF'den oluşturulan Excel'i indir

### 2. PDF Kontrolleri
- sayı kontrolleri
- kod kontrolleri
- hata/uyarı listesi

### 3. Excel Karşılaştırma
- sistem Excel'i yükle
- karşılaştır
- renkli sonuç tablosu

### 4. Rapor
- özet
- hatalar
- Excel raporu indir

---

## 19. Gemini kullanımı

Gemini yalnızca:

1. yapı/tanıtım sayfasındaki bölüm başlıklarını seçmek,
2. bbox ile kesin ayrıştırılamayan bölümü doğrulamak,
3. zor layout sayfasında span'ların hangi bölüme ait olduğunu belirlemek

için kullanılır.

Gemini:

- metin düzeltmez,
- yeni metin yazmaz,
- kod üretmez,
- eksik metni tamamlamaz.

Structured JSON kullanılır.

Free API kotasını korumak için yalnızca gerekli sayfalar Gemini'ye gönderilir.

---

## 20. Dosya yapısı

```text
curriculum_checker/
│
├── app.py
├── pdf_extract.py
├── schema_detect.py
├── unit_extract.py
├── validators.py
├── excel_import.py
├── compare.py
├── gemini_verify.py
├── models.py
├── requirements.txt
└── .env
```

Bu kadar.

---

## 21. Saklama

Veritabanı zorunlu değil.

Bir analiz sırasında:

```text
temp/
  source.pdf
  extracted.json
  extracted.xlsx
  system.xlsx
  comparison.xlsx
```

kullanılabilir.

Uygulama kapandığında silinebilir.

---

## 22. Temel kabul kriterleri

Bir PDF analizi ancak şu durumda başarılı sayılır:

1. tüm tema/üniteler bulunmuş,
2. beklenen ve çıkarılan öğrenme çıktısı sayıları eşit,
3. hiçbir bölüm başka bölümün başlığını/içeriğini yanlışlıkla içermiyor,
4. her çıkarılan metin PDF kaynak span'larına bağlı,
5. kod kontrolleri tamamlanmış,
6. çözülemeyen bölüm yok.

Bunlardan biri sağlanmıyorsa sistem:

`İNCELEME GEREKLİ`

veya

`HATA`

gösterir.

Ama yanlış veriyi doğruymuş gibi dışarı vermez.

---

## 23. MVP başarısı

İlk sürümün başarı kriteri:

- programın yapı/tanıtım sayfasını gerçek tema/ünite olarak almaması,
- tema/ünite bölümlerini başka bölümlere taşırmadan ayırması,
- Müzik programındaki kod boşluğu/noktalama varyasyonlarını eşleştirebilmesi,
- sistem Excel'indeki continuation satırlarını doğru birleştirmesi,
- beklenen/çıkarılan öğrenme çıktısı sayılarını raporlaması,
- iki Excel arasındaki eksik/fazla/yanlış bölüm/metin farklarını göstermesi.

---

## 24. Öncelik

1. PDF'den doğru ve eksiksiz veri çıkarma
2. PDF iç tutarlılık kontrolleri
3. Sistem Excel'i ile doğru karşılaştırma
4. Kullanıcı dostu raporlama

Başka özellik eklenmeyecek.
