import { useEffect } from "react";

type MetaTag = { name: string; content: string } | { property: string; content: string };

export type HeadConfig = {
  title: string;
  meta?: MetaTag[];
};

/**
 * Client-side replacement for TanStack Router's per-route `head()`.
 * Sets the document title and upserts <meta> tags; restores the previous
 * values when the page unmounts so the defaults from index.html come back.
 */
export function useHead({ title, meta = [] }: HeadConfig) {
  const key = JSON.stringify({ title, meta });

  useEffect(() => {
    const previousTitle = document.title;
    document.title = title;

    const restores: Array<() => void> = [];
    for (const tag of meta) {
      const attr = "name" in tag ? "name" : "property";
      const value = "name" in tag ? tag.name : tag.property;
      let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${value}"]`);
      if (el) {
        const prev = el.getAttribute("content");
        const existing = el;
        restores.push(() => {
          if (prev === null) existing.removeAttribute("content");
          else existing.setAttribute("content", prev);
        });
      } else {
        el = document.createElement("meta");
        el.setAttribute(attr, value);
        document.head.appendChild(el);
        const created = el;
        restores.push(() => created.remove());
      }
      el.setAttribute("content", tag.content);
    }

    return () => {
      document.title = previousTitle;
      for (const restore of restores.reverse()) restore();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}
