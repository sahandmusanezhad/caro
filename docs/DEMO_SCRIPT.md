# Demo script — CARO, 5:00

Written for the Torob AI Product Engineer submission. Persian narration,
English on screen (the repo is English; subtitles or a re-record in English
are a swap of this one file).

Every number below is in the repository and reproducible with no network:
`python3 tests/run_all.py`, `scripts/benchmark_run3.py`,
`scripts/benchmark_run5.py`.

**The one decision that shapes this script.** The obvious cut ends on the
−52% number and stops. That video would be dishonest by omission: a later,
larger, pre-registered benchmark rejected the same estimator. So the ending
is REJECTED, and the argument is that a system which can produce that ending
is worth more than one that cannot. If that reads as a weaker submission, the
whole project was pointless.

---

## 0:00–0:35 · The premise, and why the obvious product fails

> **VO (fa):** ترب یک کار را عالی انجام می‌دهد: یک کالای مشخص را در چند
> فروشگاه پیدا می‌کند و ارزان‌ترین را نشان می‌دهد. این کار وقتی جواب می‌دهد
> که همهٔ فروشنده‌ها **یک چیز** را می‌فروشند.
>
> در خودروی دست‌دوم چنین چیزی وجود ندارد. دو پراید ۹۵ با یک قیمت، دو کالای
> متفاوت‌اند — کارکرد، رنگ‌شدگی، سند، شهر. پس «ترب برای ماشین» می‌شود یک
> لیست با دکمهٔ مرتب‌سازی، و مرتب‌سازی بر اساس قیمت می‌تواند خریدار را
> سیستماتیک به سمت خراب‌ترین ماشین ببرد.

**Screen:** two near-identical Pride listings side by side, same price,
different condition fields. Then a price-sorted list with the cheapest
highlighted.

**Note to self:** «می‌تواند» is load-bearing — D36. Not «همیشه».

---

## 0:35–1:20 · What CARO does instead

> **VO:** پس CARO به‌جای مرتب‌کردن، سه چیز را جدا می‌کند و بعد کم می‌کند:
> برآوردی از قیمت، خودِ قیمت خواسته‌شده، و ریسکی که در ریال قیمت‌گذاری شده.

**Screen:** the thesis as one line, then the pipeline:

```
value = estimate − asking − risk_discount

W4 ingest → W0 tracking → W1 appraisal → W3 ranking → W2 decision
```

> **VO:** چهار لایه، و فقط **یک جای** آن مدل زبانی است: تبدیل جملهٔ فارسی
> کاربر به یک نیت ساختاریافته. بعد از آن همه‌چیز قطعی و تکرارپذیر است —
> رتبه‌بندی، ریسک، توضیح. مدل زبانی پایین‌دستِ یک تصمیمِ منجمد می‌نشیند و
> اجازه ندارد عدد یا تصمیم را عوض کند.

**Screen:** highlight the LLM boundary on the diagram.

---

## 1:20–2:15 · One listing, end to end

Live in `demo/index.html`. Case **A**, then case **F**.

> **VO:** یک آگهی. CARO دامنهٔ قیمت را می‌دهد، و کنارش شواهدی که هر جمله از
> آن آمده. هر ادعا به یک مشاهده وصل است؛ ادعای بی‌پشتوانه اصلاً رندر
> نمی‌شود.

**Screen:** case A — estimate range, evidence ledger, seven-stage trace.

> **VO:** و مهم‌تر: CARO می‌تواند بگوید نمی‌دانم.

**Screen:** switch to case F — `INSUFFICIENT_EVIDENCE`, reasons listed.

> **VO:** این یک پیام خطا نیست، یک حالت محصول است. تا وقتی برآوردگر از
> دروازهٔ ارزیابی رد نشده، فراخوانی‌اش یک استثنای برنامه‌نویسی می‌دهد، نه یک
> عدد. صداقت اینجا یک قاعده در مستندات نیست، در تایپ‌سیستم است.

**Screen:** `NotBenchmarked` raised in the code, one line.

---

## 2:15–3:25 · Two benchmarks that disagree

The centre of the video. Do not rush it.

> **VO:** حالا بخش سخت. ما این برآوردگر را دو بار روی دادهٔ واقعی باما
> سنجیدیم.

**Screen:**

```
Run 3   155 آگهی · ۴۳ trim · ۴ مدل سایپا
        MAE  63.9M   baseline 133.4M    −52.1%   UNJUDGEABLE_SLICE

Run 5   228 آگهی · ۱۰۰ trim · ۴۴ برند
        MAE 607.0M   baseline 526.3M    +15.3%   REJECTED
```

