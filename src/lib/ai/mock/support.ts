import { helpArticles, type HelpArticle } from "@/content/support/articles";
import type { SupportAskRequest, SupportReply } from "../contracts";
import { mockGate, streamText, type StreamOptions } from "./controls";

/**
 * Demo "RAG-lite": keyword scoring over the local help set only. Sources are always real
 * articles from that set; nothing is invented. No match → "I'm not sure".
 */
const STOP = new Set(["the", "a", "an", "i", "my", "is", "are", "do", "does", "to", "how", "can", "of", "in", "on", "it", "and", "or", "with", "for", "what", "why", "me", "you", "this", "that", "be", "with"]);

export function tokens(text: string) {
  return text.toLowerCase().replace(/[^a-z0-9.'-]+/g, " ").split(" ").map((t) => t.replace(/^'+|'+$/g, "")).filter((t) => t && !STOP.has(t));
}

export function scoreArticles(question: string): { article: HelpArticle; score: number }[] {
  const words = new Set(tokens(question));
  return helpArticles
    .map((article) => {
      let score = 0;
      for (const keyword of article.keywords) if (words.has(keyword)) score += 1;
      for (const word of tokens(article.title)) if (words.has(word)) score += 0.5;
      return { article, score };
    })
    .filter((match) => match.score >= 1)
    .sort((a, b) => b.score - a.score);
}

const snippet = (body: string) => (body.length > 140 ? `${body.slice(0, 137).trimEnd()}…` : body);

export async function mockSupportAsk(request: SupportAskRequest, options: StreamOptions = {}): Promise<SupportReply> {
  const gate = await mockGate(options.signal);
  if (gate === "unavailable") {
    return { status: "unavailable", answer: "", sources: [], escalation: null, source: "unavailable" };
  }
  if (gate === "empty") return { status: "answered", answer: "", sources: [], escalation: null, source: "demo" };
  const matches = scoreArticles(request.question);
  if (!matches.length) {
    const answer = "I'm not sure about that one, and I'd rather not guess. Try one of the suggested questions, or rephrase with the page or feature you're asking about.";
    await streamText(answer, options);
    return { status: "unsupported", answer, sources: [], escalation: null, source: "demo" };
  }
  const best = matches[0].score;
  const picked = matches.filter((m) => m.score >= Math.max(1, best * 0.6)).slice(0, 3);
  const answer = picked[0].article.body;
  await streamText(answer, options);
  return {
    status: "answered",
    answer,
    sources: picked.map(({ article }) => ({ id: article.id, title: article.title, link: article.link, snippet: snippet(article.body) })),
    escalation: null,
    source: "demo",
  };
}
