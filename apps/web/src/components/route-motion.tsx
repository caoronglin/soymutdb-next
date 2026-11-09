/**
 * Route motion primitives.
 *
 * The public surface is deliberately tiny so routes can wrap sections without
 * owning animation details. Policy comes from `AnimationProvider`:
 *
 * - `off` (reduced-motion, Save-Data, user choice) renders static markup with
 *   no wrappers and no animation styles;
 * - `minimal` / `standard` animate with the Web Animations API, with durations
 *   and stagger taken from the shared tokens.
 *
 * Props that are not part of the DOM contract (`delay`, `variant`, ...) are
 * stripped before the element reaches the DOM.
 */
import * as React from "react";
import { useAnimationOptional } from "../lib/animation-context";

type MotionTag = keyof React.JSX.IntrinsicElements;
type MotionVariant = "fade" | "fade-up" | "blur-up" | "scale" | (string & {});

interface MotionBaseProps extends Omit<React.HTMLAttributes<HTMLElement>, "children"> {
  children?: React.ReactNode;
  /** Delay before the animation starts, in milliseconds. */
  delay?: number;
  /** First child delay for `Stagger`, in milliseconds. */
  baseDelay?: number;
  /** Per-child delay step for `Stagger`, in milliseconds. Defaults to the token. */
  step?: number;
  /** Accepted for call-site compatibility; the component animates once on mount. */
  once?: boolean;
  /** Preserved for call-site compatibility with the stagger-style API. */
  stagger?: number;
  variant?: MotionVariant;
  as?: MotionTag;
  text?: string;
}

interface MotionTokens {
  reduced: boolean;
  duration: number;
  durationSlow: number;
  easing: string;
  stagger: number;
}

const FALLBACK_TOKENS: MotionTokens = {
  reduced: false,
  duration: 300,
  durationSlow: 500,
  easing: "cubic-bezier(0.16, 1, 0.3, 1)",
  stagger: 60,
};

const useIsomorphicLayoutEffect =
  typeof window !== "undefined" ? React.useLayoutEffect : React.useEffect;

function useMotionTokens(): MotionTokens {
  const ctx = useAnimationOptional();
  if (!ctx) return FALLBACK_TOKENS;
  return {
    reduced: ctx.reduced,
    duration: ctx.duration,
    durationSlow: ctx.durationSlow,
    easing: ctx.easing,
    stagger: ctx.stagger,
  };
}

function stripMotionProps({
  as: _as,
  baseDelay: _baseDelay,
  delay: _delay,
  once: _once,
  stagger: _stagger,
  step: _step,
  text: _text,
  variant: _variant,
  ...props
}: MotionBaseProps): React.HTMLAttributes<HTMLElement> {
  return props;
}

function keyframesFor(variant: MotionVariant): Keyframe[] {
  if (variant === "scale") {
    return [
      { opacity: 0, transform: "scale(0.96)" },
      { opacity: 1, transform: "none" },
    ];
  }
  if (variant === "blur-up") {
    return [
      { opacity: 0, transform: "translateY(8px)", filter: "blur(8px)" },
      { opacity: 1, transform: "none", filter: "blur(0px)" },
    ];
  }
  if (variant === "fade") {
    return [{ opacity: 0 }, { opacity: 1 }];
  }
  return [
    { opacity: 0, transform: "translateY(16px)" },
    { opacity: 1, transform: "none" },
  ];
}

/**
 * Animates `ref` on mount when motion is allowed. `fill: "backwards"` keeps
 * the first keyframe applied during the delay so delayed items never flash.
 */
function useMountAnimation<T extends HTMLElement>(
  ref: React.RefObject<T | null>,
  variant: MotionVariant,
  delay: number,
  reduced: boolean,
): void {
  const { duration, easing } = useMotionTokens();
  useIsomorphicLayoutEffect(() => {
    const element = ref.current;
    if (reduced || !element || typeof element.animate !== "function") return;
    const animation = element.animate(keyframesFor(variant), {
      duration,
      delay,
      easing,
      fill: "backwards",
    });
    return () => animation.cancel();
  }, [ref, variant, delay, reduced, duration, easing]);
}

function MotionWrapper({
  as = "div",
  variant = "fade-up",
  delay = 0,
  ...rest
}: MotionBaseProps) {
  const props = stripMotionProps({ ...rest, as, variant, delay });
  const { reduced } = useMotionTokens();
  const elementRef = React.useRef<HTMLElement | null>(null);
  useMountAnimation(elementRef, variant, delay, reduced);
  const Tag = as as React.ElementType;
  return <Tag ref={elementRef} {...props} />;
}

