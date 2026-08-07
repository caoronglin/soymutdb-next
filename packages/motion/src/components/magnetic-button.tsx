/**
 * Magnetic button — cursor-trail-effects skill: magnetic attraction on hover.
 * The button gently translates toward the cursor position, creating a tactile feel.
 * Respects prefers-reduced-motion (static button).
 */
import * as React from "react";
import { gsap } from "../gsap-setup";

export interface MagneticButtonProps extends React.HTMLAttributes<HTMLDivElement> {
    /** Strength of the magnetic pull (0-1). Default 0.3. */
    strength?: number;
    children: React.ReactNode;
}

export function MagneticButton({
    strength = 0.3,
    children,
    className,
    style,
    ...rest
}: MagneticButtonProps) {
    const ref = React.useRef<HTMLDivElement | null>(null);

    React.useEffect(() => {
        const el = ref.current;
        if (!el) return;

        const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (prefersReduced) return;

        const xTo = gsap.quickTo(el, "x", { duration: 0.3, ease: "power3.out" });
        const yTo = gsap.quickTo(el, "y", { duration: 0.3, ease: "power3.out" });

        const onMouseMove = (e: MouseEvent) => {
            const rect = el.getBoundingClientRect();
            const x = (e.clientX - rect.left - rect.width / 2) * strength;
            const y = (e.clientY - rect.top - rect.height / 2) * strength;
            xTo(x);
            yTo(y);
        };

        const onMouseLeave = () => {
            xTo(0);
            yTo(0);
        };

        el.addEventListener("mousemove", onMouseMove);
        el.addEventListener("mouseleave", onMouseLeave);

        return () => {
            el.removeEventListener("mousemove", onMouseMove);
            el.removeEventListener("mouseleave", onMouseLeave);
        };
    }, [strength]);

    return (
        <div ref={ref} className={className} style={{ display: "inline-block", ...style }} {...rest}>
            {children}
        </div>
    );
}
