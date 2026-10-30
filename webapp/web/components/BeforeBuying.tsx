import Link from 'next/link';

/* «پیش از خرید»: what to check before paying, in seven plain steps (B1, the
   owner's choice of 2026-10-30). The text is the one the owner approved in
   docs/ACCOUNTS_AND_PAYMENT.md, word for word; the screens suite holds the
   two to one text, so a change here is a change there too. It is a statement
   about buying a car in Iran, and the owner's: nothing here is a figure, and
   nothing is said about a price. */
export const STEPS_FA = [
  'قیمت را با آگهی‌های همان مدل و همان سال مقایسه کن؛ صفحه‌ی هر مدل در کارو آگهی‌ها را از ارزان به گران نشان می‌دهد.',
  'پیش از دیدن خودرو بیعانه نده.',
  'خودرو را پیش کارشناسی ببر که فروشنده معرفی نکرده است، برای فنی و بدنه.',
  'سند و کارت خودرو را ببین و شماره‌ی شاسی و موتور را با خود خودرو تطبیق بده.',
  'خلافی، بیمه‌نامه و معاینه‌ی فنی را استعلام کن.',
  'قرارداد را بنویس، سند را در دفترخانه منتقل کن و پول را از راه بانکی بپرداز تا ردش بماند.',
  'کارو شماره‌ی فروشنده را نگه نمی‌دارد و نشان نمی‌دهد؛ با فروشنده در خود سایتی که آگهی را منتشر کرده تماس بگیر.',
];

/* The words of the first step that open the models' list. */
const TO_MODELS = 'صفحه‌ی هر مدل';

function Step({ text }: { text: string }) {
  const at = text.indexOf(TO_MODELS);
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <Link href="/models" className="text-accent underline underline-offset-4">{TO_MODELS}</Link>
      {text.slice(at + TO_MODELS.length)}
    </>
  );
}

export default function BeforeBuying() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="eyebrow">راهنما</p>
        <h1 className="m-0 text-[28px] font-bold">پیش از خرید</h1>
        <p className="mt-3 mb-0 text-[14px] text-ink-2 max-w-[62ch]">
          هفت کار، پیش از آنکه پولی بدهی.
        </p>
      </div>
      <ol className="panel m-0 flex flex-col gap-4 pr-10 [list-style-type:persian]
                     marker:text-accent marker:font-bold text-[15px] leading-[2]"
          data-steps="before-buying">
        {STEPS_FA.map((t) => (
          <li key={t} className="pr-1"><Step text={t} /></li>
        ))}
      </ol>
      <div className="flex flex-wrap gap-2">
        <Link href="/models" className="btn">خودروها</Link>
        <Link href="/search" className="btn">جست‌وجو</Link>
      </div>
    </div>
  );
}
