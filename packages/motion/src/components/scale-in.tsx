import * as React from "react";
import { cn } from "../utils";
import { useReveal } from "../use-reveal";

export interface ScaleInProps extends React.HTMLAttributes<HTMLDivElement> {
    delay?: number;
    once?: boolean;
}

export function ScaleIn({ delay = 0, once = true, className, style, children, ...rest }: ScaleInProps) {
    const ref = useReveal<HTMLDivElement>({ variant: "scale-in", delay, once });
    return (
        <div ref={ref} className={cn(className)} style={style} {...rest}>
            {children}
        </div>
    );
}