function StaggerItem({
  variant,
  delay,
  children,
}: {
  variant: MotionVariant;
  delay: number;
  children: React.ReactNode;
}) {
  const { reduced } = useMotionTokens();
  const elementRef = React.useRef<HTMLDivElement | null>(null);
  useMountAnimation(elementRef, variant, delay, reduced);
  return <div ref={elementRef}>{children}</div>;
}

export function FadeUp(props: MotionBaseProps) {
  return <MotionWrapper variant="fade-up" {...props} />;
}

export function ScaleIn(props: MotionBaseProps) {
  return <MotionWrapper variant="scale" {...props} />;
}

export function Reveal({ variant = "fade-up", ...props }: MotionBaseProps) {
  return <MotionWrapper variant={variant} {...props} />;
}

export function Stagger({
  baseDelay = 0,
  step,
  as = "div",
  variant = "fade-up",
  children,
  ...rest
}: MotionBaseProps) {
  const props = stripMotionProps({ ...rest, as, variant, baseDelay, step });
  const { reduced, stagger } = useMotionTokens();
  const Tag = as as React.ElementType;

  if (reduced) {
    return <Tag {...props}>{children}</Tag>;
  }

  const childStep = step ?? stagger;
  return (
    <Tag {...props}>
      {React.Children.toArray(children).map((child, index) => (
        <StaggerItem
          key={(React.isValidElement(child) && child.key) || index}
          variant={variant}
          delay={baseDelay + index * childStep}
        >
          {child}
        </StaggerItem>
      ))}
    </Tag>
  );
}

function AnimatedSpan({
  variant,
  delay,
  style,
  children,
}: {
  variant: MotionVariant;
  delay: number;
  style?: React.CSSProperties;
  children: React.ReactNode;
}) {
  const { reduced } = useMotionTokens();
  const elementRef = React.useRef<HTMLSpanElement | null>(null);
  useMountAnimation(elementRef, variant, delay, reduced);
  return (
    <span ref={elementRef} style={style}>
      {children}
    </span>
  );
}

export function TextReveal({
  text,
  children,
  as = "span",
  variant = "fade-up",
  delay = 0,
  step = 30,
  ...rest
}: MotionBaseProps) {
  const props = stripMotionProps({ ...rest, as, variant, delay, step });
  const Tag = as as React.ElementType;
  const { reduced } = useMotionTokens();
  const content = text ?? (typeof children === "string" ? children : null);

  if (reduced) {
    return <Tag {...props}>{content ?? children}</Tag>;
  }

  if (content === null) {
    return (
      <Tag {...props}>
        <AnimatedSpan variant={variant} delay={delay}>
          {children}
        </AnimatedSpan>
      </Tag>
    );
  }

  const wordStyle: React.CSSProperties = { display: "inline-block", whiteSpace: "pre" };
  let wordIndex = 0;
  return (
    <Tag {...props}>
      {content.split(/(\s+)/).map((word, index) => {
        if (word.trim() === "") return word;
        const start = delay + wordIndex * step;
        wordIndex += 1;
        return (
          <AnimatedSpan key={`${index}-${word}`} variant={variant} delay={start} style={wordStyle}>
            {word}
          </AnimatedSpan>
        );
      })}
    </Tag>
  );
}

/**
 * Page-level reveal. Returns the caller's ref unchanged, so callers can keep
 * owning the element, and animates it once on mount when motion is allowed.
 */
export function useReveal<T extends HTMLElement = HTMLDivElement>(
  rootOrOptions?: React.RefObject<T | null> | Record<string, unknown>,
  _options?: Record<string, unknown>,
): React.RefObject<T | null> {
  const internalRef = React.useRef<T | null>(null);
  const ref =
    rootOrOptions && "current" in rootOrOptions
      ? (rootOrOptions as React.RefObject<T | null>)
      : internalRef;
  const { reduced, durationSlow, easing } = useMotionTokens();

  useIsomorphicLayoutEffect(() => {
    const element = ref.current;
    if (reduced || !element || typeof element.animate !== "function") return;
    const animation = element.animate(
      [
        { opacity: 0, transform: "translateY(12px)" },
        { opacity: 1, transform: "none" },
      ],
      { duration: durationSlow, easing, fill: "backwards" },
    );
    return () => animation.cancel();
  }, [ref, reduced, durationSlow, easing]);

  return ref;
}