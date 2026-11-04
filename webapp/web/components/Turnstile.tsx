'use client';

import { useEffect, useRef } from 'react';

/* Cloudflare Turnstile, the «ربات نیستم» check (webapp/api/turnstile.py).
 * Drawn only where NEXT_PUBLIC_TURNSTILE_SITE_KEY was set when the site was
 * built; without it nothing is drawn, nothing is loaded, and the forms send
 * no token -- which the API asks for only where its secret is set. The token
 * is good once: a form hands it on with what it sends, and asks for a new
 * one (`reset`) after every answer. */

export const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? '';
const SCRIPT = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';

type Widget = {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string;
  reset: (id: string) => void;
  remove: (id: string) => void;
};

declare global {
  interface Window { turnstile?: Widget }
}

let loading: Promise<Widget | null> | null = null;

function load(): Promise<Widget | null> {
  if (typeof window === 'undefined') return Promise.resolve(null);
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (!loading) {
    loading = new Promise((resolve) => {
      const s = document.createElement('script');
      s.src = SCRIPT;
      s.async = true;
      s.onload = () => resolve(window.turnstile ?? null);
      s.onerror = () => { loading = null; resolve(null); };
      document.head.appendChild(s);
    });
  }
  return loading;
}

export default function Turnstile({ onToken, resetKey }: { onToken: (token: string) => void; resetKey: number }) {
  const box = useRef<HTMLDivElement>(null);
  const id = useRef<string | null>(null);
  const handler = useRef(onToken);
  handler.current = onToken;

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY) return;
    let gone = false;
    load().then((t) => {
      if (gone || !t || !box.current || id.current) return;
      id.current = t.render(box.current, {
        sitekey: TURNSTILE_SITE_KEY,
        language: 'fa',
        callback: (token: string) => handler.current(token),
        'expired-callback': () => handler.current(''),
        'error-callback': () => handler.current(''),
      });
    });
    return () => {
      gone = true;
      if (id.current && window.turnstile) window.turnstile.remove(id.current);
      id.current = null;
    };
  }, []);

  useEffect(() => {
    if (resetKey > 0 && id.current && window.turnstile) {
      window.turnstile.reset(id.current);
      handler.current('');
    }
  }, [resetKey]);

  if (!TURNSTILE_SITE_KEY) return null;
  return <div ref={box} className="min-h-[65px]" data-turnstile="" />;
}
