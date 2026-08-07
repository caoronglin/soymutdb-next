import * as React from "react";
import { cn } from "../utils";
import { useGsapReveal } from "../use-gsap-reveal";

export interface FadeUpProps extends React.HTMLAttributes<HTMLDivElement> {
    delay?: number;
    once?: boolean;
}

export function FadeUp({ delay = 0, once = true, className, style, children, ...rest }: FadeUpProps) {
    const ref = useGsapReveal<HTMLDivElement>({ variant: "fade-up", delay, once });
    return (
        <div ref={ref} className={cn(className)} style={style} {...rest}>
            {children}
        </div>
    );
}
