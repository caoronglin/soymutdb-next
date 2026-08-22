/**
 * Compatibility wrapper retained for callers that previously opted into a
 * cursor effect. It is deliberately static under the bounded motion policy.
 */
import * as React from "react";

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
    return (
        <div
            className={className}
            data-motion-strength={strength}
            style={{ display: "inline-block", ...style }}
            {...rest}
        >
            {children}
        </div>
    );
}
