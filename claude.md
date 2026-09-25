\# Project Rules



\- PDF'de olmayan hiçbir metni üretme.

\- PDF metnini düzeltme, yeniden yazma, çevirme veya tamamlama.

\- Bölüm başlıklarını PDF'de geçtiği şekilde koru.

\- Regex-only parser oluşturma; PDF bbox/layout bilgisini kullan.

\- Gemini yalnızca layout doğrulama için kullanılabilir.

\- Gemini'nin ürettiği yeni curriculum text'i kabul etme.

\- Kod prefix'lerini program bazında hardcode etme.

\- Yapı/tanıtım sayfasından program yapısını keşfet.

\- Beklenen öğrenme çıktısı sayısı ile çıkarılan sayı uyuşmuyorsa PASS verme.

\- Belirsizlikte tahmin yapma; NEEDS\_REVIEW üret.

\- Öncelik: extraction correctness > validation > Excel comparison > UI.

\- Gereksiz altyapı, login, Docker, database, REST API ekleme.

