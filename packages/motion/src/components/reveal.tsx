import * as React from "react";
import { cn } from "../utils";
import { useGsapReveal } from "../use-gsap-reveal";
import { type RevealVariant } from "../types";

export interface RevealProps extends React.HTMLAttributes<HTMLDivElement> {
    variant?: RevealVariant;
    delay?: number;
    once?: boolean;
    as?: keyof React.JSX.IntrinsicElements;
}

export function Reveal({
    variant = "blur-up",
    delay = 0,
    once = true,
    as = "div",
    className,
    style,
    children,
    ...rest
}: RevealProps) {
    const Tag = as as React.ElementType;
    const ref = useGsapReveal<HTMLDivElement>({ variant, delay, once });
    return (
        <Tag ref={ref} className={cn(className)} style={style} {...rest}>
            {children}
        </Tag>
    );
}
