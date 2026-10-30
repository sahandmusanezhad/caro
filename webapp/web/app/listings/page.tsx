import Link from 'next/link';
import SellerListings from '@/components/SellerListings';

export const metadata = { title: 'آگهی‌های ثبت‌شده در کارو — CARO' };

export default function ListingsPage() {
  return (
    <div className="flex flex-col gap-4">
      <SellerListings />
      <p className="m-0 text-[13px]">
        <Link href="/sell" className="text-accent underline underline-offset-4">خودروات را بفروش ←</Link>
      </p>
    </div>
  );
}
