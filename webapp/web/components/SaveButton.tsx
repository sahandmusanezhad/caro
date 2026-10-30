'use client';

import { useEffect, useState } from 'react';
import { isSaved, onSavedChange, toggleSaved } from '@/lib/saved';

/* «نشان کن»: keeps a listing in this browser (lib/saved.ts). Rendered unsaved
   on the server and on the first paint, and read after: storage exists only
   in the browser, and a mismatch between the two renders is a React error. */
export default function SaveButton({ id, compact = false }: { id: string; compact?: boolean }) {
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    const sync = () => setSaved(isSaved(id));
    sync();
    return onSavedChange(sync);
  }, [id]);
  return (
    <button
      type="button"
      onClick={() => setSaved(toggleSaved(id))}
      aria-pressed={saved}
      title={saved ? 'برداشتن از نشان‌شده‌ها' : 'نگه داشتن در نشان‌شده‌ها، فقط در همین مرورگر'}
      className={`btn ${compact ? 'px-3 py-1 text-[12.5px]' : ''} ${saved ? '!bg-accent !text-white' : ''}`}
    >
      {saved ? '★ نشان‌شده' : '☆ نشان کن'}
    </button>
  );
}
