import type { Feature } from "@/lib/features";

export const SITE = {
  name: "DriftWatch",
  tagline: "Notice when your LLM app quietly gets worse.",
  description:
    "DriftWatch scores five signals on a live LLM app and flags the moment they move together. It tells you that quality shifted, not always why.",
};

export const HERO = {
  title: "Notice when your LLM app quietly gets worse.",
  body:
    "DriftWatch scores five signals on your live traffic and flags the moment they move together. It tells you that quality shifted, not always why.",
  primary: { label: "Create an account", href: "/auth/sign-up" },
  secondary: { label: "Open the live demo", href: "/demo" },
};

export const SIGNALS = [
  { name: "Embedding drift", text: "Compares recent answers to a baseline and measures how far their meaning has moved." },
  { name: "Self-consistency", text: "Asks the same question more than once and checks whether the answers agree." },
  { name: "Canary accuracy", text: "Runs a fixed set of questions with known answers on a schedule." },
  { name: "Judge trend", text: "A second model grades a sample of answers against a rubric. We watch the trend, not single grades." },
  { name: "Hallucination score", text: "Looks for answers that disagree with themselves across samples. A heuristic, not fact checking." },
];

export const HOW_TO_STEPS: { name: string; command: string; text: string; needs: Feature[] }[] = [
  { name: "Install", command: "pip install driftwatch", text: "Install the package into the same environment as your app.", needs: ["cli"] },
  { name: "Link your project", command: "driftwatch init", text: "Sign in through the browser and link this folder to a DriftWatch project.", needs: ["cli"] },
  { name: "Open the dashboard", command: "driftwatch dashboard", text: "See live scores on your machine, or log in on the website to see the same data.", needs: ["cli"] },
];

export const MODES: { title: string; text: string; needs?: Feature[] }[] = [
  { title: "On your machine", text: "A small agent runs while your app runs and keeps raw text local. Scores sync to your account.", needs: ["cli"] },
  { title: "From the web", text: "Connect a model from your dashboard and DriftWatch runs scheduled checks against it.", needs: ["cloudConnect"] },
];

export const KEYS: { title: string; text: string; needs?: Feature[] }[] = [
  { title: "Start free", text: "A small allowance on our key so you can try it on a real app.", needs: ["freeKey"] },
  { title: "Bring your own key", text: "Kept in your system keychain on your machine, or encrypted and never shown again in the cloud.", needs: ["cli"] },
];

// Later scope. Each item shows in the "Coming soon" section until all of its
// features are listed in NEXT_PUBLIC_FEATURES; then it leaves that section and
// the matching section above (how-to, modes, keys) starts rendering instead.
export const ROADMAP: { title: string; text: string; needs: Feature[] }[] = [
  { title: "Local agent and CLI", text: "pip install driftwatch, run driftwatch init, and a small agent watches your app whenever it runs.", needs: ["cli"] },
  { title: "Local and web dashboards in sync", text: "driftwatch dashboard on your machine, and the same live charts on this site after you log in.", needs: ["cli"] },
  { title: "Free allowance and your own keys", text: "Try it on our key with a small limit, then switch to your own provider key at any time.", needs: ["freeKey"] },
  { title: "Connect a model from the web", text: "Add a model from your dashboard and DriftWatch runs scheduled checks against it, no install needed.", needs: ["cloudConnect"] },
];

export const FAQ: { question: string; answer: string; needs?: Feature[] }[] = [
  {
    question: "What is DriftWatch?",
    answer:
      "DriftWatch is a monitoring tool that watches a live LLM app for silent quality drift. It scores five signals on your real traffic, such as embedding drift and canary accuracy, combines them into one score, and flags you when that score crosses your threshold. It tells you that quality moved, not always why.",
  },
  {
    question: "How do I start monitoring my app locally?",
    answer:
      "Install the package with pip install driftwatch, then run driftwatch init inside your project folder. It signs you in through the browser, creates a project and stores its key in your system keychain. From then on, a small background agent starts whenever your Python app runs. Run driftwatch dashboard to see it.",
    needs: ["cli"],
  },
  {
    question: "Can I watch the dashboard without the command line?",
    answer:
      "Yes. Every score the local agent computes is synced to your DriftWatch account, so the same charts appear on the website after you log in. If you would rather skip the local install entirely, connect your model from the web dashboard and DriftWatch runs its scheduled checks against it from the cloud.",
    needs: ["cli", "cloudConnect"],
  },
  {
    question: "Who pays for the LLM calls DriftWatch makes?",
    answer:
      "Each account gets a small free allowance on our key, enough to try DriftWatch on a real app. After that, add your own provider key. Locally it stays in your system keychain and never leaves your machine. If you connect a model from the cloud, the key is encrypted and never shown again.",
    needs: ["freeKey"],
  },
  {
    question: "Does DriftWatch send my prompts and responses to the cloud?",
    answer:
      "No, not by default. Text-based checks run on your machine, and only scores and small bits of metadata reach your account. The one exception is the LLM judge: it sends a sample to the model provider you use, or through our relay if you are on the free allowance.",
    needs: ["cli"],
  },
  {
    question: "How does the live demo work?",
    answer:
      "The demo runs a small question-answering bot that DriftWatch monitors in real time. Buttons let you push it into drift, for example by swapping to a weaker model or slipping in prompt injection, and you can watch the five signals and the combined score react. Every visitor shares the same demo.",
  },
  {
    question: "What can I do with an account today?",
    answer:
      "Today an account lets you sign in, keep a verified email on file, and be first in line as the local agent and web dashboard ship. Your account is where synced scores and project keys will live. You can delete it at any time from the data deletion page.",
  },
  {
    question: "What does DriftWatch not do?",
    answer:
      "It does not prove your model is correct, and it cannot always explain why quality changed. It watches statistical signals and a sampled judge, so a quiet score means nothing obvious moved, not that nothing is wrong. Treat an alert as a reason to look closer, then check real examples yourself.",
  },
];
