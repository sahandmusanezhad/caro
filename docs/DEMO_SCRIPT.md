# Demo script — CARO, 5:00

Written for the Torob AI Product Engineer submission. Persian narration,
English on screen (the repo is English; subtitles or a re-record in English
are a swap of this one file).

Every number below is either reproducible from the repository or preserved as
a committed run transcript. Those are two different things and the script must
not blur them.

The synthetic figures are **reproducible with no network**: `python3
tests/run_all.py` and `python3 tests/run_all.py ranking` re-derive them on any
clean clone.

The Run 3 and Run 5 figures are **transcripts, not reproductions**. Their
corpora were never committed and are not recoverable (D46), so
`benchmark_run3.py`, `benchmark_run5.py`, `run5_significance.py`,
`rank_run3.py` and `rank_run5.py` cannot run here. Their committed output in
`docs/` is what may be filmed, and no frame may imply it is being re-derived
on camera.

---

## The two decisions that shape this script

**It is centred on the decision, not on the estimator.** The earlier cut
centred on two benchmarks that disagree. That is a statistics talk, and a
judge who has watched it for a minute can fairly ask what the product is.
CARO's thesis is a decision engine: intent, retrieval, priced risk, ranking,
an evidence ledger, and a refusal state. The market estimate is one input to
it. So the estimator's story moves to 3:40 and stops being the spine.

**And every frame is labelled with what it runs on.** This is the constraint
the rewrite had to solve, and it is not cosmetic. D41: on *every* real corpus
this project has collected, CARO refuses to serve a market estimate — Run 3
returns UNJUDGEABLE_SLICE → DO NOT SERVE, Run 5 returns REJECTED, and on Run
5's corpus the gate returns no usable verdict at all: the split is so far out
of support that comparable- and global-quantiles collapse into one predictor
(D43). `Ranker.score` calls `estimator.predict`, which raises. **A ranked shortlist over real Bama
listings is not filmable today, and no cut of this video may imply it is.**

So the demo shows the decision path on the synthetic corpus with the word
SYNTHETIC on screen, shows the same pipeline refusing on real listings, and
says which is which out loud. That is a weaker-looking demo than the one that
quietly films the synthetic corpus and calls it Bama. It is the only one this
project is allowed to make.

---

## 0:00–0:30 · Why the obvious product fails

> **VO (fa):** ترب یک کار را عالی انجام می‌دهد: یک کالای مشخص را در چند
> فروشگاه پیدا می‌کند و ارزان‌ترین را نشان می‌دهد. این وقتی جواب می‌دهد که
> همهٔ فروشنده‌ها **یک چیز** را می‌فروشند.
>
> در خودروی دست‌دوم چنین چیزی وجود ندارد. دو پراید ۹۵ با یک قیمت، دو کالای
> متفاوت‌اند. پس «ترب برای ماشین» می‌شود یک لیست با دکمهٔ مرتب‌سازی — و
> مرتب‌سازی بر اساس قیمت می‌تواند خریدار را سیستماتیک به سمت خراب‌ترین ماشینِ
> همان بودجه ببرد.

**Screen:** two real Bama Pride listings side by side, same price, different
condition fields. Then a price-sorted list, cheapest highlighted.

**Note to self:** «می‌تواند» is load-bearing — D36. Not «همیشه».

---

## 0:30–2:10 · One decision, end to end · **SYNTHETIC CORPUS**

The centre of the video. The label sits in the corner for all 100 seconds.

> **VO:** پس CARO به‌جای مرتب‌کردن، تصمیم می‌گیرد — و تصمیمش را قابل بازرسی
> نگه می‌دارد. این بخش روی پیکرهٔ ساختگی پروژه اجرا می‌شود، جایی که می‌دانیم
> جواب درست چیست. چرا، را دو دقیقهٔ بعد می‌گویم.

**Query:** «ماشین اول خانواده، تصادفی نباشه، بودجه ۱.۵ میلیارد»

> **VO:** اول نیت: بودجه، مدل، و چیزی که **استنباط** شده — «خانواده» یعنی
> ریسک‌گریز. استنباط روی صفحه نوشته می‌شود، چون فرضی که کاربر نبیند، فرضی
> است که نمی‌تواند اصلاحش کند. و «تصادفی نباشه» یک ترجیح نیست، یک شرط قطعی
> است و هیچ‌وقت شل نمی‌شود.

**Screen:** `IntentSpec` — budget, weights, `assumptions`, `deal_breakers`,
and `unparsed` (what the parser saw and could not map, kept rather than
dropped).

> **VO:** بعد رتبه‌بندی. هر عدد جداگانه نگه داشته می‌شود: ارزش، ریسکی که در
> تومان قیمت‌گذاری شده، کارکرد، نقدشوندگی. یک نمرهٔ مبهم وجود ندارد.

