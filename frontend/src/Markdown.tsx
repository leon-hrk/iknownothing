import type { ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

/** Fenced code blocks (closed or still streaming) and inline code spans. */
const CODE = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)/g;

/** Inline `$…$` with no space inside its delimiters; a `$` next to a space, as in amounts of money, is text. */
const DOLLAR_MATH = /(?<![\\$\w])\$(?=[^\s$])([^$\n]*?[^\s$\\])\$(?![\w$])/g;

/** Rewrites `\(…\)` and inline `$…$` to `$$…$$` and `\[…\]` to a `$$` block, outside of code, for remark-math. */
function normalizeMath(text: string): string {
  return text
    .split(CODE)
    .map((part, i) => i % 2 ? part : part
      .replace(/\\\[([\s\S]*?)\\\]/g, (_, m: string) =>
        /^[ \t]*\n[\s\S]*\n[ \t]*$/.test(m) ? `$$${m}$$` : `\n$$\n${m.trim()}\n$$\n`)
      .replace(/\\\(([\s\S]*?)\\\)/g, (_, m: string) => `$$${m.trim()}$$`)
      .replace(DOLLAR_MATH, (_, m: string) => `$$${m}$$`))
    .join("");
}

/** A URL with a scheme, an absolute path, or only a fragment. */
const ABSOLUTE = /^([a-z][a-z0-9+.-]*:|\/|#)/i;

/** With `resolve`, relative image sources are turned into URLs by it; with `onOpen`, a click on a relative link
 * calls it with the link target instead of following it. */
export default function Markdown({ text, resolve, onOpen }: {
  text: string; resolve?: (src: string) => string; onOpen?: (href: string) => void;
}) {
  const urlTransform = (url: string, key: string) => {
    const safe = defaultUrlTransform(url);
    return resolve && key === "src" && safe && !ABSOLUTE.test(safe) ? resolve(safe) : safe;
  };
  const components = onOpen && {
    a: ({ href, children }: { href?: string; children?: ReactNode }) => href && !ABSOLUTE.test(href)
      ? <a href={href} onClick={(e) => { e.preventDefault(); onOpen(href); }}>{children}</a>
      : <a href={href}>{children}</a>,
  };
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]} rehypePlugins={[rehypeKatex]}
        urlTransform={urlTransform} components={components}>
        {normalizeMath(text)}
      </ReactMarkdown>
    </div>
  );
}
