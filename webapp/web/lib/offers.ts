/* How a model's page orders and narrows its listings. Pure, so the screens
   suite can call them; the page holds only which one is chosen.

   The API sends the listings priced cheapest first and the rest after, and it
   is the one that knows which prices are usable, so «cheapest» is its order,
   untouched. The other two keep that order wherever they cannot tell two
   listings apart, so a tie still reads cheapest first. */
import type { EvidenceItem } from '@/lib/api';

export type OfferSort = 'price' | 'year' | 'mileage';

type Offer = Pick<EvidenceItem, 'year_jalali' | 'mileage_km' | 'mileage_status'>;

/** An odometer the gate does not doubt: graded plausible, or not graded at
 *  all (an appraisal row, whose odometer eligibility already checked). A
 *  suspicious or impossible figure is not «the least driven». */
function trusted(o: Offer): boolean {
  return o.mileage_km != null && (o.mileage_status == null || o.mileage_status === 'plausible');
}

export function sortOffers<T extends Offer>(offers: T[], by: OfferSort): T[] {
  const at = new Map(offers.map((o, i) => [o, i] as const));
  const tie = (a: T, b: T) => (at.get(a) as number) - (at.get(b) as number);
  const out = [...offers];
  if (by === 'year') {
    out.sort((a, b) => {
      if (a.year_jalali == null || b.year_jalali == null) {
        return (a.year_jalali == null ? 1 : 0) - (b.year_jalali == null ? 1 : 0) || tie(a, b);
      }
      return b.year_jalali - a.year_jalali || tie(a, b);
    });
  } else if (by === 'mileage') {
    out.sort((a, b) => {
      const ta = trusted(a), tb = trusted(b);
      if (ta !== tb) return ta ? -1 : 1;
      if (!ta) return tie(a, b);
      return (a.mileage_km as number) - (b.mileage_km as number) || tie(a, b);
    });
  }
  return out;
}

/** The listings of one year, in the order given; every listing for none. */
export function offersOfYear<T extends Offer>(offers: T[], year: number | null): T[] {
  return year == null ? offers : offers.filter((o) => o.year_jalali === year);
}
