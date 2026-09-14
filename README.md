# Smart Money Tracker

يراقب العملات الرايجة والجديدة عبر Solana + EVM chains (Ethereum/BSC/Base/Arbitrum) + Tron،
ويكشف صفقات الشراء الضخمة (whale buys) تلقائياً بدون قوائم محافظ يدوية.
يبعث تنبيه تلقرام فوري + يعرض داشبورد مباشر على الويب.

## التشغيل محلياً

\`\`\`bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
\`\`\`

افتح `http://localhost:8000`

## متغيرات البيئة المطلوبة

| المتغير | الوصف | إجباري؟ |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | توكن بوت التلقرام | لا (بدونه ما يوصل تنبيه تلقرام، بس الداشبورد يشتغل) |
| `TELEGRAM_CHAT_ID` | آيدي الشات اللي يوصله التنبيه | لا |
| `ETHERSCAN_API_KEY` | مفتاح Etherscan (مجاني) | لا (يحسن حد الطلبات) |
| `BSCSCAN_API_KEY` | مفتاح Bscscan | لا |
| `BASESCAN_API_KEY` | مفتاح Basescan | لا |
| `ARBISCAN_API_KEY` | مفتاح Arbiscan | لا |
| `WHALE_BUY_THRESHOLD_USD` | أقل قيمة صفقة تعتبر ذكية/ضخمة (افتراضي 5000) | لا |

⚠️ **مهم**: لا تحط أي توكن مباشر بالكود. كلها لازم تنحط كـ Environment Variables
(على Render: Dashboard → Environment).

## النشر على Render

1. نوع الخدمة: **Web Service** (مو Background Worker)
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. ضيف الـ Environment Variables اللي فوق
