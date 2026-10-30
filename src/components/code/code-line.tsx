import { tokenize } from "./highlight";

/** Renders one highlighted JavaScript line. Works in Server and Client Components. */
export function CodeText({ source }: { source: string }) {
  if (source === "") return <>{"​"}</>;
  return (
    <>
      {tokenize(source).map((token, index) => (
        <span key={index} className={`tok-${token.kind}`}>
          {token.text}
        </span>
      ))}
    </>
  );
}
