import * as React from "react";

type MotionProps = React.HTMLAttributes<HTMLDivElement> & {
  delay?: number;
  once?: boolean;
  baseDelay?: number;
  step?: number;
  variant?: string;
  stagger?: number;
  as?: keyof React.JSX.IntrinsicElements;
  text?: string;
};

function getDomProps({
  as: _as,
  baseDelay: _baseDelay,
  delay: _delay,
  once: _once,
  stagger: _stagger,
  step: _step,
  text: _text,
  variant: _variant,
  ...props
}: Omit<MotionProps, "children">): React.HTMLAttributes<HTMLDivElement> {
  return props;
}

export function FadeUp({ children, ...props }: MotionProps) {
  return <div {...getDomProps(props)}>{children}</div>;
}

export function FadeIn({ children, ...props }: MotionProps) {
  return <div {...getDomProps(props)}>{children}</div>;
}

export function ScaleIn({ children, ...props }: MotionProps) {
  return <div {...getDomProps(props)}>{children}</div>;
}

export function Reveal({ children, ...props }: MotionProps) {
  return <div {...getDomProps(props)}>{children}</div>;
}

export function Stagger({ children, ...props }: MotionProps) {
  return <div {...getDomProps(props)}>{children}</div>;
}

export function TextReveal({ text, children, as = "span", ...props }: MotionProps) {
  const Tag = as as React.ElementType;
  return <Tag {...getDomProps(props)}>{text ?? children}</Tag>;
}

export function CountUp({ end, start = 0, prefix, suffix, children, ...props }: MotionProps & { end: number; start?: number; prefix?: string; suffix?: string }) {
  return <span {...getDomProps(props)}>{prefix}{end ?? start}{suffix}{children}</span>;
}

export function useReveal<T extends HTMLElement = HTMLDivElement>(
  rootOrOptions?: React.RefObject<T | null> | Record<string, unknown>,
  _options?: Record<string, unknown>,
): React.RefObject<T | null> {
  const internalRef = React.useRef<T | null>(null);
  return (rootOrOptions && "current" in rootOrOptions
    ? (rootOrOptions as React.RefObject<T | null>)
    : internalRef) as React.RefObject<T | null>;
}
