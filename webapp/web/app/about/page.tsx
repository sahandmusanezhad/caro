import Link from 'next/link';

export const metadata = { title: 'درباره‌ی ما — CARO' };

/* Numbers on this page are reproducible from the repository, and one of them
   was wrong: 47 counted `^## D` HEADINGS, but D31 has a second heading —
   `## D31 (result)` — recording how that decision turned out. Headings are not
   decisions.
   Every number below is now derived from the thing it describes rather than
   maintained here: `tests/test_claims.py` recomputes the decision count from
   docs/DECISIONS.md, and `tests/run_all.py` compares the assertion total
   against its own run. Both fail the build when this file disagrees, because
   a count a human keeps beside a file that grows is a count that drifts. */

const FACTS: [string, string, string][] = [
  ['۵۵', 'تصمیم ثبت‌شده', 'docs/DECISIONS.md'],
  ['۱۲۱۲', 'گزاره‌ی آزمون', 'tests/run_all.py'],
  ['۱۰', 'مجموعه‌ی آزمون', 'یکی از آن‌ها فقط مراقب بازگشت ادعاهای بازنشسته است'],
  ['۰', 'وابستگی سنگین', 'هسته‌ی پروژه فقط به numpy نیاز دارد'],
];

export default function About() {
  return (
    <div className="flex flex-col gap-10">
      <section>
        <p className="eyebrow">درباره‌ی ما</p>
        <h1 className="m-0 text-[30px] font-bold leading-[1.4] max-w-[26ch]">
          تفاوت CARO مدلش نیست؛ این است که نمی‌گذارد ادعا از شواهدش جلو بزند
        </h1>
        <p className="mt-5 mb-0 text-[16px] leading-[2] text-ink-2
                      max-w-[64ch]">
          ساختن یک موتور جست‌وجوی خودرو کار سختی نیست. کار سخت این است که وقتی
          داده کافی نیست، سامانه به‌جای تولید یک عدد قانع‌کننده، سکوت کند — و
          سکوتش را توضیح بدهد. بیشتر این پروژه صرف ساختن جاهایی شده که سامانه
          اجازه ندارد حرف بزند.
        </p>
      </section>

      <section>
        <div className="grid gap-px bg-line border border-line sm:grid-cols-4">
          {FACTS.map(([n, k, src]) => (
            <div key={k} className="bg-surface p-5">
              <div className="num text-[26px] font-medium text-accent">{n}</div>
              <div className="text-[13.5px] mt-1">{k}</div>
              <div className="text-[11.5px] text-ink-3 mt-1.5 num
                              break-words">{src}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <p className="eyebrow">دفتر تصمیم‌ها</p>
        <p className="m-0 text-[15px] leading-[1.95] max-w-[64ch]">
          بیشتر آن ۵۵ تصمیم به این دلیل نوشته شده‌اند که چیزی به‌شکلی نامرئی
          خراب شده بود. دو تا از آن‌ها بیش از بقیه اینجا حضور دارند:
        </p>
        <div className="mt-4 grid gap-px bg-line border border-line
                        sm:grid-cols-2">
          <div className="bg-surface p-5">
            <div className="num text-[13px] text-accent mb-1">D35</div>
            <p className="m-0 text-[13.5px] leading-[1.9] text-ink-2">
              پیکره و برآوردگر هرگز در یک اجرا با هم عوض نمی‌شوند، و یک دروازه
              پس از دیدن خروجی‌اش ویرایش نمی‌شود. بعد از یک شکست، عوض‌کردن
              داده و اجرای دوباره، طبیعی‌ترین راه ساختن یک بردِ ساختگی است.
            </p>
          </div>
          <div className="bg-surface p-5">
            <div className="num text-[13px] text-accent mb-1">D36</div>
            <p className="m-0 text-[13.5px] leading-[1.9] text-ink-2">
              سازوکاری که طراحی پشتیبانی می‌کند، یک واقعیت مشاهده‌شده درباره‌ی
              بازار ایران نیست. نُه بار این مرز رد شده بود؛ حالا یک مجموعه‌ی
              آزمون مراقب بازگشتشان است و صراحتاً می‌گوید نمونه‌های تازه را
              نمی‌گیرد.
            </p>
          </div>
        </div>
      </section>

      <section className="panel">
        <p className="eyebrow">حلقه‌ی بازبینی</p>
        <p className="m-0 text-[14.5px] leading-[1.95] max-w-[64ch]
                      text-ink-2">
          هر بخش از کار برای نقد بیرونی فرستاده می‌شود، با اعداد و استدلالش، و
          با درخواست صریحِ <b className="text-ink">قوی‌ترین اعتراض</b> به‌جای
          تأیید. این حلقه یک بار نقصی واقعی را گرفت که هیچ آزمونی در این مخزن
          پیدایش نمی‌کرد؛ و یک بار هم خودش اشتباه کرد و گفتنِ آن به‌همان اندازه
          مهم بود. بازبینی‌ای که بی‌بررسی پذیرفته شود، بازبینی نیست.
        </p>
      </section>

      <section className="panel border-dashed">
        <p className="eyebrow">وضعیت فعلی، بی‌گردکردن گوشه‌ها</p>
        <ul className="m-0 ps-5 list-disc marker:text-ink-3 flex flex-col gap-2 text-[14px]
                       leading-[1.9] text-ink-2">
          <li>آداپتور باما نوشته و اجرا شده؛ دیوار نوشته شده ولی مسیر زنده‌اش
              هنوز اجرا نشده؛ شیپور و خودرو ۴۵ هنوز نوشته نشده‌اند.</li>
          <li>هیچ برآوردگری روی پیکره‌ی واقعی از دروازه‌ی پذیرش عبور نکرده،
              پس روی داده‌ی واقعی رتبه‌بندی سرو نمی‌شود.</li>
          <li>تشخیص تصادف از روی عکس هنوز ساخته نشده است. وقتی ساخته شود،
              خروجی‌اش «استنتاج‌شده» ثبت می‌شود — نه «مشاهده‌شده» — و در
              نبود قطعیت، «قابل تشخیص نیست» می‌گوید.</li>
        </ul>
      </section>

      <div className="flex gap-2 flex-wrap">
        <Link href="/how-it-works" className="btn-solid">چطور کار می‌کند</Link>
        <Link href="/contact" className="btn">تماس با ما</Link>
      </div>
    </div>
  );
}
