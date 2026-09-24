import React from "react";

// Rendu Markdown très léger : paragraphes, listes, **gras**, _italique_, [n] citations.
function inline(text, onCite) {
  const parts = [];
  const re = /(\*\*[^*]+\*\*|_[^_]+_|\[\d+\])/g;
  let last = 0, m, k = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("**")) parts.push(<strong key={k++}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith("_")) parts.push(<em key={k++}>{t.slice(1, -1)}</em>);
    else {
      const n = t.slice(1, -1);
      parts.push(
        <button key={k++} type="button" className="cite" onClick={() => onCite?.(Number(n))} aria-label={`Source ${n}`}>
          {n}
        </button>
      );
    }
    last = m.index + t.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export default function Markdown({ text = "", onCite }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="md">
      {blocks.map((b, i) => {
        const lines = b.split("\n").filter(Boolean);
        if (lines.length && lines.every((l) => /^\s*([-*•]|\d+\.)\s+/.test(l)))
          return (
            <ul key={i}>
              {lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*([-*•]|\d+\.)\s+/, ""), onCite)}</li>)}
            </ul>
          );
        return <p key={i}>{inline(lines.join(" "), onCite)}</p>;
      })}
    </div>
  );
}
