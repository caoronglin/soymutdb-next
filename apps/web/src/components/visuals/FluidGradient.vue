<template>
  <div
    class="fluid-gradient"
    :style="{ ...style, ...(failed ? { background: fallbackBackground } : {}) }"
    aria-hidden="true"
  >
    <canvas ref="canvasRef" class="fluid-gradient__canvas" />
    <div v-if="$slots.default" class="fluid-gradient__content">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * FluidGradient — animated five-stop fluid background.
 *
 * Faithful port of the React baseline WebGL2 fragment shader
 * (`apps/web/src/components/fluids/fluid-gradient.tsx` at
 * d3904c2105f34e5d74f3ae3a163d6b25f075bf64): fbm + domain warping over a
 * five-stop palette with grain and vignette. Self-contained, no npm deps.
 *
 * Accessibility: when `reduced` is true — or the user asks for
 * `prefers-reduced-motion: reduce` — a single static frame is rendered and the
 * RAF loop never starts.
 */
import { computed, onMounted, onUnmounted, ref, useTemplateRef, watch } from "vue";

import { DEFAULT_FLUID_COLORS } from "./fluid-palettes";

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
  for (int i = 0; i < 3; i++) {
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

const props = withDefaults(
  defineProps<{
    colors?: string[];
    speed?: number;
    scale?: number;
    grain?: number;
    /** Disable the animation loop (reduced-motion / motion policy off). */
    reduced?: boolean;
    style?: Record<string, string | number>;
  }>(),
  {
    colors: () => [...DEFAULT_FLUID_COLORS],
    speed: 80,
    scale: 2.5,
    grain: 0.003,
    reduced: false,
    style: undefined,
  },
);

const canvasRef = useTemplateRef<HTMLCanvasElement>("canvasRef");
const failed = ref(false);
const prefersReduced = ref(false);

const effectiveReduced = computed(() => props.reduced || prefersReduced.value);
const fallbackBackground = computed(
  () => `linear-gradient(150deg, ${props.colors.join(", ")})`,
);

// GL handles live outside the reactive graph: the render loop mutates them.
let gl: WebGL2RenderingContext | null = null;
let program: WebGLProgram | null = null;
let rafId = 0;
let running = false;
let visible = true;
let started = 0;
let observer: IntersectionObserver | null = null;
let motionQuery: MediaQueryList | null = null;
let uniforms: {
  resolution: WebGLUniformLocation | null;
  time: WebGLUniformLocation | null;
  speed: WebGLUniformLocation | null;
  scale: WebGLUniformLocation | null;
  grain: WebGLUniformLocation | null;
} | null = null;
let resize = () => {};
let width = 0;
let height = 0;

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace("#", "");
  const value = parseInt(
    clean.length === 3
      ? clean
          .split("")
          .map((c) => c + c)
          .join("")
      : clean,
    16,
  );
  return [((value >> 16) & 0xff) / 255, ((value >> 8) & 0xff) / 255, (value & 0xff) / 255];
}

function compileProgram(context: WebGL2RenderingContext): WebGLProgram | null {
  function compile(type: number, source: string): WebGLShader | null {
    const shader = context.createShader(type);
    if (!shader) return null;
    context.shaderSource(shader, source);
    context.compileShader(shader);
    if (!context.getShaderParameter(shader, context.COMPILE_STATUS)) {
      context.deleteShader(shader);
      return null;
    }
    return shader;
  }

  const vs = compile(context.VERTEX_SHADER, VERT);
  const fs = compile(context.FRAGMENT_SHADER, FRAG);
  if (!vs || !fs) return null;
  const linked = context.createProgram();
  if (!linked) return null;
  context.attachShader(linked, vs);
  context.attachShader(linked, fs);
  context.linkProgram(linked);
  context.deleteShader(vs);
  context.deleteShader(fs);
  if (!context.getProgramParameter(linked, context.LINK_STATUS)) {
    context.deleteProgram(linked);
    return null;
  }
  return linked;
}

