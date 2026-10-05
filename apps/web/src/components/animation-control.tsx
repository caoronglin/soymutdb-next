/**
 * Animation control center — popover for switching animation intensity.
 * Mounted in the site header. Persists to localStorage.
 */
import * as React from "react";
import { useTranslation } from "react-i18next";
import { CrownOutlined, CheckOutlined, DashboardOutlined, StopOutlined, SunOutlined } from "@ant-design/icons";
import { Button } from "@/lib/antd";
import { cn } from "@/lib/cn";
import { useAnimation, type AnimationIntensity } from "../lib/animation-context";

const OPTIONS: ReadonlyArray<{
    value: AnimationIntensity;
    label: string;
    description: string;
    icon: React.ComponentType<{ className?: string }>;
}> = [
        { value: "auto", label: "Auto", description: "Adapt to accessibility and session resources.", icon: CrownOutlined },
        { value: "standard", label: "Standard", description: "Standard ease-out (~300ms).", icon: SunOutlined },
        { value: "minimal", label: "Minimal", description: "Only essential transitions (~100ms).", icon: DashboardOutlined },
        { value: "off", label: "Off", description: "No motion. Best for accessibility.", icon: StopOutlined },
    ];

export function AnimationControl() {
  const { t } = useTranslation();
    const { preference, intensity, decisionReason, setIntensity } = useAnimation();
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
                type="text"
                icon={<CrownOutlined className="size-4" aria-hidden />}
                aria-label={t("animation.settings")}
                aria-haspopup="dialog"
                aria-expanded={open}
                onClick={() => setOpen((v) => !v)}
            />
            {open ? (
                <div
                    ref={popoverRef}
                    role="dialog"
                    aria-label={t("animation.settings")}
                    className="absolute right-0 top-full z-50 mt-2 w-72 origin-top-right rounded-xl border bg-popover p-2 text-popover-foreground shadow-lg"
                    style={{
                        animation: "fade-down 160ms cubic-bezier(0.16, 1, 0.3, 1)",
                    }}
                >
                    <div className="px-3 py-2">
                        <p className="font-display text-sm font-semibold">{t("animation.motion")}</p>
                        <p className="text-xs text-muted-foreground">
                            {decisionReason === "reduced-motion"
                                ? t("animation.reducedMotionOs")
                                : preference !== intensity
                                  ? t("animation.sessionAdjustedTo", { mode: intensity })
                                  : t("animation.tuneHint")}
                        </p>
                    </div>
                    <div className="mt-1 grid gap-1">
                        {OPTIONS.map((opt) => {
                            const Icon = opt.icon;
                            const active = preference === opt.value;
                            return (
                                <Button
                                    key={opt.value}
                                    htmlType="button"
                                    type="text"
                                    onClick={() => {
                                        setIntensity(opt.value);
                                        setOpen(false);
                                    }}
                                    aria-pressed={active}
                                    className={cn(
                                        "flex h-auto w-full items-start gap-3 rounded-lg px-3 py-2 text-left transition-colors",
                                        "hover:bg-accent focus-visible:bg-accent",
                                        active && "bg-accent/60",
                                    )}
                                >
                                    <Icon className="mt-0.5 size-4 shrink-0 text-foreground/70" aria-hidden />
                                    <span className="flex-1">
                                        <span className="block text-sm font-medium">{opt.label}</span>
                                        <span className="block text-xs text-muted-foreground">{opt.description}</span>
                                    </span>
                                    {active ? <CheckOutlined className="mt-0.5 size-4 text-primary" aria-hidden /> : null}
                                </Button>
                            );
                        })}
                    </div>
                </div>
            ) : null}
        </div>
    );
}
