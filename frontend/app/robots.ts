import type { MetadataRoute } from "next";

const site = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

// /demo is not disallowed on purpose: its layout sets noindex, which crawlers only see if they can fetch it.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/dashboard", "/admin", "/auth"] },
    sitemap: `${site}/sitemap.xml`,
  };
}