**Screen:** the three-card shortlist with the term breakdown open on the top
pick — `value`, `risk`, `mileage` visible as separate rows, each in tomans.

> **VO:** و ریسک **ضرب** نمی‌شود، **کم** می‌شود. یک تخمین نامطمئن یک فرصت
> کوچک‌تر نیست، یک شرط پرریسک‌تر است.

**Screen:** `opportunity = conservative − asking − expected_damage_toman`.

**Then move a weight, live:** «قابلیت اطمینان برایم مهم‌تر است.» The order
changes on screen with no round trip.

> **VO:** وزن‌ها مال کاربر است، نه مال ما.

---

## 2:10–2:50 · The part that refuses · **SYNTHETIC CORPUS**

**Query:** «پراید کم‌کارکرد تا ۸۰۰ میلیون»

> **VO:** حالا یک درخواست که جواب کافی ندارد. CARO لیست خالی نمی‌دهد و در
> عین حال چیزی از خودش نمی‌سازد. می‌گوید چه چیزی را شل کرد، به زبان خود
> کاربر.

**Screen:** the relaxation ladder's Persian line, verbatim from
`RelaxationReport.text_fa()`.

> **VO:** و در سطح بالاتر، وقتی شواهد کافی نیست، اصلاً عدد نمی‌دهد.

**Screen:** case F — `INSUFFICIENT_EVIDENCE`, reasons listed; then
`NotBenchmarked` raised in the code, one line.

> **VO:** این یک پیام خطا نیست، یک حالت محصول است. تا وقتی برآوردگر از
> دروازهٔ ارزیابی رد نشده، فراخوانی‌اش یک استثنا می‌دهد، نه یک عدد. صداقت
> اینجا یک قاعده در مستندات نیست، در تایپ‌سیستم است.

---

## 2:50–3:40 · What happens on real Bama listings · **REAL DATA**

The label changes on screen. This transition is the honest heart of the video
and it must be visible, not narrated away.

> **VO:** حالا همان خط لوله، روی ۴۰۳ آگهی واقعی که خودمان از باما جمع کردیم.

**Screen:** `docs/RANK_RUN5_2026-09-08.txt` — the committed transcript of
that run, opened as a file. **Not run live.** Run 5's corpus is gone (D46), so
`rank_run5.py` raises here; filming a terminal would either fail on camera or
require a corpus that no longer exists. The transcript carries both frames this
section needs — the term-liveness table and the refusal line — so nothing is
lost but the keystrokes. The corner label stays REAL DATA: the run was real.
What the narration may not say, in any wording, is that it is happening now.

> **VO:** نیت درست خوانده می‌شود. بازیابی کار می‌کند — شش تا ۲۰۶ واقعی داخل
> بودجه. نردبان شل‌سازی کار می‌کند. و بعد:

**Screen:** hold on the line `shortlist — refused: estimator is not gated`.

> **VO:** رد می‌کند. روی **هر** پیکرهٔ واقعی که تا امروز جمع کرده‌ایم، CARO
> حاضر نیست یک برآورد بازار سرو کند. Run 3 گفت شواهدِ سرو کردن کافی نیست؛
> Run 5 مدل را رد کرد؛ و روی پیکرهٔ Run 5 خودِ دروازه هم قدرت تفکیک ندارد —
> split آن‌قدر بیرون از پشتیبانی است که دو baseline به یک برآوردگر تبدیل
> می‌شوند.
>
> و دو چیز دیگر که همین اجرا نشان داد: از شش ترمِ رتبه‌بندی، **چهارتا روی
> دادهٔ واقعی ثابت‌اند** — ریسک، هزینهٔ نگهداری و نقدشوندگی را W4 اصلاً پر
> نمی‌کند. یعنی چهار تا از شش اسلایدری که همین الان نشانتان دادم، روی دادهٔ
> باما هیچ کاری نمی‌کنند.

**Screen:** the term-liveness table, `LIVE` / `CONSTANT` column visible.

> **VO:** این را می‌شد نشان نداد. ولی تفاوت بین یک محصول و یک دموی محصول
> دقیقاً همین است.

---

## 3:40–4:20 · The estimator, and a rejection that failed too · **REAL DATA**

> **VO:** و حالا کوتاه، داستان برآوردگر — چون یک درس دارد.

**Screen:**

```
Run 3   155 آگهی · ۴ مدل سایپا      MAE  63.9M  vs 133.4M   −52.1%   UNJUDGEABLE
Run 5   228 آگهی · ۴۴ برند          MAE 607.0M  vs 526.3M   +15.3%   REJECTED
```

