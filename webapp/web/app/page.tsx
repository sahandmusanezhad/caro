import Link from 'next/link';
import SearchBox from '@/components/SearchBox';

/* The landing page.
 *
 * Every claim here is about the SYSTEM — what it computes, what it refuses,
 * what it records — and none is about the Iranian used-car market. That line
 * is D36 and it has been crossed nine times in this project's history, always
 * in prose, always in a place like this one. A sentence such as "used 206s are
 * overpriced in Tehran" would be a market fact this repository has no evidence
 * for; "CARO subtracts an expected damage cost from every opportunity figure"
 * is a description of code that can be checked.
 */

const PILLARS = [
  {
    n: '۰۱',
    t: 'یک جمله، نه یک فرم',
    b: 'پرسش را به فارسی می‌نویسی. CARO کاربرد، بودجه، سقف کارکرد، خط قرمزها '
      + 'و پروفایل ریسک را از همان جمله بیرون می‌کشد و — این مهم‌تر است — هرچه '
      + 'را نفهمیده باشد جدا نشان می‌دهد.',
  },
  {
    n: '۰۲',
    t: '«بهترین» یک تابع است، نه یک نظر',
    b: 'رتبه‌بندی حاصل شش وزن است: صرفه، ریسک، هزینه‌ی نگهداری، نقدشوندگی، '
      + 'کارکرد و تازگی. وزن‌ها روی صفحه‌اند و می‌توانی تغییرشان بدهی؛ ترتیب '
      + 'جلوی چشمت عوض می‌شود.',
  },
  {
    n: '۰۳',
    t: 'ریسک از قیمت کم می‌شود، نه در آن ضرب',
    b: 'صرفه = برآورد − قیمت پیشنهادی − هزینه‌ی انتظاری خسارت. هر سه به تومان‌اند '
      + 'و هر سه جدا نمایش داده می‌شوند، چون عددی که نتوانی اجزایش را ببینی، '
      + 'عددی است که نمی‌توانی ردش کنی.',
  },
  {
    n: '۰۴',
    t: 'وقتی شواهد کافی نیست، توصیه‌ای در کار نیست',
    b: 'اگر برآوردگر روی این پیکره از دروازه‌ی پذیرش عبور نکرده باشد، CARO '
      + 'رتبه‌بندی را سرو نمی‌کند. شواهد را نشان می‌دهد و می‌گوید چرا ساکت است. '
      + 'این حالت یک خطا نیست؛ یک حالت محصول است.',
  },
];

/* Source status, stated as it actually is in `caro/ingest/`. A landing page
   listing four logos as if four pipelines existed would be the same class of
   overclaim the design record spends forty entries preventing. */
const SOURCES = [
  {
    name: 'باما',
    host: 'bama.ir',
    state: 'آداپتور نوشته و اجرا شده',
    tone: 'good',
    note: 'مسیر مرورگر، با تأخیر ادب‌مندانه و احترام به robots.txt',
  },
  {
    name: 'دیوار',
    host: 'divar.ir',
    state: 'آداپتور نوشته، مسیر زنده اجرا نشده',
    tone: 'warn',
    note: 'استخراج فیلدها و نرمال‌سازی فارسی آماده است',
  },
  {
    name: 'شیپور',
    host: 'sheypoor.com',
    state: 'هنوز نوشته نشده',
    tone: 'muted',
    note: '—',
  },
  {
    name: 'خودرو ۴۵',
    host: 'khodro45.com',
    state: 'هنوز نوشته نشده',
    tone: 'muted',
    note: '—',
  },
];

const TONE: Record<string, string> = {
  good: 'text-good border-good bg-good-soft',
  warn: 'text-warn border-warn bg-warn-soft',
  muted: 'text-ink-3 border-line bg-sunk',
};

