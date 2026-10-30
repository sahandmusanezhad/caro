/* The site's nav, in one place.
 *
 * «آگهی فروشنده‌ها» and «ثبت آگهی» lead to the listings sellers post on CARO
 * itself, which need a store the deploy holder sets up (docs/SELLER_LISTINGS.md).
 * The owner chose on 2026-10-30 to keep them out of the nav until then: they
 * appear where NEXT_PUBLIC_SELLER_LISTINGS is «on» when the site is built.
 * The pages stay at their addresses and say the deployment takes no listings
 * where the store is off. */

export interface NavItem { href: string; fa: string }

export function navItems(sellerListings: string | undefined): NavItem[] {
  const seller = sellerListings === 'on'
    ? [{ href: '/listings', fa: 'آگهی فروشنده‌ها' }, { href: '/sell', fa: 'ثبت آگهی' }]
    : [];
  return [
    { href: '/', fa: 'خانه' },
    { href: '/search', fa: 'جست‌وجو' },
    { href: '/models', fa: 'خودروها' },
    { href: '/compare', fa: 'مقایسه' },
    { href: '/saved', fa: 'نشان‌شده‌ها' },
    ...seller,
    { href: '/how-it-works', fa: 'چطور کار می‌کند' },
    { href: '/about', fa: 'درباره‌ی ما' },
    { href: '/contact', fa: 'تماس با ما' },
  ];
}
