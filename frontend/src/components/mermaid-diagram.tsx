"use client";

import { useEffect, useState } from "react";

interface Props {
  /** Mermaid chart source (flowchart / sequenceDiagram / etc). */
  chart: string;
  /** Unique DOM id for the rendered SVG (Mermaid needs this). */
  id: string;
}

/**
 * Client-side Mermaid renderer.
 *
 * Mermaid uses DOM APIs so it can't run at build time - we dynamic-import
 * it inside a useEffect so Next.js keeps the initial bundle small and
 * SSR doesn't blow up.
 *
 * The chart string is a compile-time constant (we author it in code, not
 * user input), so injecting the returned SVG via `dangerouslySetInnerHTML`
 * is safe.
 */
export default function MermaidDiagram({ chart, id }: Props) {
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: "dark",
          securityLevel: "loose",
          fontFamily: "'JetBrains Mono', ui-monospace, monospace",
          themeVariables: {
            darkMode: true,
            background: "#111114",
            primaryColor: "#16161a",
            primaryTextColor: "#e6e6e9",
            primaryBorderColor: "#33333a",
            lineColor: "#565660",
            secondaryColor: "#16161a",
            tertiaryColor: "#111114",
            actorBkg: "#16161a",
            actorBorder: "#33333a",
            actorTextColor: "#e6e6e9",
            actorLineColor: "#565660",
            signalColor: "#8a8a91",
            signalTextColor: "#e6e6e9",
            noteBkgColor: "#232327",
            noteTextColor: "#e6e6e9",
            noteBorderColor: "#33333a",
          },
        });
        const { svg: rendered } = await mermaid.render(id, chart);
        if (!cancelled) setSvg(rendered);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [chart, id]);

  if (error) {
    return (
      <div className="panel p-4 mono text-xs text-[var(--error)]">
        Diagram render error: {error}
      </div>
    );
  }

  if (!svg) {
    return (
      <div className="panel p-8 flex items-center justify-center text-xs text-[var(--text-subtle)]">
        Rendering diagram…
      </div>
    );
  }

  return (
    <div
      className="panel p-4 overflow-x-auto flex justify-center [&_svg]:max-w-full"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
