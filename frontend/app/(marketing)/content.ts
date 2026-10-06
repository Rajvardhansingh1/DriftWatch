import type { Feature } from "@/lib/features";

export const SITE = {
  name: "DriftWatch",
  tagline: "Notice when your LLM app gets quietly worse.",
  description:
    "DriftWatch is an LLM drift monitor. It scores five quality signals on a running LLM app and raises an alert when they move together. It shows that quality moved, not always why.",
};

export const HERO = {
  title: "Notice when your LLM app gets quietly worse.",
  body:
    "DriftWatch scores five quality signals on a running LLM app and raises an alert when they move together. It tells you that quality moved, not always why. The live demo needs no account.",
  primary: { label: "Create an account", href: "/auth/sign-up" },
  secondary: { label: "Open the live demo", href: "/demo" },
};

export const SIGNALS = [
  {
    name: "Embedding drift",
    text: "Turns each answer into an embedding, a vector that captures its meaning, and measures how far recent answers have moved from a baseline.",
  },
  {
    name: "Self-consistency",
    text: "Asks the same question several times and checks whether the answers still agree with each other.",
  },
  {
    name: "Canary accuracy",
    text: "Runs canary probes, a fixed set of questions with known answers, on a schedule and tracks how many come back right.",
  },
  {
    name: "Judge trend",
    text: "A second model, the LLM judge, grades a sample of answers against a rubric. DriftWatch watches the trend, not any single grade.",
  },
  {
    name: "Hallucination score",
    text: "Checks each claim against grounding context when you have it, and compares repeated samples when you don't. A word-overlap heuristic, not fact checking.",
  },
];

export const HOW_TO_STEPS: { name: string; command: string; text: string; needs: Feature[] }[] = [
  { name: "Install", command: "pip install driftwatch", text: "Install the package into the same Python environment as your app.", needs: ["cli"] },
  { name: "Link your project", command: "driftwatch init", text: "Sign in through the browser and link this folder to a DriftWatch project.", needs: ["cli"] },
  { name: "Open the dashboard", command: "driftwatch dashboard", text: "See live scores on your machine, or log in on the website to see the same data.", needs: ["cli"] },
];

export const MODES: { title: string; text: string; needs?: Feature[] }[] = [
  { title: "On your machine", text: "A small agent runs alongside your app and keeps raw prompts and responses local. Scores sync to your account.", needs: ["cli"] },
  { title: "From the web", text: "Connect a model from your dashboard and DriftWatch runs scheduled checks against it.", needs: ["cloudConnect"] },
];

export const KEYS: { title: string; text: string; needs?: Feature[] }[] = [
  { title: "Start free", text: "A small allowance on our provider key, enough to try DriftWatch on a real app.", needs: ["freeKey"] },
  { title: "Bring your own key", text: "Stored in your system keychain when you run locally, or encrypted in the cloud and never shown again.", needs: ["cli"] },
];

// Later scope. Each item shows in the "Coming soon" section until all of its
// features are listed in NEXT_PUBLIC_FEATURES; then it leaves that section and
// the matching section above (how-to, modes, keys) starts rendering instead.
export const ROADMAP: { title: string; text: string; needs: Feature[] }[] = [
  { title: "Local agent and CLI", text: "Run pip install driftwatch and driftwatch init, and a small agent watches your app whenever it runs.", needs: ["cli"] },
  { title: "Local and web dashboards in sync", text: "driftwatch dashboard on your machine, and the same live charts on this site after you log in.", needs: ["cli"] },
  { title: "Free allowance and your own keys", text: "Try it on our key with a small limit, then switch to your own provider key whenever you like.", needs: ["freeKey"] },
  { title: "Connect a model from the web", text: "Add a model from your dashboard and DriftWatch runs scheduled checks against it, with nothing to install.", needs: ["cloudConnect"] },
];

export const FAQ: { question: string; answer: string; needs?: Feature[] }[] = [
  {
    question: "What is DriftWatch?",
    answer:
      "DriftWatch is an LLM drift monitor: it watches a running LLM app for quality that drops without any error or crash. It scores five signals, including embedding drift and canary accuracy, combines them into one score and alerts when that score crosses a threshold. It shows that quality moved, though not always why.",
  },
  {
    question: "How does DriftWatch detect LLM quality regression?",
    answer:
      "It watches several signals at once instead of trusting one metric. Embedding drift shows answers changing in meaning, canary probes catch wrong answers to known questions, and an LLM judge grades a sample against a rubric. When the combined score crosses a threshold, you get an alert. The alert says something moved; finding the cause is still your job.",
  },
  {
    question: "Can DriftWatch detect LLM hallucinations?",
    answer:
      "Partly. The hallucination score checks each claim against grounding context when the app has it, and otherwise compares repeated answers to the same question for contradictions. It is a word-overlap heuristic, not fact checking. A model that gives the same wrong answer every time can pass it, so treat a clean score as weak evidence.",
  },
  {
    question: "How do I monitor my own LLM app with DriftWatch?",
    answer:
      "Install the package with pip install driftwatch, then run driftwatch init inside your project folder. It signs you in through the browser, creates a project and stores its key in your system keychain. From then on, a small background agent starts whenever your Python app runs. Run driftwatch dashboard to see it.",
    needs: ["cli"],
  },
  {
    question: "Can I see the dashboard without the command line?",
    answer:
      "Yes. Every score the local agent computes syncs to your DriftWatch account, so the same charts appear on the website after you log in. If you would rather skip the local install entirely, connect your model from the web dashboard and DriftWatch runs its scheduled checks against it from the cloud.",
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
      "Not by default. Text-based checks run on your machine, and only scores and a little metadata reach your account. The exception is the LLM judge: it sends a sample of answers to your model provider, or through our relay if you are on the free allowance, so the judge can grade them.",
    needs: ["cli"],
  },
  {
    question: "How does the live demo work?",
    answer:
      "The demo is a small question-answering bot that DriftWatch monitors in real time. Buttons such as Simulate model downgrade and Simulate prompt injection creep push it into drift, and you can watch the five signals and the combined score react. Every visitor shares the same demo, so you may see other people's runs.",
  },
  {
    question: "Is the live demo private?",
    answer:
      "No. Every visitor shares the demo, and scenarios you trigger are visible to others. Any question you type goes through the demo server to an LLM provider so the bot can answer it. Do not type anything sensitive into the demo, such as personal data, passwords or confidential company details.",
  },
  {
    question: "What can I do with a DriftWatch account today?",
    answer:
      "Today an account lets you sign up, log in and log out. It is where your projects and synced scores will live once the local agent and web dashboard ship. The live demo works without an account. There is no self-serve deletion yet, so to delete an account, email the address on the Security page.",
  },
  {
    question: "What are the limits of DriftWatch?",
    answer:
      "DriftWatch cannot prove your model is correct, and it cannot always explain why quality changed. It watches statistical signals and a sampled LLM judge, so a quiet score means nothing obvious moved, not that nothing is wrong. Treat an alert as a reason to look closer, then read real examples yourself.",
  },
];
