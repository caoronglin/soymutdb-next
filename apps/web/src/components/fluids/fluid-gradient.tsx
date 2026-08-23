/**
 * FluidGradient — animated deep-blue fluid background.
 *
 * A lightweight WebGL2 fragment shader that recreates the flowing gradient
 * used on DeepSeek's "Join DeepSeek" brand panel (fbm + domain warping over a
 * five-stop palette). The canvas is entirely self-contained so it can be
 * dropped behind any Ant Design surface without pulling in a UI library.
 *
 * Accessibility: when `reduced` is true (via the app motion policy) the
 * shader renders a single static frame and never starts the animation loop.
 */
import * as React from "react";

export interface FluidGradientProps {
  /** Five-stop deep-blue palette (defaults to the DeepSeek brand ramp). */
  colors?: string[];
  speed?: number;
  scale?: number;
  grain?: number;
  /** Disable the animation loop (reduced-motion / `off` intensity). */
  reduced?: boolean;
  className?: string;
  style?: React.CSSProperties;
  /** Overlay content rendered above the canvas (kept in DOM flow). */
  children?: React.ReactNode;
}

export const DEFAULT_FLUID_COLORS = [
  "#0A1A3A",
  "#1A3870",
  "#2D5F9E",
  "#4A8AC4",
  "#0D1F4A",
];

const VERT = `#version 300 es
in vec2 a_pos;
out vec2 v_uv;
void main() {
  v_uv = a_pos * 0.5 + 0.5;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}`;

const FRAG = `#version 300 es
precision highp float;
out vec4 fragColor;
in vec2 v_uv;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_speed;
uniform float u_scale;
uniform float u_grain;
uniform vec3 u_colors[5];

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}
float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
    mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x),
    u.y
  );
}
float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  mat2 rot = mat2(0.8, 0.6, -0.6, 0.8);
  for (int i = 0; i < 5; i++) {
    v += a * noise(p);
    p = rot * p * 2.0;
    a *= 0.5;
  }
  return v;
}
vec3 grad(float t) {
  vec3 c0 = u_colors[0];
  vec3 c1 = u_colors[1];
  vec3 c2 = u_colors[2];
  vec3 c3 = u_colors[3];
  vec3 c4 = u_colors[4];
  t = clamp(t, 0.0, 1.0);
  float x = t * 4.0;
  int i = int(floor(x));
  float f = fract(x);
  vec3 a = i == 0 ? c0 : (i == 1 ? c1 : (i == 2 ? c2 : (i == 3 ? c3 : c4)));
  vec3 b = i >= 3 ? c4 : (i == 0 ? c1 : (i == 1 ? c2 : (i == 2 ? c3 : c4)));
  return mix(a, b, smoothstep(0.0, 1.0, f));
}
void main() {
  vec2 uv = v_uv;
  float aspect = u_resolution.x / u_resolution.y;
  vec2 p = (vec2(uv.x * aspect, uv.y) - vec2(aspect * 0.5, 0.5)) * u_scale;
  float t = u_time * u_speed * 0.001;

  vec2 q = vec2(fbm(p + t), fbm(p + vec2(5.2, 1.3) - t));
  vec2 r = vec2(
    fbm(p + q * 1.7 + vec2(1.7, 9.2) + vec2(t * 0.5, -t * 0.4)),
    fbm(p + q * 1.7 + vec2(8.3, 2.8) - vec2(t * 0.3, t * 0.6))
  );
  float f = fbm(p + r * 1.7);
  float n = mix(f, f * f * f, 0.25);

  vec3 col = grad(n);
  float g = (hash(uv * u_resolution - t) * 2.0 - 1.0) * u_grain;
  col += g;

  vec2 d = uv - 0.5;
  float vig = smoothstep(0.9, 0.3, length(d * vec2(aspect, 1.0)));
  col *= mix(0.72, 1.0, vig);
  fragColor = vec4(col, 1.0);
}`;

function defaultGradientCss(colors: string[]): string {
  return `linear-gradient(150deg, ${colors.join(", ")})`;
}

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace("#", "");
  const value = parseInt(clean.length === 3 ? clean.split("").map((c) => c + c).join("") : clean, 16);
  return [((value >> 16) & 0xff) / 255, ((value >> 8) & 0xff) / 255, (value & 0xff) / 255];
}

