import * as React from "react";
import { cn } from "../utils";
import { useReveal } from "../use-reveal";

export interface FadeInProps extends React.HTMLAttributes<HTMLDivElement> {
    delay?: number;
    once?: boolean;
}

export function FadeIn({ delay = 0, once = true, className, style, children, ...rest }: FadeInProps) {
    const ref = useReveal<HTMLDivElement>({ variant: "fade-in", delay, once });
    return (
        <div ref={ref} className={cn(className)} style={style} {...rest}>
            {children}
        </div>
    );
}