function render(elapsedMs: number) {
  if (!gl || !uniforms) return;
  gl.uniform1f(uniforms.time, elapsedMs / 1000);
  gl.uniform1f(uniforms.speed, props.speed);
  gl.uniform1f(uniforms.scale, props.scale);
  gl.uniform1f(uniforms.grain, props.grain);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
}

function frame(now: number) {
  if (visible && !document.hidden) render(now - started);
  rafId = requestAnimationFrame(frame);
}

function start() {
  if (running || !gl) return;
  running = true;
  started = performance.now();
  rafId = requestAnimationFrame(frame);
}

function stop() {
  running = false;
  if (rafId) cancelAnimationFrame(rafId);
  rafId = 0;
}

function drawStatic() {
  render(0);
}

function init() {
  const canvas = canvasRef.value;
  if (!canvas || typeof window === "undefined") return;

  let context: WebGL2RenderingContext | null = null;
  try {
    context = canvas.getContext("webgl2", {
      alpha: true,
      antialias: true,
      premultipliedAlpha: true,
    }) as WebGL2RenderingContext | null;
  } catch {
    context = null;
  }
  if (!context) {
    failed.value = true;
    return;
  }
  gl = context;

  program = compileProgram(gl);
  if (!program) {
    failed.value = true;
    return;
  }
  gl.useProgram(program);

  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const positionLoc = gl.getAttribLocation(program, "a_pos");
  gl.enableVertexAttribArray(positionLoc);
  gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0);

  const palette = props.colors.map(hexToRgb);
  gl.uniform3fv(gl.getUniformLocation(program, "u_colors"), new Float32Array(palette.flat()));

  uniforms = {
    resolution: gl.getUniformLocation(program, "u_resolution"),
    time: gl.getUniformLocation(program, "u_time"),
    speed: gl.getUniformLocation(program, "u_speed"),
    scale: gl.getUniformLocation(program, "u_scale"),
    grain: gl.getUniformLocation(program, "u_grain"),
  };

  const dpr = Math.min(window.devicePixelRatio || 1, 1.5) * 0.6;
  resize = () => {
    if (!gl || !uniforms) return;
    const nextWidth = Math.max(1, canvas.clientWidth || canvas.width || 1);
    const nextHeight = Math.max(1, canvas.clientHeight || canvas.height || 1);
    if (nextWidth === width && nextHeight === height) return;
    width = nextWidth;
    height = nextHeight;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(uniforms.resolution, canvas.width, canvas.height);
  };
  resize();

  if (typeof IntersectionObserver !== "undefined") {
    observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
    });
    observer.observe(canvas);
  }

  window.addEventListener("resize", resize);

  if (effectiveReduced.value) drawStatic();
  else start();
}

function onMotionPreferenceChange(event: MediaQueryListEvent) {
  prefersReduced.value = event.matches;
}

onMounted(() => {
  motionQuery =
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)")
      : null;
  if (motionQuery) {
    prefersReduced.value = motionQuery.matches;
    motionQuery.addEventListener("change", onMotionPreferenceChange);
  }
  init();
});

onUnmounted(() => {
  stop();
  observer?.disconnect();
  observer = null;
  window.removeEventListener("resize", resize);
  motionQuery?.removeEventListener("change", onMotionPreferenceChange);
  motionQuery = null;
  if (gl) {
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    if (program) gl.deleteProgram(program);
  }
  gl = null;
  program = null;
  uniforms = null;
});

watch(effectiveReduced, (reduced) => {
  if (reduced) {
    stop();
    drawStatic();
  } else {
    start();
  }
});

// The loop reads live props, so a palette/speed change only needs a redraw on
// the static (reduced-motion) path.
watch(
  () => [props.colors, props.speed, props.scale, props.grain],
  () => {
    if (effectiveReduced.value) drawStatic();
  },
);
</script>

<style scoped>
.fluid-gradient {
  position: relative;
  overflow: hidden;
}

.fluid-gradient__canvas {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
}

.fluid-gradient__content {
  position: relative;
  z-index: 1;
  height: 100%;
}
</style>
