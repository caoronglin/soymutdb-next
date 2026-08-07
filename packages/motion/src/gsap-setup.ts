/**
 * GSAP setup — registers ScrollTrigger once and re-exports the configured
 * instance so every animation module shares a single, ready-to-use `gsap`.
 */
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

export { gsap, ScrollTrigger };