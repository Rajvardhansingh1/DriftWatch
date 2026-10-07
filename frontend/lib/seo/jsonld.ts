import { FAQ, HOW_TO_STEPS, SITE } from "@/app/(marketing)/content";
import { type Feature, isLive } from "@/lib/features";

// Structured data mirrors visible content exactly and describes only live
// features, so search and answer engines are never told something false.
export function buildLd(on: Set<Feature>, siteUrl: string): object[] {
  const ld: object[] = [
    {
      "@context": "https://schema.org",
      "@type": "SoftwareApplication",
      name: SITE.name,
      description: SITE.description,
      applicationCategory: "DeveloperApplication",
      operatingSystem: on.has("cli") ? "Windows, macOS, Linux" : "Web",
      url: siteUrl,
    },
    { "@context": "https://schema.org", "@type": "Organization", name: SITE.name, url: siteUrl },
    {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: FAQ.filter((f) => isLive(f, on)).map((f) => ({
        "@type": "Question",
        name: f.question,
        acceptedAnswer: { "@type": "Answer", text: f.answer },
      })),
    },
  ];
  if (HOW_TO_STEPS.every((s) => isLive(s, on))) {
    ld.push({
      "@context": "https://schema.org",
      "@type": "HowTo",
      name: "Start monitoring an LLM app with DriftWatch",
      step: HOW_TO_STEPS.map((s, i) => ({
        "@type": "HowToStep",
        position: i + 1,
        name: s.name,
        text: `${s.text} Run: ${s.command}`,
      })),
    });
  }
  return ld;
}

// JSON-LD goes into a <script> tag; escape the characters that could close it.
export function serializeLd(data: object): string {
  return JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026");
}
