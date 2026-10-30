/**
 * A small, deterministic JavaScript highlighter for short fixed snippets
 * (Node + Express examples on the marketing site). It never changes the source
 * text: tokens concatenate back to the input line.
 */
export type TokenKind =
  | "kw"
  | "str"
  | "com"
  | "dec"
  | "num"
  | "fn"
  | "call"
  | "cls"
  | "builtin"
  | "punct"
  | "plain";

export type Token = { kind: TokenKind; text: string };

const KEYWORDS = new Set([
  "const", "let", "var", "function", "return", "if", "else", "for", "while", "of", "in",
  "new", "async", "await", "try", "catch", "throw", "import", "export", "from", "class",
]);
/** Literal values get the "number" colour so they stand out from names. */
const LITERALS = new Set(["true", "false", "null", "undefined"]);
const BUILTINS = new Set(["require", "console", "JSON", "Math", "Object", "Array"]);

const PATTERN =
  /(\/\/.*$)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_$][\w$]*)|(\s+)|([^\sA-Za-z_$\d"'`]+)/g;

export function tokenize(line: string): Token[] {
  const tokens: Token[] = [];
  let previous = "";
  for (const match of line.matchAll(PATTERN)) {
    const [text, comment, string, number, word, space] = match;
    const rest = line.slice((match.index ?? 0) + text.length);
    let kind: TokenKind = "punct";
    if (comment) kind = "com";
    else if (string) kind = "str";
    else if (number) kind = "num";
    else if (space) kind = "plain";
    else if (word) {
      if (KEYWORDS.has(word)) kind = "kw";
      else if (LITERALS.has(word)) kind = "num";
      else if (BUILTINS.has(word)) kind = "builtin";
      else if (previous === "function") kind = "fn";
      else if (/^[A-Z]/.test(word)) kind = "cls";
      else if (rest.startsWith("(")) kind = "call";
      else kind = "plain";
    }
    if (!space) previous = text.trim();
    tokens.push({ kind, text });
  }
  return tokens;
}
