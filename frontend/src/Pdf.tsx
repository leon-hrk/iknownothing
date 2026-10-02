import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

/** Every page of the PDF at `url`, as wide as the reader. */
export default function Pdf({ url }: { url: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [pages, setPages] = useState(0);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(ref.current!);
    return () => observer.disconnect();
  }, []);
  return (
    <div className="pdf" ref={ref}>
      <Document file={url} onLoadSuccess={(d) => setPages(d.numPages)}
        loading={<div className="pending">…</div>} error={<p className="error">The PDF could not be loaded.</p>}>
        {width > 0 && Array.from({ length: pages }, (_, i) => <Page key={i} pageNumber={i + 1} width={width} />)}
      </Document>
    </div>
  );
}
