'use client';

/* Error reports from the browser (docs/REARCHITECTURE.md, phase 0).
 *
 * Off unless NEXT_PUBLIC_SENTRY_DSN was set when the site was built: the
 * value is written into the bundle then, so without it this renders nothing
 * and fetches nothing -- the SDK is a chunk of its own, asked for only where
 * reports are on.
 *
 * With it, the SDK sends its envelopes to the site's own origin, /api/report,
 * where the API cleans each event with the same rule as its own and
 * forwards it (webapp/api/observability.py). Two reasons, both the site's:
 * its policy lets a browser connect to its own origin and to nothing else,
 * and what a report may carry is a rule written once, in Python, not again
 * here. */
import { useEffect } from 'react';

const DSN = process.env.NEXT_PUBLIC_SENTRY_DSN;

export default function ErrorReports() {
  useEffect(() => {
    if (!DSN) return;
    import('@sentry/browser')
      .then((Sentry) => {
        Sentry.init({
          dsn: DSN,
          tunnel: '/api/report',
          // Nothing about the person is collected here either: no user, no
          // cookie, no header, no body, no query. The API takes out what an
          // event still carries; this keeps it from being put in.
          dataCollection: {
            userInfo: false,
            cookies: false,
            httpHeaders: false,
            httpBodies: [],
            urlQueryParams: false,
          },
          tracesSampleRate: 0,
        });
      })
      // A report that cannot start is no reason for the page not to.
      .catch(() => undefined);
  }, []);
  return null;
}
