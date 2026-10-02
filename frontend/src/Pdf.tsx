import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

/** Every page of the PDF at `url`, as wide as the reader. Scrolls to `page` whenever `opened` changes. */
export default function Pdf({ url, page, opened }: { url: string; page?: number; opened: unknown }) {
  const ref = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [width, setWidth] = useState(0);
  const [pages, setPages] = useState(0);
  const [ratio, setRatio] = useState(0);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(ref.current!);
    return () => observer.disconnect();
  }, []);
  const ready = width > 0 && ratio > 0;
  useEffect(() => {
    const target = ready && page ? pageRefs.current[page - 1] : null;
    const reader = ref.current?.parentElement;
    if (target && reader) reader.scrollTop += target.getBoundingClientRect().top - reader.getBoundingClientRect().top;
  }, [ready, opened]);
  return (
    <div className="pdf" ref={ref}>
      <Document file={url}
        onLoadSuccess={(d) => {
          setPages(d.numPages);
          d.getPage(1).then((p) => { const v = p.getViewport({ scale: 1 }); setRatio(v.height / v.width); });
        }}
        loading={<div className="pending">…</div>} error={<p className="error">The PDF could not be loaded.</p>}>
        {ready && Array.from({ length: pages }, (_, i) => (
          // the height of the first page holds each page's place, so a page can be scrolled to before it is drawn
          <div key={i} className="pdf-page" ref={(el) => { pageRefs.current[i] = el; }} style={{ minHeight: Math.round(width * ratio) }}>
            <Page pageNumber={i + 1} width={width} />
          </div>
        ))}
      </Document>
    </div>
  );
}
