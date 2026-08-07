/**
 * Animation control center — popover for switching animation intensity.
 * Mounted in the site header. Persists to localStorage.
 */
import * as React from "react";
import { Sparkles, Check, Zap, Gauge, Ban, SunMedium } from "lucide-react";
import { Button, cn } from "@soymutdb/ui";
import { useAnimation, type AnimationIntensity } from "../lib/animation-context";

const OPTIONS: ReadonlyArray<{
    value: AnimationIntensity;
    label: string;
    description: string;
    icon: React.ComponentType<{ className?: string }>;
}> = [
        { value: "off", label: "Off", description: "No motion. Best for accessibility.", icon: Ban },
        { value: "minimal", label: "Minimal", description: "Only essential transitions (~100ms).", icon: Gauge },
        { value: "normal", label: "Normal", description: "Standard ease-out (~300ms).", icon: SunMedium },
        { value: "expressive", label: "Expressive", description: "Rich spring motion (~500ms).", icon: Zap },
    ];

export function AnimationControl() {
    const { intensity, setIntensity, reduced } = useAnimation();
    const [open, setOpen] = React.useState(false);
    const popoverRef = React.useRef<HTMLDivElement | null>(null);
    const buttonRef = React.useRef<HTMLButtonElement | null>(null);

    // Close on outside click / Escape.
    React.useEffect(() => {
        if (!open) return;
        const onPointer = (e: PointerEvent) => {
            if (
                popoverRef.current &&
                !popoverRef.current.contains(e.target as Node) &&
                buttonRef.current &&
                !buttonRef.current.contains(e.target as Node)
            ) {
                setOpen(false);
            }
        };
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") setOpen(false);
        };
        document.addEventListener("pointerdown", onPointer);
        document.addEventListener("keydown", onKey);
        return () => {
            document.removeEventListener("pointerdown", onPointer);
            document.removeEventListener("keydown", onKey);
        };
    }, [open]);

    return (
        <div className="relative">
            <Button
                ref={buttonRef}
                variant="ghost"
                size="icon"
                aria-label="Animation settings"
                aria-haspopup="dialog"
                aria-expanded={open}
                onClick={() => setOpen((v) => !v)}
            >
                <Sparkles className="size-4" aria-hidden />
            </Button>
            {open ? (
                <div
                    ref={popoverRef}
                    role="dialog"
                    aria-label="Animation settings"
                    className="absolute right-0 top-full z-50 mt-2 w-72 origin-top-right rounded-xl border bg-popover p-2 text-popover-foreground shadow-lg"
                    style={{
                        animation: "fade-down 160ms cubic-bezier(0.16, 1, 0.3, 1)",
                    }}
                >
                    <div className="px-3 py-2">
                        <p className="font-display text-sm font-semibold">Motion</p>
                        <p className="text-xs text-muted-foreground">
                            {reduced ? "Reduced motion is on (OS setting)." : "Tune animation intensity."}
                        </p>
                    </div>
                    <div className="mt-1 grid gap-1">
                        {OPTIONS.map((opt) => {
                            const Icon = opt.icon;
                            const active = intensity === opt.value;
                            return (
                                <button
                                    key={opt.value}
                                    type="button"
                                    onClick={() => {
                                        setIntensity(opt.value);
                                        setOpen(false);
                                    }}
                                    aria-pressed={active}
                                    className={cn(
                                        "flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left transition-colors",
                                        "hover:bg-accent focus-visible:bg-accent",
                                        active && "bg-accent/60",
                                    )}
                                >
                                    <Icon className="mt-0.5 size-4 shrink-0 text-foreground/70" aria-hidden />
                                    <span className="flex-1">
                                        <span className="block text-sm font-medium">{opt.label}</span>
                                        <span className="block text-xs text-muted-foreground">{opt.description}</span>
                                    </span>
                                    {active ? <Check className="mt-0.5 size-4 text-primary" aria-hidden /> : null}
                                </button>
                            );
                        })}
                    </div>
                </div>
            ) : null}
        </div>
    );
}
