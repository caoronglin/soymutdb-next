import * as React from "react";
import { cn } from "../utils";
import { useMotion } from "../context";
import { useReveal } from "../use-reveal";

export interface TextRevealProps extends Omit<React.HTMLAttributes<HTMLSpanElement>, "children"> {
    text: string;
    baseDelay?: number;
    /** Milliseconds between tokens. */
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
 * in a span and reveals them using opacity/transform only. Whitespace tokens
 * are preserved without animation. Honors
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
    const { reduced } = useMotion();
    const containerRef = useReveal<HTMLElement>({
        variant: "fade-up",
        delay: baseDelay,
        once,
        stagger: step / 1000,
        childSelector: "[data-token]",
    });

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
                                          willChange: "opacity, transform",
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
