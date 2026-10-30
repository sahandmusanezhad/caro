/** @type {import('next').NextConfig} */

// Headers every page is served with (2026-10-30). The policy allows what the
// site uses and nothing else: its own scripts and styles -- inline as well,
// which the App Router's hydration needs -- Google Fonts' stylesheet and font
// files, images from itself and data: URLs, connections to itself (the API is
// behind the same origin), and no frame, plugin or base elsewhere. It is sent
// in production only: the development server evaluates code it is sent,
// which the policy forbids.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com data:",
  "img-src 'self' data: blob:",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join('; ');

const SECURITY_HEADERS = [
  { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=(), payment=()' },
  { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
];

const nextConfig = {
  // Which framework serves the page is nobody's business but the operator's.
  poweredByHeader: false,
  // The API is FastAPI, served beside this app. In development it runs on
  // 8000; in production nginx puts both behind one origin, so the rewrite
  // keeps the client code writing /api/... in both places.
  async rewrites() {
    return [{
      source: '/api/:path*',
      destination: `${process.env.CARO_API ?? 'http://127.0.0.1:8000'}/api/:path*`,
    }];
  },
  async headers() {
    const production = process.env.NODE_ENV === 'production';
    return [{
      source: '/:path*',
      headers: production
        ? [...SECURITY_HEADERS, { key: 'Content-Security-Policy', value: CSP }]
        : SECURITY_HEADERS,
    }];
  },
};
export default nextConfig;
