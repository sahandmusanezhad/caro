import Link from 'next/link';

export const metadata = { title: 'چطور کار می‌کند — CARO' };

/* The page a reviewer reads before deciding whether to trust anything else on
   the site. Every statement here describes code in this repository. Where a
   capability does not exist yet, it says so — a walkthrough that describes the
   intended system rather than the built one is the most expensive kind of
   documentation, because it is believed. */

const LAYERS = [
  {
    id: 'W4',
    fa: 'گردآوری',
    what: 'آگهی‌ها از منبع خوانده می‌شوند و به فیلدهای ساخت‌یافته تبدیل می‌شوند: '
      + 'قیمت، کارکرد، سال شمسی، گیربکس، سوخت، وضعیت بدنه، مشکل سند.',
    detail: 'نرمال‌سازی فارسی اینجاست — ارقام فارسی و عربی به لاتین، «ي» و «ك» '
      + 'عربی به فارسی، نیم‌فاصله به فاصله — چون «۱۲۰٬۰۰۰ کیلومتر» و '
      + '«120000 کیلومتر» یک عدد‌اند. قیمت با دو مسیر مستقل خوانده می‌شود و '
      + 'اگر با هم نخوانند، آگهی مشکوک علامت می‌خورد.',
  },
  {
    id: 'W0',
    fa: 'رصد',
    what: 'همان آگهی در طول زمان دنبال می‌شود: تغییر قیمت، حذف، و انتشار مجدد '
      + 'با شناسه‌ی تازه.',
    detail: 'آگهی حذف‌شده لزوماً فروخته‌نشده نیست و این تفاوت، سوگیری سانسور '
      + 'است. آگهی‌های تکراری در یک خوشه جمع می‌شوند تا یک ماشین، چند بار در '
      + 'آموزش شمرده نشود.',
  },
  {
    id: 'W1',
    fa: 'ارزش‌گذاری',
    what: 'برآورد قیمت با ادغام جزئی (partial pooling): تیپ‌های کم‌داده به سمت '
      + 'میانه‌ی خانواده‌ی خود جمع می‌شوند به‌جای آن‌که از چند آگهی، یک قانون '
      + 'ساخته شود.',
    detail: 'و مهم‌تر: یک دروازه‌ی پذیرش. اگر برآوردگر روی برش‌های نگه‌داشته‌شده '
      + 'قابل‌قضاوت نباشد، سرو نمی‌شود. خطای کلیِ خوب، اعتبار یک برآورد شرطی '
      + 'را ثابت نمی‌کند؛ این دقیقاً همان استنتاجی است که سامانه اجازه‌اش را '
      + 'نمی‌دهد.',
  },
  {
    id: 'W3',
    fa: 'رتبه‌بندی',
    what: 'جمله‌ی فارسی به قصد تبدیل می‌شود، قصد به نامزدها، و نامزدها به یک '
      + 'فهرست کوتاه با نقش‌های متفاوت.',
    detail: 'اگر هیچ آگهی‌ای با قیدها جور نشود، قیدها پله‌پله شل می‌شوند و '
      + 'گفته می‌شود کدام و چقدر. فهرست کوتاه عمداً متنوع است: «امن‌ترین '
      + 'گزینه» و «بیشترین صرفه» دو ادعای متفاوت‌اند و خریدار باید هر دو را '
      + 'ببیند.',
  },
  {
    id: 'W2',
    fa: 'عامل‌ها و دفتر شواهد',
    what: 'هر ادعا در یک دفتر ثبت می‌شود با درجه‌ی شواهدش: مشاهده‌شده، '
      + 'استخراج‌شده، یا استنتاج‌شده.',
    detail: 'یک داور جبری هم هست که با آن نمی‌شود بحث کرد: بازبینی که بشود '
      + 'قانعش کرد، بازبینی نیست.',
  },
];

