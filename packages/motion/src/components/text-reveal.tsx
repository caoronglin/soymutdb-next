import * as React from "react";
import { cn } from "../utils";
import { gsap } from "../gsap-setup";
import { useMotion } from "../context";

export interface TextRevealProps extends Omit<React.HTMLAttributes<HTMLSpanElement>, "children"> {
    text: string;
    baseDelay?: number;
    /** Milliseconds between tokens — converted to seconds for GSAP stagger. */
    step?: number;
    once?: boolean;
    split?: "word" | "char";
    as?: "span" | "div";
}

interface TokenInfo {
    token: string;
    tokIdx: number;
    isWhitespace: boolean;
    idx: number;
}

interface LineInfo {
    lineIdx: number;
    tokens: TokenInfo[];
}

/**
 * TextReveal — splits text into lines and words (or chars), wraps each token
 * in a span on mount, and runs a GSAP blur-focus stagger driven by
 * ScrollTrigger. Whitespace tokens are preserved without animation. Honors
 * reduced motion (renders the plain text statically).
 */
export function TextReveal({
    text,
    baseDelay = 0,
    step = 40,
    once = true,
    split = "word",
    as = "span",
    className,
    style,
    ...rest
}: TextRevealProps) {
    const Tag = as as React.ElementType;
    const containerRef = React.useRef<HTMLSpanElement | null>(null);
    const { reduced } = useMotion();

    const lines = React.useMemo(() => text.split("\n"), [text]);

    // Pre-compute token spans with stable, render-pure indices (no mutable
    // counter touched during render).
    const tokenized = React.useMemo<LineInfo[] | null>(() => {
        if (reduced) return null;
        let counter = 0;
        return lines.map((line, lineIdx) => {
            const tokens = split === "char" ? Array.from(line) : line.split(/(\s+)/);
            return {
                lineIdx,
                tokens: tokens.map((token, tokIdx) => {
                    if (/^\s+$/.test(token)) {
                        return { token, tokIdx, isWhitespace: true, idx: -1 };
                    }
                    return { token, tokIdx, isWhitespace: false, idx: counter++ };
                }),
            };
        });
    }, [lines, split, reduced]);

    React.useEffect(() => {
        if (reduced) return;
        const el = containerRef.current;
        if (!el) return;

        const tokens = el.querySelectorAll<HTMLElement>("[data-token]");
        if (tokens.length === 0) return;

        const ctx = gsap.context(() => {
            const mm = gsap.matchMedia();
            mm.add(
                {
                    isReduced: "(prefers-reduced-motion: reduce)",
                    isNormal: "(prefers-reduced-motion: no-preference)",
                },
                (context) => {
                    if (context.conditions?.isReduced) {
                        gsap.set(tokens, { opacity: 1, y: 0, filter: "blur(0px)" });
                        return;
                    }
                    // Blur focus effect: opacity 0 → 1, blur 8px → 0, y 0.4em → 0
                    gsap.fromTo(
                        tokens,
                        { opacity: 0, y: "0.4em", filter: "blur(8px)" },
                        {
                            opacity: 1,
                            y: 0,
                            filter: "blur(0px)",
                            duration: 0.6,
                            ease: "power2.out",
                            stagger: step / 1000,
                            delay: baseDelay / 1000,
                            scrollTrigger: {
                                trigger: el,
                                start: "top 85%",
                                once,
                            },
                        },
                    );
                },
            );
            return () => mm.revert();
        }, el);

        return () => ctx.revert();
    }, [text, baseDelay, step, once, reduced, split]);

    return (
        <Tag
            ref={containerRef as unknown as React.Ref<HTMLElement>}
            className={cn(className)}
            style={style}
            {...rest}
        >
            {reduced
                ? text
                : tokenized?.map((line) => (
                      <span key={line.lineIdx} className="block">
                          {line.tokens.map((t) =>
                              t.isWhitespace ? (
                                  <span key={t.tokIdx}>{t.token}</span>
                              ) : (
                                  <span
                                      key={t.tokIdx}
                                      data-token={t.idx}
                                      style={{
                                          display: "inline-block",
                                          willChange: "opacity, transform, filter",
                                      }}
                                  >
                                      {t.token}
                                  </span>
                              ),
                          )}
                      </span>
                  ))}
        </Tag>
    );
}
