import * as React from "react";
import { cn } from "../utils";
import { gsap } from "../gsap-setup";
import { useMotion } from "../context";

function formatNumber(n: number): string {
    return n.toLocaleString("en-US");
}

export interface CountUpProps extends React.HTMLAttributes<HTMLSpanElement> {
    end: number;
    start?: number;
    duration?: number;
    formatted?: boolean;
    suffix?: string;
    prefix?: string;
}

/**
 * Count-up number animation. Tweens a proxy object's `val` from `start` to
 * `end` with GSAP, writing the rounded value into the DOM via React state.
 * Triggers on scroll into view. Respects reduced motion (snaps to `end`).
 */
export function CountUp({
    end,
    start = 0,
    duration = 1200,
    formatted = true,
    suffix,
    prefix,
    className,
    ...rest
}: CountUpProps) {
    const ref = React.useRef<HTMLSpanElement | null>(null);
    const { reduced } = useMotion();
    const [display, setDisplay] = React.useState(start);

    React.useEffect(() => {
        if (reduced) {
            setDisplay(end);
            return;
        }
        const el = ref.current;
        if (!el) return;

        const ctx = gsap.context(() => {
            const obj = { val: start };
            gsap.to(obj, {
                val: end,
                duration: duration / 1000,
                ease: "power1.out",
                onUpdate: () => setDisplay(Math.round(obj.val)),
                scrollTrigger: {
                    trigger: el,
                    start: "top 90%",
                    once: true,
                },
            });
        }, el);

        return () => ctx.revert();
    }, [end, start, duration, reduced]);

    const text = formatted ? formatNumber(display) : String(display);

    return (
        <span ref={ref} className={cn("font-mono tabular-nums", className)} data-numeric {...rest}>
            {prefix}
            {text}
            {suffix}
        </span>
    );
}
