import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

/** Fenced code blocks (closed or still streaming) and inline code spans. */
const CODE = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)/g;

/** Rewrites `\(…\)` to `$$…$$` and `\[…\]` to a `$$` block, outside of code, for remark-math. */
function normalizeMath(text: string): string {
  return text
    .split(CODE)
    .map((part, i) => i % 2 ? part : part
      .replace(/\\\[([\s\S]*?)\\\]/g, (_, m: string) =>
        /^[ \t]*\n[\s\S]*\n[ \t]*$/.test(m) ? `$$${m}$$` : `\n$$\n${m.trim()}\n$$\n`)
      .replace(/\\\(([\s\S]*?)\\\)/g, (_, m: string) => `$$${m.trim()}$$`))
    .join("");
}

export default function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]} rehypePlugins={[rehypeKatex]}>
        {normalizeMath(text)}
      </ReactMarkdown>
    </div>
  );
}
