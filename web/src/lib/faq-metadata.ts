export type FAQProtocol = "bisq_easy" | "multisig_v1" | "musig" | "all";

export const FAQ_PROTOCOL_OPTIONS: ReadonlyArray<{ value: FAQProtocol; label: string }> = [
  { value: "bisq_easy", label: "Bisq Easy" },
  { value: "multisig_v1", label: "Bisq 1 (Multisig)" },
  { value: "musig", label: "MuSig" },
  { value: "all", label: "All Protocols" },
];

export const FAQ_CATEGORIES: ReadonlyArray<string> = [
  "General",
  "Trading",
  "Wallet",
  "Security",
  "Reputation",
  "Payments",
  "Technical",
  "Bisq Easy",
  "Bisq 2",
  "Fees",
  "Account",
];

const CATEGORY_KEYWORDS: ReadonlyArray<{ category: string; tokens: string[]; weight: number }> = [
  {
    category: "Trading",
    tokens: ["trade", "offer", "maker", "taker", "price", "spread", "mediation", "arbitration", "settle"],
    weight: 3,
  },
  {
    category: "Wallet",
    tokens: ["wallet", "seed", "restore", "backup", "address", "txid", "transaction id", "utxo", "keys"],
    weight: 3,
  },
  {
    category: "Security",
    tokens: ["security", "scam", "phishing", "tor", "pgp", "signature", "verify", "fraud"],
    weight: 3,
  },
  {
    category: "Reputation",
    tokens: ["reputation", "profile age", "profile", "badge", "score", "burn bsq"],
    weight: 3,
  },
  {
    category: "Payments",
    tokens: ["payment", "bank", "sepa", "iban", "wise", "revolut", "zelle", "fiat", "ach"],
    weight: 3,
  },
  {
    category: "Technical",
    tokens: ["error", "crash", "install", "upgrade", "update", "version", "log", "broken", "stuck"],
    weight: 2,
  },
  {
    category: "Fees",
    tokens: ["fee", "fees", "mining fee", "network fee"],
    weight: 2,
  },
  {
    category: "Account",
    tokens: ["account", "login", "sign in", "identity", "session"],
    weight: 2,
  },
  {
    category: "Bisq Easy",
    tokens: ["bisq easy"],
    weight: 2,
  },
  {
    category: "Bisq 2",
    tokens: ["bisq 2", "bisq2"],
    weight: 2,
  },
];

function sanitizeText(value: string | null | undefined): string {
  return (value || "").toLowerCase();
}

export function detectFaqProtocol(...texts: Array<string | null | undefined>): FAQProtocol {
  const combined = texts.map(sanitizeText).join(" ");
  const hasBisq2 = combined.includes("bisq easy") || combined.includes("bisq 2") || combined.includes("bisq2");
  const hasBisq1 = combined.includes("bisq 1") || combined.includes("bisq1") || combined.includes("multisig");
  const hasMuSig = combined.includes("musig");

  if (hasMuSig && !hasBisq1 && !hasBisq2) return "musig";
  if (hasBisq1 && hasBisq2) return "all";
  if (hasBisq1) return "multisig_v1";
  if (hasBisq2) return "bisq_easy";
  return "all";
}

export function detectFaqCategory(
  question: string | null | undefined,
  answer?: string | null | undefined,
  fallbackCategory?: string | null | undefined,
): string {
  const preferred = (fallbackCategory || "").trim();
  if (preferred && preferred.toLowerCase() !== "general") return preferred;

  const combined = `${sanitizeText(question)} ${sanitizeText(answer)}`.trim();
  if (!combined) return "General";

  const scores: Record<string, number> = {};
  for (const category of FAQ_CATEGORIES) scores[category] = 0;

  for (const entry of CATEGORY_KEYWORDS) {
    for (const token of entry.tokens) {
      if (combined.includes(token)) {
        scores[entry.category] += entry.weight;
      }
    }
  }

  let bestCategory = "General";
  let bestScore = 0;
  for (const [category, score] of Object.entries(scores)) {
    if (score > bestScore) {
      bestCategory = category;
      bestScore = score;
    }
  }

  if (bestScore > 0) return bestCategory;
  return preferred || "General";
}

export function inferFaqMetadata(params: {
  question?: string | null;
  answer?: string | null;
  category?: string | null;
  protocol?: FAQProtocol | null;
}): { category: string; protocol: FAQProtocol } {
  const category = detectFaqCategory(params.question, params.answer, params.category);
  const protocol = params.protocol || detectFaqProtocol(params.question, params.answer);
  return { category, protocol };
}
