const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const apiUrl = process.env.NEXT_PUBLIC_MONITOR_API_URL || "";
const wss = supabaseUrl.replace(/^https:/, "wss:");

// Public pages are static and take no user input. App routes (/dashboard,
// /admin, /auth) get a stricter nonce-based CSP from middleware.ts instead.
const publicCsp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self' ${apiUrl} ${supabaseUrl} ${wss}`.trim(),
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const baseHeaders = [
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "X-Frame-Options", value: "DENY" },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  async headers() {
    return [
      { source: "/:path*", headers: baseHeaders },
      {
        source: "/((?!(?:dashboard|admin|auth)(?:/|$)).*)",
        headers: [{ key: "Content-Security-Policy", value: publicCsp }],
      },
    ];
  },
};

module.exports = nextConfig;