export default function HowItWorks() {
  return (
    <div className="flex flex-col gap-10">
      <section>
        <p className="eyebrow">چطور کار می‌کند</p>
        <h1 className="m-0 text-[30px] font-bold leading-[1.4] max-w-[24ch]">
          پنج لایه، و یک قاعده که همه‌شان از آن پیروی می‌کنند
        </h1>
        <p className="mt-4 mb-0 text-[16px] leading-[1.95] text-ink-2
                      max-w-[62ch]">
          جهت وابستگی یک‌طرفه است: گردآوری ← رصد ← ارزش‌گذاری ← رتبه‌بندی ←
          عامل‌ها. هیچ لایه‌ای به لایه‌ی بالادست خود دست نمی‌زند، و به همین دلیل
          می‌شود یکی را عوض کرد بی‌آن‌که بقیه بی‌صدا معنایشان تغییر کند.
        </p>
      </section>

      <section>
        <div className="flex flex-col gap-px bg-line border border-line">
          {LAYERS.map((l) => (
            <article key={l.id} className="bg-surface p-6 grid gap-4
                                           sm:grid-cols-[5rem_1fr]">
              <div>
                <div className="num text-[20px] font-medium text-accent">
                  {l.id}
                </div>
                <div className="text-[13px] text-ink-3">{l.fa}</div>
              </div>
              <div>
                <p className="m-0 text-[15px] leading-[1.95]">{l.what}</p>
                <p className="m-0 mt-2 text-[13.5px] leading-[1.95]
                              text-ink-2">{l.detail}</p>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <p className="eyebrow">حساب اصلی</p>
        <p className="num text-[17px] m-0 leading-[2]" dir="ltr">
          value = estimate − asking_price − risk_discount
        </p>
        <p className="mt-4 mb-0 text-[14.5px] leading-[1.95] text-ink-2
                      max-w-[64ch]">
          هر سه جمله به تومان‌اند. ریسک <b className="text-ink">کم می‌شود</b>،
          نه اینکه در امتیاز ضرب یا نرمال شود — چون یک ماشین تصادفی، ضریبی روی
          مطلوبیت نیست؛ یک هزینه‌ی انتظاری به تومان است، و وقتی به تومان نوشته
          شود می‌شود درباره‌اش بحث کرد. هزینه‌ی انتظاری خسارت با برآورد رشد
          می‌کند: همان درصد ریسک روی ماشین گران‌تر، تومان بیشتری می‌بلعد.
        </p>
      </section>

      <section className="panel border-r-2 border-r-bad">
        <p className="eyebrow">جایی که سامانه ساکت می‌شود</p>
        <p className="m-0 text-[15px] leading-[1.95] max-w-[64ch]">
          روی هیچ پیکره‌ی واقعی‌ای تا امروز برآوردگری از دروازه‌ی پذیرش عبور
          نکرده است. نتیجه این است که روی داده‌ی واقعی، CARO فهرست کوتاه
          نمی‌دهد — شواهد را نشان می‌دهد و می‌گوید چرا رتبه‌بندی نمی‌کند.
        </p>
        <p className="m-0 mt-3 text-[13.5px] leading-[1.95] text-ink-2
                      max-w-[64ch]">
          پیکره‌ی ساختگی که در دموی این سایت سرو می‌شود، کد واقعی و رتبه‌بندی
          واقعی را اجرا می‌کند و چون قیمت درستِ هر خودرو در آن معلوم است،
          دروازه عبور می‌کند. برچسب SYNTHETIC روی همه‌ی صفحه‌ها همین را
          می‌گوید: رفتار سامانه را می‌بینی، نه بازار ایران را.
        </p>
      </section>

      <section className="panel">
        <p className="eyebrow">حریم خصوصی و ادب اسکرپینگ</p>
        <ul className="m-0 ps-5 list-disc marker:text-ink-3 flex flex-col gap-2 text-[14px]
                       leading-[1.9] text-ink-2">
          <li>
            شماره‌ی تماس فروشنده هرگز ذخیره یا نمایش داده نمی‌شود. پیش از
            انتشار، شناسه‌های تماس حذف می‌شوند و <b className="text-ink">بعد</b>
            {' '}عدد کارکرد از باقی‌مانده خوانده می‌شود — ترتیب برعکس، راهی است
            برای آنکه رقم‌های یک شماره تلفن به‌عنوان کارکرد جا بزنند.
          </li>
          <li>
            پیکره‌ی منتشرشده هیچ متن نوشته‌شده به‌دست فروشنده را حمل نمی‌کند.
            دو نگهبان این را تضمین می‌کنند: یکی روی نام کلیدها، دیگری روی
            <b className="text-ink"> خودِ بایت‌های فایل نهایی</b> — چون نگهبانی
            که فقط شیء در حافظه را ببیند، با تغییر نام یک فیلد دور زده می‌شود.
          </li>
          <li>
            هیچ دور زدن ضدربات، حل کپچا، چرخاندن حساب یا کار با کد پیامکی
            انجام نمی‌شود. اگر منبعی ببندد، ثبت می‌شود و کار متوقف می‌شود.
          </li>
        </ul>
      </section>

      <div className="flex gap-2 flex-wrap">
        <Link href="/search?q=%DB%B2%DB%B0%DB%B6%20%D8%B2%DB%8C%D8%B1%20%DB%B8%DB%B0%DB%B0%20%D9%85%DB%8C%D9%84%DB%8C%D9%88%D9%86"
              className="btn-solid">یک جست‌وجوی واقعی را ببین</Link>
        <Link href="/about" className="btn">درباره‌ی این پروژه</Link>
      </div>
    </div>
  );
}
