import { tokenizePython } from "./highlight";

/** Renders one highlighted Python line. Works in Server and Client Components. */
export function CodeText({ source }: { source: string }) {
  if (source === "") return <>{"​"}</>;
  return (
    <>
      {tokenizePython(source).map((token, index) => (
        <span key={index} className={`tok-${token.kind}`}>
          {token.text}
        </span>
      ))}
    </>
  );
}
