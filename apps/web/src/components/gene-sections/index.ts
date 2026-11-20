/**
 * The six optional blocks of the gene detail page, one component each.
 *
 * Every one of them takes the corresponding `*_section` from the gene response
 * and nothing else: the section carries its own status, provenance and rows, so
 * a block never needs a second request to decide what to show.
 */
export { GeneAnnotationSectionCard } from "./gene-annotation-section";
export { GeneHomologSectionCard } from "./gene-homolog-section";
export { GeneExpressionSectionCard } from "./gene-expression-section";
export { GeneVariantSectionCard } from "./gene-variant-section";
export { GenePhenotypeSectionCard } from "./gene-phenotype-section";
export { GeneLiteratureSectionCard } from "./gene-literature-section";
export { SectionMissing, SectionNotice } from "./section-state";
