import ContactForm from '@/components/ContactForm';

export const metadata = { title: 'تماس با ما — CARO' };

export default function ContactPage() {
  return (
    <div className="flex flex-col gap-8">
      <section>
        <p className="eyebrow">تماس با ما</p>
        <h1 className="m-0 text-[28px] font-bold leading-[1.4] max-w-[24ch]">
          سؤال، ایراد، یا اعتراض به یک عدد
        </h1>
        <p className="mt-4 mb-0 text-[15px] leading-[1.95] text-ink-2
                      max-w-[60ch]">
          اگر جایی از سامانه عددی نشان داده که فکر می‌کنی از شواهدش جلو زده،
          همان را بنویس — این نوع پیام از همه مفیدتر است. شماره‌ی پیگیری‌ای که
          می‌گیری، همان چیزی است که در پاسخ به آن ارجاع می‌دهیم.
        </p>
      </section>

      <ContactForm />

      <section className="panel border-dashed">
        <p className="eyebrow">با پیامت چه می‌کنیم</p>
        <ul className="m-0 ps-5 list-disc marker:text-ink-3 flex flex-col gap-2 text-[13.5px]
                       leading-[1.9] text-ink-2">
          <li>
            در یک فایل فقط-افزودنی روی همین سرور ذخیره می‌شود و از مخزن کد
            بیرون است.
          </li>
          <li>
            هیچ ربطی به پیکره‌ی داده ندارد و هرگز وارد آن نمی‌شود؛ آن دو، دو
            چرخه‌ی عمر جدا دارند.
          </li>
          <li>
            صندوق پیام‌ها فقط با توکن مدیریت باز می‌شود، و اگر توکنی تنظیم
            نشده باشد اصلاً باز نمی‌شود.
          </li>
        </ul>
      </section>
    </div>
  );
}