> **VO:** همان برآوردگر، همان گیت، همان ثابت‌های منجمد. فقط پیکره عوض شد —
> و دومی، که ثبت‌نامه‌اش قبل از اولین درخواست نوشته شده بود، مدل را رد کرد.
>
> بعد عدم‌قطعیت خودِ آن رد را اندازه گرفتیم.

**Screen:**

```
ΔMAE  +80.7M  (+15.3%)      95% CI  [−324M, +436M]
P(worse by more than the gate's 10%)  =  58%
```

> **VO:** پنجاه‌وهشت درصد. یعنی همان گزاره‌ای که گیت رویش رد کرد، از پرتاب
> سکه قابل تفکیک نیست. معیارِ MAE در گیت هیچ کنترل عدم‌قطعیتی نداشت — و ما
> این را در سه جای دیگرِ همین پروژه درست کرده بودیم و کنارش را ندیده بودیم.
>
> پس Run 5 فقط حق دارد هر دو نیمه را با هم بگوید: گیتِ منجمد طبق معیار
> ثبت‌شده‌اش رد کرد؛ و آن معیار نمی‌توانست این را از نویز جدا کند. برآوردگر
> نه بهتر از baseline نشان داده شده، نه بدتر.

**Screen:** `EVAL_CONTRACT_V2.md`, frozen, with the falsifier line visible.

> **VO:** معیار را قبل از آزمایش بعدی درست کردیم، نه بعدش. و نوشتیم چه چیزی
> این ادعا را باطل می‌کند: اگر نسخهٔ بعدیِ این قرارداد پذیرش را شل کند نه
> سخت، دقیقاً همان چیزی است که ادعا می‌کند نیست.

---

## 4:20–5:00 · What is measured, and what is not

> **VO:** پس صادقانه‌ترین جمع‌بندی این است:

**Screen, held for six seconds — this is the closing slide (D44):**

```
REAL DATA    ingestion                    VALIDATED
             extraction contracts         VALIDATED / AUDITABLE
             snapshot completeness        AUDITABLE
             ranking inputs               AUDITABLE   (38% complete)
             appraisal                    NOT VALIDATED
             ranking quality              NOT VALIDATED
             ground truth for ranking     NO GROUND TRUTH

SYNTHETIC    pipeline behaviour · ranking mechanics ·
             decision ledger · explanation and evidence path
```

> **VO:** بیشترین شواهد را جایی گذاشته‌ایم که تز محصول کمترین نیازش را دارد.
> این خودش یک یافته است و ثبت شده — D41.
>
> و روی دادهٔ واقعی، CARO در ویدیو بی‌سروصدا شکست نمی‌خورد. به مرزِ ارزیابی
> می‌رسد و می‌گوید **شواهد کافی برای این ادعا ندارم**. هر سطر بالای این
> اسلاید، چیزی است که به آن جمله حق می‌دهد باور شود.
>
> کار بعدی هم از همین بیرون می‌آید: قبل از آزمایش ششم روی برآوردگر، آن چهار
> ترمِ مرده را از دادهٔ خودِ باما پر کن، و بفهم چرا baseline روی دادهٔ واقعی
> از دروازه رد نمی‌شود. یک محصولی که اصلاً نمی‌تواند برآورد سرو کند، مسئلهٔ
> بزرگ‌تری از این است که کدام برآوردگر را سرو می‌کرد.

**Screen, final, held for four seconds:**

```
۷۰۵ assertion · ۸ suite · ۴۶ decision · ۵ اجرای زنده روی باما
۰ ادعای بدون شواهد در خروجی

github.com/sahandmusanezhad/caro
```

> **VO (last line):** چیزی که ساختیم یک مدل قیمت نیست. سیستمی است که مرزِ
> دانستنِ خودش را اجرا می‌کند — حتی وقتی آن مرز، خودش را رد می‌کند.

---

## Production notes

- **Total 5:00.** If it runs over, cut from 3:40–4:20 (compress the estimator
  story to the two-line table and the 58%). Never cut 2:50–3:40. That section
  is the difference between this submission and one that films a synthetic
  corpus and lets the judge assume it is Bama.
- **The SYNTHETIC / REAL DATA label is on screen for every frame of
  0:30–3:40.** Not a title card at the start — a persistent corner label. A
  viewer who joins at 1:20 must be able to tell.
- Do not show a slide that says "−52%" without "+15.3%" in the same frame.
  That remains the most tempting editing mistake in the project.
- Do not show a ranked shortlist over real Bama listings. It does not exist;
  the pipeline refuses. If a future run gets the gate to pass on real data,
  this note is what has to be deleted first, deliberately.
- Screen-record `demo/index.html` at 1440p; the Persian copy must be legible
  at half size. Terminal sections run the real commands — `rank_run5.py`
  printing the refusal live is more convincing than a still of it.
- No music under 2:50–3:40. Let the refusal sit.
