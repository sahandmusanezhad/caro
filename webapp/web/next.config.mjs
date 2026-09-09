/** @type {import('next').NextConfig} */
const nextConfig = {
  // The API is FastAPI, served beside this app. In development it runs on
  // 8000; in production nginx puts both behind one origin, so the rewrite
  // keeps the client code writing /api/... in both places.
  async rewrites() {
    return [{
      source: '/api/:path*',
      destination: `${process.env.CARO_API ?? 'http://127.0.0.1:8000'}/api/:path*`,
    }];
  },
};
export default nextConfig;
