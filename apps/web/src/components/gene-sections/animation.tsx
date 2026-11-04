/**
 * The route's motion wrapper, re-exported so the section components carry one
 * import for their outer animation.
 *
 * These components render inside the gene page's `<Tabs>`, i.e. inside the
 * route's tree. They deliberately do not create their own animation context.
 */
export { ScaleIn } from "../route-motion";
