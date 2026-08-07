import * as React from "react";
import { AlertTriangle, RotateCw } from "lucide-react";
import { Button } from "@soymutdb/ui";

export interface ErrorBoundaryProps {
    children: React.ReactNode;
    /** Optional fallback render. */
    fallback?: (error: Error, reset: () => void) => React.ReactNode;
}

interface ErrorBoundaryState {
    error: Error | null;
}

/**
 * App-wide error boundary. Catches render errors in the subtree and offers
 * a retry button that re-mounts the children.
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
    state: ErrorBoundaryState = { error: null };

    static getDerivedStateFromError(error: Error): ErrorBoundaryState {
        return { error };
    }

    componentDidCatch(error: Error, info: React.ErrorInfo): void {
        // Log to console — a production app would forward to an APM.
        console.error("[ErrorBoundary]", error, info.componentStack);
    }

    reset = (): void => {
        this.setState({ error: null });
    };

    render(): React.ReactNode {
        const { error } = this.state;
        if (error) {
            if (this.props.fallback) return this.props.fallback(error, this.reset);
            return <DefaultFallback error={error} onReset={this.reset} />;
        }
        return this.props.children;
    }
}

function DefaultFallback({ error, onReset }: { error: Error; onReset: () => void }) {
    return (
        <div
            role="alert"
            className="mx-auto flex max-w-md flex-col items-center rounded-xl border border-dashed p-10 text-center"
        >
            <div className="mb-4 flex size-12 items-center justify-center rounded-full bg-destructive/10">
                <AlertTriangle className="size-6 text-destructive" aria-hidden />
            </div>
            <h2 className="font-display text-xl font-semibold">Something went wrong</h2>
            <p className="mt-2 text-sm text-muted-foreground">
                {error.message || "An unexpected error occurred while rendering this section."}
            </p>
            <Button onClick={onReset} className="mt-6" variant="default">
                <RotateCw className="size-4" aria-hidden />
                Try again
            </Button>
        </div>
    );
}