> **VO:** همان برآوردگر. همان گیت. همان ثابت‌های منجمد. تنها چیزی که عوض
> شد، پیکرهٔ داده بود — و دومی، که بزرگ‌تر بود و پیش از اولین درخواست
> ثبت‌نامهٔ نوشته‌شده داشت، مدل را **رد کرد**.
>
> چرا؟ Run 3 چهار مدل سایپا بود. Run 5 چهل‌وچهار برند، با بازهٔ قیمتی
> **۱۴۳ برابری** — از ۳۵۰ میلیون تا ۵۰ میلیارد. partial pooling تخمین یک
> trim کم‌داده را به سمت پارِنتش جمع می‌کند؛ روی ۱۴۳ برابر، این یک تصحیح
> ملایم نیست، یک خطای بزرگ است.

**Screen:** the price histogram of each corpus, side by side. This single
image explains the whole result.

---

## 3:25–4:20 · What the disagreement taught

> **VO:** و اینجا چیزی پیدا شد که از خودِ نتیجه مهم‌تر است.
>
> ثبت‌نامهٔ Run 5 توزیع اندازهٔ trim را با جزئیات مقید کرده بود — شمارش‌ها،
> کف‌ها، اندازهٔ برش‌ها. و دربارهٔ **ناهمگنی قیمت هیچ نگفته بود**.
>
> هر دو پیکره شکل ثبت‌شده را برآورده می‌کنند. و مسئلهٔ تخمین یکسانی
> نیستند.

**Screen:** the spec's §2 shape constraints, then a red annotation on what
it does *not* constrain.

> **VO:** هیچ قاعده‌ای نقض نشد. ثبت‌نامه نسبت به متغیری که نتیجه را تعیین
> کرد نابینا بود — و **از قبل** نابینا بود. این تنها راهی است که چنین چیزی
> اثبات می‌شود. اگر معیار را بعد از دیدن نتیجه انتخاب کنیم، هیچ‌وقت
> نمی‌فهمیم.

**Screen:** `docs/RUN5_SPEC.md`, header: *"FROZEN, NOT STARTED"*, with the
commit date visibly before the run.

> **VO:** و یک چیز دیگر: pre-flight ما با هفت نمونه نتیجه گرفته بود نرخ
> تبدیل بدتر نیست. واقعیت ۰.۵۶۶ بود، نه ۰.۷۰۱. با n=۷ آن نتیجه‌گیری از
> ظرفیت نمونه‌اش جلو زده بود — و این ثبت شده، چون همان خطاست در مقیاس
> کوچک‌تر.

---

## 4:20–5:00 · The decision

> **VO:** پس تصمیم چیست؟
>
> از روز اول در سند تصمیم‌ها نوشته شده بود: **اگر baseline ببرد، baseline را
> بفرست و بگو.** روی این پیکره، baseline بُرد. پس همان می‌رود روی خط.

**Screen:** D12, with its original commit date.

> **VO:** CARO تخمین‌گر شرطی را سرو نمی‌کند. نه چون کار نمی‌کند — چون
> شواهدی که اجازهٔ آن را بدهد نداریم، و سیستم طوری ساخته شده که نتواند
> وانمود کند داریم.
>
> این نمی‌گوید partial pooling برای بازار ایران بد است. می‌گوید روی این
> پیکره، با این سؤال ثبت‌شده، باخت. سؤال بعدی یک آزمایش تازه است، با
> ثبت‌نامهٔ خودش — چون «مدل باخت، پیکره را عوض کنیم، مدل بُرد» دقیقاً همان
> حلقه‌ای است که این پروژه برای رد کردنش ساخته شده.

**Screen, final, held for four seconds:**

```
۶۱۱ assertion · ۷ suite · ۳۹ decision · ۵ اجرای زنده روی باما
۰ ادعای بدون شواهد در خروجی

github.com/sahandmusanezhad/caro
```

> **VO (last line):** چیزی که ساختیم یک مدل قیمت نیست. سیستمی است که
> مرزِ دانستنِ خودش را هم اجرا می‌کند.

---

## Production notes

- **Total 5:00.** If it runs over, cut from 0:35–1:20 (the architecture
  tour), never from 2:15–3:25. The two-benchmark section is the submission.
- Screen-record `demo/index.html` at 1440p; the Persian copy must be legible
  at half size.
- Terminal recordings: run the real commands. `benchmark_run5.py` takes a
  few seconds and printing live is more convincing than a still.
- Do not show a slide that says "−52%" without "+15.3%" in the same frame.
  That is the one editing mistake that would undo the argument, and it is
  the most tempting one.
- No music under 2:15–3:25. Let the numbers sit.