export default function Home() {
  return (
    <div className="flex flex-col gap-12">

      {/* ---------------------------------------------------------------- */}
      <section>
        <p className="eyebrow">CARO · تصمیم‌یار خرید خودروی کارکرده</p>
        <h1 className="text-[30px] sm:text-[38px] font-bold leading-[1.35]
                       m-0 max-w-[22ch] text-balance">
          ارزان‌ترین آگهی، بهترین معامله نیست.
        </h1>
        <p className="mt-4 mb-7 text-[17px] leading-[1.9] max-w-[58ch]
                      text-ink-2">
          CARO آگهی‌ها را مرتب نمی‌کند؛ درباره‌شان تصمیم می‌گیرد — و هر عددی
          که نشان می‌دهد همراه با <em className="not-italic font-bold text-accent">
          درجه‌ی شواهدی</em> است که پشتش ایستاده. جایی که شواهد کم بیاورد، سکوت
          می‌کند و می‌گوید چرا.
        </p>

        <SearchBox autoFocus />
      </section>

      {/* ---------------------------------------------------------------- */}
      <section>
        <p className="eyebrow">چه چیزی این را از یک فیلتر جدا می‌کند</p>
        <div className="grid gap-px bg-line border border-line
                        sm:grid-cols-2">
          {PILLARS.map((p) => (
            <article key={p.n} className="bg-surface p-6">
              <span className="num text-[12px] text-ink-3">{p.n}</span>
              <h2 className="text-[17px] font-medium mt-1 mb-2 leading-8">
                {p.t}
              </h2>
              <p className="m-0 text-[14px] text-ink-2 leading-[1.95]">{p.b}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------------- */}
      <section>
        <p className="eyebrow">منابع داده — وضعیت واقعی، نه فهرست آرزوها</p>
        <div className="border border-line bg-surface rounded-[3px]
                        overflow-x-auto">
          <table className="w-full border-collapse text-[13.5px] min-w-[560px]">
            <thead>
              <tr className="text-ink-3 text-[12px]">
                <th className="text-right font-normal px-4 py-2.5 border-b
                               border-line">منبع</th>
                <th className="text-right font-normal px-4 py-2.5 border-b
                               border-line">دامنه</th>
                <th className="text-right font-normal px-4 py-2.5 border-b
                               border-line">وضعیت</th>
                <th className="text-right font-normal px-4 py-2.5 border-b
                               border-line">توضیح</th>
              </tr>
            </thead>
            <tbody>
              {SOURCES.map((s) => (
                <tr key={s.host} className="align-top">
                  <td className="px-4 py-3 border-b border-line font-medium">
                    {s.name}
                  </td>
                  <td className="px-4 py-3 border-b border-line num
                                 text-[12px] text-ink-3">{s.host}</td>
                  <td className="px-4 py-3 border-b border-line">
                    <span className={`chip ${TONE[s.tone]} !font-fa
                                      !text-[11.5px] !normal-case
                                      !tracking-normal`}
                          style={{ direction: 'rtl' }}>
                      {s.state}
                    </span>
                  </td>
                  <td className="px-4 py-3 border-b border-line text-ink-2">
                    {s.note}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-[12.5px] text-ink-3 leading-7 max-w-[70ch]">
          هیچ‌جای این سامانه دور زدن ضدربات، حل کپچا یا چرخاندن حساب انجام
          نمی‌شود. اگر منبعی ما را ببندد، ثبت می‌کنیم و می‌ایستیم. شماره‌ی
          تماس فروشنده هم هرگز ذخیره یا نمایش داده نمی‌شود — نگهبان محتوا روی
          خودِ فایل منتشرشده اجرا می‌شود، نه روی شیء در حافظه.
        </p>
      </section>

      {/* ---------------------------------------------------------------- */}
      <section className="panel border-r-2 border-r-accent">
        <p className="eyebrow">قاعده‌ای که بقیه‌ی سامانه از آن می‌آید</p>
        <p className="text-[17px] leading-[1.9] m-0 max-w-[62ch]">
          یک ادعا هرگز از شواهدش جلو نمی‌زند. برآوردگری که روی یک پیکره سنجیده
          نشده باشد، روی همان پیکره سرو نمی‌شود — حتی اگر خطای کلی‌اش عالی به
          نظر برسد، چون خطای کلی چیزی درباره‌ی اعتبار یک برآورد
          <span className="text-accent font-medium"> شرطی</span> نمی‌گوید.
        </p>
        <div className="mt-5 flex gap-2 flex-wrap">
          <Link href="/how-it-works" className="btn">چطور کار می‌کند</Link>
          <Link href="/search?q=%DB%B2%DB%B0%DB%B6" className="btn">
            یک جست‌وجوی نمونه
          </Link>
        </div>
      </section>

    </div>
  );
}
