/**
 * A small, deterministic Python highlighter for short fixed snippets.
 * It never changes the source text: tokens concatenate back to the input line.
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
  "from", "import", "def", "class", "return", "try", "finally", "yield", "if", "else",
  "elif", "for", "in", "with", "as", "async", "await", "None", "True", "False", "and",
  "or", "not", "raise", "except", "pass", "lambda", "is",
]);
const BUILTINS = new Set(["str", "int", "bool", "dict", "list", "float", "print", "len"]);

const PATTERN =
  /(#.*$)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(@[\w.]+)|(\b\d+\b)|([A-Za-z_]\w*)|(\s+)|([^\sA-Za-z_\d"'#@]+)/g;

export function tokenizePython(line: string): Token[] {
  const tokens: Token[] = [];
  let previousWord = "";
  for (const match of line.matchAll(PATTERN)) {
    const [text, comment, string, decorator, number, word, space] = match;
    const rest = line.slice((match.index ?? 0) + text.length);
    let kind: TokenKind = "punct";
    if (comment) kind = "com";
    else if (string) kind = "str";
    else if (decorator) kind = "dec";
    else if (number) kind = "num";
    else if (space) kind = "plain";
    else if (word) {
      if (KEYWORDS.has(word)) kind = "kw";
      else if (previousWord === "def") kind = "fn";
      else if (previousWord === "class" || /^[A-Z]/.test(word)) kind = "cls";
      else if (BUILTINS.has(word)) kind = "builtin";
      else if (rest.startsWith("(")) kind = "call";
      else kind = "plain";
      previousWord = word;
    }
    tokens.push({ kind, text });
  }
  return tokens;
}
