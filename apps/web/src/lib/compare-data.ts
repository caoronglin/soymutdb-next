/**
 * Embedded comparison dataset for the /compare page.
 *
 * A small curated subset of well-characterised soybean mutant variants
 * that works offline and during SSG. The live API is preferred when
 * available; this file is the graceful-degradation fallback.
 */

export interface CompareVariant {
  id: string;
  gene: string;
  geneName: string;
  chromosome: string;
  position: number;
  refAllele: string;
  altAllele: string;
  mutationType: "SNP" | "INDEL" | "insertion" | "deletion" | "substitution" | "MNV";
  impact: "HIGH" | "MODERATE" | "LOW" | "MODIFIER";
  phenotype: string;
  mutagen: string;
  cultivar: string;
  proteinChange?: string;
}

export const COMPARE_VARIANTS: CompareVariant[] = [
  {
    id: "SMDB-00001", gene: "Glyma.01G123400", geneName: "GmphyA1",
    chromosome: "Gm01", position: 45230012, refAllele: "G", altAllele: "A",
    mutationType: "SNP", impact: "HIGH",
    phenotype: "Early flowering, reduced plant height",
    mutagen: "EMS", cultivar: "Williams 82", proteinChange: "G1057R",
  },
  {
    id: "SMDB-00002", gene: "Glyma.02G222300", geneName: "GmFT2a",
    chromosome: "Gm02", position: 33450123, refAllele: "C", altAllele: "T",
    mutationType: "SNP", impact: "MODERATE",
    phenotype: "Delayed flowering under long days",
    mutagen: "Fast neutron", cultivar: "Williams 82", proteinChange: "P73L",
  },
  {
    id: "SMDB-00003", gene: "Glyma.04G156400", geneName: "GmAGL1",
    chromosome: "Gm04", position: 39120890, refAllele: "A", altAllele: "G",
    mutationType: "SNP", impact: "LOW",
    phenotype: "Subtle floral morphology change",
    mutagen: "EMS", cultivar: "Jack", proteinChange: "K123E",
  },
  {
    id: "SMDB-00004", gene: "Glyma.06G207800", geneName: "E1",
    chromosome: "Gm06", position: 20006753, refAllele: "T", altAllele: "C",
    mutationType: "SNP", impact: "HIGH",
    phenotype: "Early maturity, determinate growth",
    mutagen: "EMS", cultivar: "Williams 82", proteinChange: "R15W",
  },
  {
    id: "SMDB-00005", gene: "Glyma.08G359700", geneName: "GmGmphyA3",
    chromosome: "Gm08", position: 46580223, refAllele: "G", altAllele: "A",
    mutationType: "SNP", impact: "MODERATE",
    phenotype: "Insensitive to far-red light",
    mutagen: "EMS", cultivar: "Williams 82", proteinChange: "G1076R",
  },
  {
    id: "SMDB-00006", gene: "Glyma.10G221500", geneName: "GmFT5a",
    chromosome: "Gm10", position: 44780112, refAllele: "C", altAllele: "T",
    mutationType: "SNP", impact: "MODERATE",
    phenotype: "Late flowering under SD conditions",
    mutagen: "Gamma ray", cultivar: "Enrei", proteinChange: "A133V",
  },
  {
    id: "SMDB-00007", gene: "Glyma.12G073900", geneName: "GmDtf1",
    chromosome: "Gm12", position: 5490876, refAllele: "G", altAllele: "A",
    mutationType: "SNP", impact: "HIGH",
    phenotype: "Determinate stem growth",
    mutagen: "EMS", cultivar: "Williams 82", proteinChange: "G81E",
  },
  {
    id: "SMDB-00008", gene: "Glyma.13G278600", geneName: "GmTfl1",
    chromosome: "Gm13", position: 29980234, refAllele: "C", altAllele: "T",
    mutationType: "SNP", impact: "HIGH",
    phenotype: "Determinate habit, terminal flower",
    mutagen: "EMS", cultivar: "Williams 82", proteinChange: "R134*",
  },
  {
    id: "SMDB-00009", gene: "Glyma.15G228200", geneName: "GmNARK",
    chromosome: "Gm15", position: 36120345, refAllele: "A", altAllele: "T",
    mutationType: "INDEL", impact: "HIGH",
    phenotype: "Supernodulation, nitrate-tolerant symbiosis",
    mutagen: "EMS", cultivar: "Bragg", proteinChange: "K606*",
  },
  {
    id: "SMDB-00010", gene: "Glyma.16G163200", geneName: "GmGmGI",
    chromosome: "Gm16", position: 30982012, refAllele: "T", altAllele: "C",
    mutationType: "SNP", impact: "MODERATE",
    phenotype: "Late flowering under LD",
    mutagen: "Fast neutron", cultivar: "Williams 82", proteinChange: "M406T",
  },
  {
    id: "SMDB-00011", gene: "Glyma.19G194300", geneName: "GmDtf2",
    chromosome: "Gm19", position: 40892011, refAllele: "G", altAllele: "A",
    mutationType: "SNP", impact: "MODERATE",
    phenotype: "Semi-determinate growth habit",
    mutagen: "EMS", cultivar: "Harosoy", proteinChange: "G169R",
  },
  {
    id: "SMDB-00012", gene: "Glyma.20G090000", geneName: "GmSACPD-C",
    chromosome: "Gm20", position: 33120980, refAllele: "C", altAllele: "T",
    mutationType: "SNP", impact: "HIGH",
    phenotype: "Elevated stearic acid in seeds",
    mutagen: "EMS", cultivar: "Bay", proteinChange: "P225S",
  },
];
