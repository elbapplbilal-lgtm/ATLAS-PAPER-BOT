# ATLAS — واجهة مراقبة Hyperliquid للهاتف

## شنو خدام؟
- `index.html` واجهة ATLAS للهاتف باللغة العربية (وضع داكن).
- `assets/atlas.css` التصميم المتجاوب.
- `assets/atlas.js` يقرأ ملفات البيانات العامة الموجودة في المستودع فقط؛ بلا مفاتيح وبلا تداول.
- `hyperliquid_monitor.py` يجلب شموع BTC الحقيقية المغلقة (15 دقيقة) من Hyperliquid، ويحسب المؤشرات، ويكتب:
  - `data/hyperliquid_btc_15m.json` للسعر و RSI و EMA والدعم/المقاومة.
  - `data/hyperliquid_btc_candles.json` لآخر 120 شمعة حقيقية حتى يظهر الشارت.
- `.github/workflows/hyperliquid.yml` مجدول تقريباً كل 15 دقيقة لتحديث ملفات البيانات.
- `.github/workflows/deploy-atlas-site.yml` ينشر الموقع إلى GitHub Pages عند تحديث الملفات.

## تشغيل الموقع مجاناً من الهاتف
1. افتح صفحة المستودع على GitHub.
2. ادخل إلى **Settings** ثم **Pages**.
3. تحت **Build and deployment** اختَر **Source: GitHub Actions**.
4. ادخل إلى **Actions** ثم اختر **ATLAS Website - GitHub Pages** واضغط **Run workflow**. إذا كان هناك تشغيل ناجح بعد تفعيل Pages، قد لا تحتاج للتشغيل اليدوي.
5. بعد ظهور العلامة الخضراء على نشر الموقع، افتح:

   https://elbapplbilal-lgtm.github.io/ATLAS-PAPER-BOT/

## احتياطات
- الموقع **تحليل فقط**. لا يوصل محفظتك ولا يشغل شراء/بيع.
- ما تشارك حتى مفتاح خاص، API Secret، أو عبارة استرداد.
- أسعار الواجهة هي **آخر شموع محفوظة** وليست بثاً كل ثانية. قد يكون هناك تأخير بسبب GitHub Actions وPages.
- إذا كان Pages غير مفعّل، وظيفة النشر قد تفشل برسالة **Not Found** أو **Resource not accessible by integration**. الحل هو تفعيل Pages يدوياً من Settings.
- إذا ظهرت بيانات قديمة، راجع حالة Workflow `ATLAS Hyperliquid BTC - تحليل كل 15 دقيقة` وحدّث الصفحة.