/**
 * Render one static fluid frame (used by reduced-motion and before first RAF).
 */
function compileProgram(gl: WebGL2RenderingContext): WebGLProgram | null {
  function compile(type: number, source: string): WebGLShader | null {
    const shader = gl.createShader(type);
    if (!shader) return null;
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  }

  const vs = compile(gl.VERTEX_SHADER, VERT);
  const fs = compile(gl.FRAGMENT_SHADER, FRAG);
  if (!vs || !fs) return null;
  const program = gl.createProgram();
  if (!program) return null;
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  gl.deleteShader(vs);
  gl.deleteShader(fs);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    gl.deleteProgram(program);
    return null;
  }
  return program;
}

export function FluidGradient({
  colors = DEFAULT_FLUID_COLORS,
  speed = 80,
  scale = 2.5,
  grain = 0.003,
  reduced = false,
  className,
  style,
  children,
}: FluidGradientProps) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (typeof window === "undefined" || typeof document === "undefined") return;
    const node: HTMLCanvasElement = canvas;

    const ctx = node.getContext("webgl2", {
      alpha: true,
      antialias: true,
      premultipliedAlpha: true,
    }) as WebGL2RenderingContext | null;
    if (!ctx) {
      setFailed(true);
      return;
    }

    const gl = ctx;
    const program = compileProgram(gl);
    if (!program) {
      setFailed(true);
      return;
    }
    gl.useProgram(program);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const positionLoc = gl.getAttribLocation(program, "a_pos");
    gl.enableVertexAttribArray(positionLoc);
    gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0);

    const palette = colors.map(hexToRgb);
    gl.uniform3fv(gl.getUniformLocation(program, "u_colors"), new Float32Array(palette.flat()));

    const uRes = gl.getUniformLocation(program, "u_resolution");
    const uTime = gl.getUniformLocation(program, "u_time");
    const uSpeed = gl.getUniformLocation(program, "u_speed");
    const uScale = gl.getUniformLocation(program, "u_scale");
    const uGrain = gl.getUniformLocation(program, "u_grain");

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let width = 0;
    let height = 0;
    function resize() {
      const nextWidth = Math.max(1, node.clientWidth);
      const nextHeight = Math.max(1, node.clientHeight);
      if (nextWidth === width && nextHeight === height) return;
      width = nextWidth;
      height = nextHeight;
      node.width = Math.floor(width * dpr);
      node.height = Math.floor(height * dpr);
      gl.viewport(0, 0, node.width, node.height);
      gl.uniform2f(uRes, node.width, node.height);
    }
    resize();

    let raf = 0;
    const start = performance.now();
    let stopped = false;

    function frame(now: number) {
      if (stopped) return;
      const t = (now - start) / 1000;
      gl.uniform1f(uTime, t);
      gl.uniform1f(uSpeed, speed);
      gl.uniform1f(uScale, scale);
      gl.uniform1f(uGrain, grain);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      raf = requestAnimationFrame(frame);
    }

    function drawStatic() {
      gl.uniform1f(uTime, 0);
      gl.uniform1f(uSpeed, speed);
      gl.uniform1f(uScale, scale);
      gl.uniform1f(uGrain, grain);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }

    if (reduced) {
      drawStatic();
    } else {
      raf = requestAnimationFrame(frame);
    }

    const onResize = () => resize();
    window.addEventListener("resize", onResize);

    return () => {
      stopped = true;
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      const lose = gl.getExtension("WEBGL_lose_context");
      lose?.loseContext();
      gl.deleteProgram(program);
    };
  }, [colors, speed, scale, grain, reduced]);

  const fallbackBackground = failed ? defaultGradientCss(colors) : undefined;

  return (
    <div
      className={className}
      style={{ position: "relative", overflow: "hidden", background: fallbackBackground, ...style }}
      aria-hidden="true"
    >
      <canvas
        ref={canvasRef}
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", display: "block" }}
      />
      {children ? <div style={{ position: "relative", zIndex: 1 }}>{children}</div> : null}
    </div>
  );
}

export default FluidGradient;
