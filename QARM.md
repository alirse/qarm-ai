# مساحة قرم الجديدة

واجهة `/admin/qarm/chat` أصبحت مساحة موحدة فيها محادثات متعددة، ردود متدفقة، نسخ الأكواد، حفظ اختياري على الجهاز، صور مولدة فعليًا، بحث مع مصادر، وجلسات البرمجة ضمن الواجهة. تبقى صفحات وأدوات المشروع السابقة متاحة.

## النماذج الفعلية

- Groq GPT OSS 120B و20B للمحادثة؛ ميزانية السياق والرد محسوبة، ولا يوجد انتقال تلقائي إلى مزود آخر.
- FLUX.1 Schnell من Hugging Face: تم توليد صورة حقيقية من خلال مسار قرم في 12 أكتوبر 2026، بدون توكن أو API مدفوع.
- RealVisXL وJuggernaut XL: تم ربط المحولات بعروض ZeroGPU العامة، لكن اختبارات اليوم انتهت بخطأ خدمة/حصة دون صورة مكتملة؛ جاهزية العرض لا تضمن نجاح كل طلب.
- الصور تمر عبر خادم قرم وتُحفظ خارجه في مجلد الإعدادات الخاص، ولا تُرفع إلى GitHub.
- الفيديو والنماذج الكبيرة الموجودة كأوزان فقط لم تُفعّل؛ تحتاج خدمة استدلال وموارد مناسبة، ولا ننزّلها إلى Codespaces CPU أو نستدعي خدمة مدفوعة.

## النشر المستقل

أضيف `Dockerfile` و`render.yaml` وسكربت بدء محمي، بخطة Render Free فقط. **لم تُنشأ الاستضافة المستقلة بعد ولم تُنقل مفاتيح الحساب إليها.** تفاصيل النوم والتخزين والحماية في [دليل النشر](deploy/README.md).

# قرم — Qarm AI

## الاستخدام

بعد تسجيل دخول المالك، افتح `/admin/qarm/chat` للمحادثة العربية من الكمبيوتر أو Safari على الآيفون. رابط المحادثة ظاهر في لوحة الإدارة. يمكن إضافة الرابط إلى الشاشة الرئيسية في الآيفون من قائمة المشاركة.

- المحادثة النصية تستخدم Groq المُعد مسبقًا على الخادم؛ لا تحتاج إلى إدخال مفتاح في المتصفح.
- الاختيار الافتراضي GPT OSS 120B، ويمكن اختيار GPT OSS 20B يدويًا. لا تتحول هذه الواجهة تلقائيًا إلى مزود آخر.
- الرد المتوازن 1024 توكن والمطول 4096، والتفصيلي يطلب حتى 8192 ضمن الحصة المتاحة. يُخفض الحد عند اقتراب السياق من الميزانية.
- يُحسب السؤال والسياق دون اقتطاع هامش احتياطي اعتباطي ضمن ميزانية 8000 توكن، بناءً على حصة Groq المجانية الحالية للنموذج الافتراضي. التقدير تقريبي؛ استجابة Groq الفعلية هي المرجع. حدود حسابك قد تختلف.
- معالجة Groq العامة تعيد المحاولة مرة واحدة عند خطأ TPM 413 قابل للتصحيح، بخفض ميزانية الرد فقط دون تغيير رسائل السؤال أو أدوات البرمجة.
- وصول الحصة المؤقتة يظهر كرسالة انتظار. لا توجد ترقية أو اشتراك أو fallback مدفوع في واجهة المحادثة.
- لا تُحذف أجزاء من السياق تلقائيًا. عندما يطول، احفظ المحادثة ثم ابدأ واحدة جديدة أو اختصر الرسالة.
- حفظ المحادثة على الجهاز اختياري؛ لا يتزامن بين الآيفون والكمبيوتر. زر حفظ المحادثة يصدر ملفًا نصيًا.
- رسالتك تبقى عند فشل الاتصال. لا تعاد الطلبات تلقائيًا من الواجهة.

## أدوات المشروع

البرمجة وتنفيذ المهام: `/admin/code`. البحث: `/admin/qarm/search`. الصور: `/admin/qarm/images`. Codex المحلي: `/admin/qarm/codex-local`. الجاهزية: `/admin/qarm/ready`.

المحادثة النصية لا تنفذ أوامر ولا تقرأ ملفات جهازك. أدوات المشروع السابقة محفوظة وتعمل بحسب إعداداتها الخاصة. مسار Codex يستعمل تسجيل دخول ChatGPT الموجود، وله حدود مستقلة عن Groq.

## التشغيل والتحديث

النسخة الحالية تعمل في Codespaces. حفظ التغييرات على GitHub لا يحدّث عملية الخادم العاملة تلقائيًا. حدّث الفرع ثم أعد تشغيل الخادم من مساحة العمل الحالية، مع الحفاظ على إعداداتها المحلية وعدم رفع ملفات `.env` أو بيانات تسجيل الدخول.

```bash
git pull --ff-only origin qarm/python-version-setup
uv sync --locked --no-dev
uv run --no-sync fcc-server
```

إذا توجد تعديلات محلية، راجعها قبل السحب؛ لا تستعمل reset أو تحذفها. لا تشغل نسخة ثانية على المنفذ نفسه.

هذه التغييرات لا تضيف استضافة دائمة أو تغيّر فواتير Codespaces. يجب أن تكون مساحة العمل قيد التشغيل حتى يعمل الرابط. لا تفعل أي خطة مدفوعة لتحقيق تشغيل دائم.

## التحقق

```bash
uv sync --locked
uv run --no-sync pytest -n 4 tests/api/test_qarm* tests/providers/test_groq* tests/api/test_groq_token_limits.py -q
```

الاختبارات تستخدم بدائل لخدمات المزود، ولا تكشف المفاتيح أو تستعمل رصيد Groq. اختبار الحساب الحي يتطلب الوصول للخادم الحالي وإعداداته الخاصة.

المراجع: https://console.groq.com/docs/rate-limits — https://console.groq.com/docs/api-reference

### Personal-use limits and research (2026-10-12)

Qarm does not impose a cumulative image quota or a 40-turn conversation quota. The image duplicate cache retains only the latest 256 IDs; evicting metadata does not delete generated files. Groq responses can request up to 8192 tokens and are bounded by the remaining estimated 8000-token-per-minute free allowance, with authoritative provider correction. Provider rate limits, context budgets and model behavior still apply; unlimited free inference or guaranteed accuracy is not promised. Deep research reads up to six public HTTPS sources and the workspace synthesizes their excerpts through the existing Groq model with numbered references. If synthesis fails, source cards remain available. Excerpts are partial and untrusted; citations require checking against the linked source.
