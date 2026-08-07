/**
 * ============================================================================
 * ⚠️  SSG 构建期占位数据 — 仅离线构建使用，绝不用于运行时 API 失败回退！
 * ============================================================================
 *
 * 本文件只允许被 scripts/ 下的构建脚本（ssg-build.ts / generate-samples.ts）
 * 引用，用于在没有后端 API 的离线/CI 环境中产出完整的静态页面。
 *
 * 以下红线，禁止违反：
 *   - ❌ 禁止在 apps/web/src/**（运行时组件/hooks/客户端代码）import 本文件。
 *   - ❌ 禁止把 FALLBACK_VARIANTS / FALLBACK_PAGES / renderSampleDetailHtml
 *     当作 API 失败时的运行时降级数据（请用错误态 + 重试，见 DataErrorState）。
 *   - ❌ 禁止把示例统计（hero_stats 等）展示给真实用户——它们是构建占位，
 *     不是真实数据库数字。
 *
 * 如需运行时兜底，请在 src/** 中实现错误态 UI，而不是回退到本文件的示例数据。
 * ============================================================================
 *
 * Provides embedded sample variants, page layouts, and widget HTML so
 * that `ssg:build` can produce complete static pages even in an
 * offline / CI environment without a running backend.
 */

export interface SampleVariant {
    id: string;
    gene: string;
    geneName: string;
    chromosome: string;
    position: number;
    refAllele: string;
    altAllele: string;
    mutationType:
        | "SNP"
        | "INDEL"
        | "MNV"
        | "insertion"
        | "deletion"
        | "substitution";
    impact: "HIGH" | "MODERATE" | "LOW" | "MODIFIER";
    phenotype: string;
    mutagen: string;
    cultivar: string;
    referenceGenome: string;
    description: string;
    proteinChange?: string;
}

export interface WidgetLayout {
    name: string;
    data_source: "static" | "dynamic" | "external";
    cache_ttl: number;
    params?: Record<string, unknown>;
    fallback_html?: string;
}

export interface PageLayout {
    page: string;
    title: string;
    description: string;
    widgets: WidgetLayout[];
}

/* ------------------------------------------------------------------ */
/*  Sample variants (25 entries)                                      */
/* ------------------------------------------------------------------ */

export const FALLBACK_VARIANTS: SampleVariant[] = [
    {
        id: "SMDB-00001",
        gene: "Glyma.01G123400",
        geneName: "GmphyA1",
        chromosome: "Gm01",
        position: 45230012,
        refAllele: "G",
        altAllele: "A",
        mutationType: "SNP",
        impact: "HIGH",
        phenotype: "Early flowering, reduced plant height",
        mutagen: "EMS",
        cultivar: "Williams 82",
        referenceGenome: "Wm82.a4.v1",
        description:
            "Phytochrome A1 nonsense mutation causing early maturity under long-day conditions.",
        proteinChange: "p.Gln726*",
    },
    {
        id: "SMDB-00002",
        gene: "Glyma.02G034500",
        geneName: "GmFT2a",
        chromosome: "Gm02",
        position: 4890123,
        refAllele: "C",
        altAllele: "T",
        mutationType: "SNP",
        impact: "MODERATE",
        phenotype: "Delayed flowering",
        mutagen: "Fast neutron",
        cultivar: "Enrei",
        referenceGenome: "Wm82.a4.v1",
        description: "Missense variant in florigen gene FLOWERING LOCUS T 2a.",
        proteinChange: "p.Gly169Asp",
    },
    {
        id: "SMDB-00003",
        gene: "Glyma.03G223100",
        geneName: "GmGIa",
        chromosome: "Gm03",
        position: 39812345,
        refAllele: "T",
        altAllele: "A",
        mutationType: "SNP",
        impact: "HIGH",
        phenotype: "Late maturity, long juvenile",
        mutagen: "EMS",
        cultivar: "Williams 82",
        referenceGenome: "Wm82.a4.v1",
        description:
            "GIGANTEA homolog premature stop associated with long-juvenile trait.",
        proteinChange: "p.Lys821*",
    },
    {
        id: "SMDB-00004",
        gene: "Glyma.04G156400",
        geneName: "GmTfl1",
        chromosome: "Gm04",
        position: 46123098,
        refAllele: "A",
        altAllele: "G",
        mutationType: "SNP",
        impact: "MODERATE",
        phenotype: "Determinate stem growth",
        mutagen: "EMS",
        cultivar: "Hedou 12",
        referenceGenome: "Wm82.a4.v1",
        description: "TERMINAL FLOWER 1 missense mutation producing determinate habit.",
        proteinChange: "p.Arg166Gly",
    },
    {
        id: "SMDB-00005",
        gene: "Glyma.05G078900",
        geneName: "GmDtf1",
        chromosome: "Gm05",
        position: 7234567,
        refAllele: "GAAA",
        altAllele: "G",
        mutationType: "deletion",
        impact: "HIGH",
        phenotype: "Dwarf, compact internodes",
        mutagen: "Gamma ray",
        cultivar: "Peking",
        referenceGenome: "Wm82.a4.v1",
        description: "3-bp deletion in a gibberellin biosynthetic enzyme.",
    },
    {
        id: "SMDB-00006",
        gene: "Glyma.06G204300",
        geneName: "GmOle1",
        chromosome: "Gm06",
        position: 18765432,
        refAllele: "C",
        altAllele: "T",
        mutationType: "SNP",
        impact: "MODERATE",
        phenotype: "Elevated oleic acid content",
        mutagen: "EMS",
        cultivar: "Bay",
        referenceGenome: "Wm82.a4.v1",
        description: "Oleosin isoform missense increasing oleic acid ratio in seeds.",
        proteinChange: "p.Pro113Ser",
    },
    {
        id: "SMDB-00007",
        gene: "Glyma.07G092100",
        geneName: "GmF3H",
        chromosome: "Gm07",
        position: 8901234,
        refAllele: "G",
        altAllele: "A",
        mutationType: "SNP",
        impact: "HIGH",
        phenotype: "Pale flower colour (pink)",
        mutagen: "EMS",
        cultivar: "Clark",
        referenceGenome: "Wm82.a4.v1",
        description:
            "Flavanone 3-hydroxylase nonsense mutation disrupting anthocyanin pathway.",
        proteinChange: "p.Trp145*",
    },
    {
        id: "SMDB-00008",
        gene: "Glyma.08G134500",
        geneName: "GmNARK",
        chromosome: "Gm08",
        position: 10456789,
        refAllele: "T",
        altAllele: "C",
        mutationType: "SNP",
        impact: "MODERATE",
        phenotype: "Hypernodulation",
        mutagen: "EMS",
        cultivar: "Bragg",
        referenceGenome: "Wm82.a4.v1",
        description:
            "Nodule autoregulation receptor kinase missense causing uncontrolled nodule formation.",
        proteinChange: "p.Leu911Pro",
    },
    {
        id: "SMDB-00009",
        gene: "Glyma.09G011200",
        geneName: "GmRj2",
        chromosome: "Gm09",
        position: 1234567,
        refAllele: "C",
        altAllele: "T",
        mutationType: "SNP",
        impact: "HIGH",
        phenotype: "Nodulation restriction with specific Bradyrhizobium",
        mutagen: "EMS",
        cultivar: "Hardee",
        referenceGenome: "Wm82.a4.v1",
        description: "Rj2 allele blocking nodulation by incompatible rhizobial strains.",
        proteinChange: "p.Arg353*",
    },
    {
        id: "SMDB-00010",
        gene: "Glyma.10G244400",
        geneName: "GmSACPD-C",
        chromosome: "Gm10",
        position: 46789012,
        refAllele: "G",
        altAllele: "A",
        mutationType: "SNP",
        impact: "MODERATE",
        phenotype: "High stearic acid seeds",
        mutagen: "EMS",
        cultivar: "Fayette",
        referenceGenome: "Wm82.a4.v1",
        description:
            "Stearoyl-ACP desaturase missense variant raising stearic acid to ~25%.",
        proteinChange: "p.Glu200Lys",
    },
    {
        id: "SMDB-00011",
        gene: "Glyma.11G190400",
        geneName: "GmGmphyA2",
        chromosome: "Gm11",
        position: 33456789,
        refAllele: "A",
        altAllele: "T",
        mutationType: "SNP",
        impact: "HIGH",
        phenotype: "Insensitive to far-red light",
        mutagen: "Fast neutron",
        cultivar: "Harosoy",
        referenceGenome: "Wm82.a4.v1",
        description: "Phytochrome A2 paralog nonsense allele.",
        proteinChange: "p.Tyr966*",
    },
    {
        id: "SMDB-00012",
        gene: "Glyma.12G020500",
        geneName: "GmK1",
        chromosome: "Gm12",
        position: 1234567,
        refAllele: "AT",
        altAllele: "A",
        mutationType: "deletion",
        impact: "HIGH",
        phenotype: "Kunitz trypsin inhibitor null",
        mutagen: "Gamma ray",
        cultivar: "Raiden",
        referenceGenome: "Wm82.a4.v1",
        description:
            "Frameshift in Kunitz trypsin inhibitor eliminating anti-nutritional protein.",
    },
    {
        id: "SMDB-00013",
        gene: "Glyma.13G123500",
        geneName: "GmRag1",
        chromosome: "Gm13",
        position: 29876543,
        refAllele: "G",
        altAllele: "C",
        mutationType: "SNP",
        impact: "MODERATE",
        phenotype: "Soybean aphid resistance",
        mutagen: "EMS",
        cultivar: "Dowling",
        referenceGenome: "Wm82.a4.v1",
        description:
            "NLR gene allele conferring antibiosis resistance to Aphis glycines.",
        proteinChange: "p.Ser545Thr",
    },
    {
        id: "SMDB-00014",
        gene: "Glyma.14G089400",
        geneName: "GmD1",
        chromosome: "Gm14",
        position: 8123456,
        refAllele: "C",
        altAllele: "G",
        mutationType: "SNP",
        impact: "HIGH",
        phenotype: "Yellow seed coat",
        mutagen: "EMS",
        cultivar: "Williams 82",
        referenceGenome: "Wm82.a4.v1",
        description: "CHS gene cluster regulatory variant producing yellow hilum.",
        proteinChange: "p.Gln108His",
    },
    {
        id: "SMDB-00015",
        gene: "Glyma.15G122000",
        geneName: "GmLox2",
        chromosome: "Gm15",
        position: 11345678,
        refAllele: "T",
        altAllele: "A",
        mutationType: "SNP",
        impact: "HIGH",
        phenotype: "Lipoxygenase-2 null, reduced beany flavor",
        mutagen: "EMS",
        cultivar: "Ichihime",
        referenceGenome: "Wm82.a4.v1",
        description: "Nonsense mutation eliminating LOX-2 activity in seeds.",
        proteinChange: "p.Tyr482*",
    },
    {
        id: "SMDB-00016",
        gene: "Glyma.16G023200",
        geneName: "GmPdh1",
        chromosome: "Gm16",
        position: 2345678,
        refAllele: "G",
        altAllele: "A",
        mutationType: "SNP",
        impact: "MODERATE",
        phenotype: "Pubescence colour: tawny → grey",
        mutagen: "EMS",
        cultivar: "Mansoy",
        referenceGenome: "Wm82.a4.v1",
        description: "Flavonoid 3'-hydroxylase allele affecting trichome pigment.",
        proteinChange: "p.Ala304Thr",
    },
    {
        id: "SMDB-00017",
        gene: "Glyma.17G093400",
        geneName: "GmRps1k",
        chromosome: "Gm17",
        position: 8765432,
        refAllele: "C",
        altAllele: "T",
        mutationType: "SNP",
        impact: "MODERATE",
        phenotype: "Phytophthora root rot resistance",
        mutagen: "EMS",
        cultivar: "Kingwa",
        referenceGenome: "Wm82.a4.v1",
        description: "NLR allele conferring resistance to Phytophthora sojae races.",
        proteinChange: "p.Arg620Cys",
    },
    {
        id: "SMDB-00018",
        gene: "Glyma.18G273600",
        geneName: "GmD2",
        chromosome: "Gm18",
        position: 55678901,
        refAllele: "T",
        altAllele: "C",
        mutationType: "SNP",
        impact: "HIGH",
        phenotype: "Dwarf, dark green leaves, brassinosteroid insensitive",
        mutagen: "EMS",
        cultivar: "Williams 82",
        referenceGenome: "Wm82.a4.v1",
        description: "BR receptor kinase mutant with compact growth habit.",
        proteinChange: "p.Gly644Asp",
    },
    {
        id: "SMDB-00019",
        gene: "Glyma.19G112300",
        geneName: "GmPhyB1",
        chromosome: "Gm19",
        position: 35678901,
        refAllele: "G",
        altAllele: "A",
        mutationType: "SNP",
        impact: "MODERATE",
        phenotype: "Red light insensitivity, elongated internodes",
        mutagen: "EMS",
        cultivar: "L82-2024",
        referenceGenome: "Wm82.a4.v1",
        description: "Phytochrome B1 missense with altered shade avoidance.",
        proteinChange: "p.Met568Ile",
    },
    {
        id: "SMDB-00020",
        gene: "Glyma.20G116200",
        geneName: "GmKTI",
        chromosome: "Gm20",
        position: 35678901,
        refAllele: "C",
        altAllele: "T",
        mutationType: "SNP",
        impact: "LOW",
        phenotype: "Silent polymorphism",
        mutagen: "Natural variant",
        cultivar: "PI 88788",
        referenceGenome: "Wm82.a4.v1",
        description: "Synonymous variant in Kunitz inhibitor cluster.",
        proteinChange: "p.Pro32Pro",
    },
    {
        id: "SMDB-00021",
        gene: "Glyma.01G234500",
        geneName: "GmE1",
        chromosome: "Gm01",
        position: 55234567,
        refAllele: "A",
        altAllele: "T",
        mutationType: "SNP",
        impact: "HIGH",
        phenotype: "Early maturity under short photoperiod",
        mutagen: "EMS",
        cultivar: "Sakamotowase",
        referenceGenome: "Wm82.a4.v1",
        description:
            "E1 locus (legume-specific flowering repressor) loss-of-function allele.",
        proteinChange: "p.Lys159*",
    },
    {
        id: "SMDB-00022",
        gene: "Glyma.06G312000",
        geneName: "GmRhg1",
        chromosome: "Gm18",
        position: 1623456,
        refAllele: "G",
        altAllele: "C",
        mutationType: "MNV",
        impact: "HIGH",
        phenotype: "Soybean cyst nematode resistance",
        mutagen: "Natural variant",
        cultivar: "Peking",
        referenceGenome: "Wm82.a4.v1",
        description: "Multi-nucleotide variant at the Rhg1 alpha-SNAP locus.",
        proteinChange: "p.Gln201His/p.Ala211Val",
    },
    {
        id: "SMDB-00023",
        gene: "Glyma.02G234500",
        geneName: "GmMIPS1",
        chromosome: "Gm02",
        position: 42345678,
        refAllele: "G",
        altAllele: "A",
        mutationType: "SNP",
        impact: "HIGH",
        phenotype: "Low phytic acid seeds",
        mutagen: "EMS",
        cultivar: "CX1834",
        referenceGenome: "Wm82.a4.v1",
        description:
            "Myo-inositol phosphate synthase missense reducing phytic acid ~50%.",
        proteinChange: "p.Arg396Lys",
    },
    {
        id: "SMDB-00024",
        gene: "Glyma.09G045600",
        geneName: "GmW1",
        chromosome: "Gm09",
        position: 4321098,
        refAllele: "C",
        altAllele: "T",
        mutationType: "SNP",
        impact: "HIGH",
        phenotype: "White flower (loss of purple pigment)",
        mutagen: "EMS",
        cultivar: "Williams 82",
        referenceGenome: "Wm82.a4.v1",
        description:
            "Flavonoid 3'5'-hydroxylase nonsense producing white-flowered phenotype.",
        proteinChange: "p.Gln422*",
    },
    {
        id: "SMDB-00025",
        gene: "Glyma.13G345600",
        geneName: "GmFAD2-1A",
        chromosome: "Gm13",
        position: 44567890,
        refAllele: "G",
        altAllele: "A",
        mutationType: "SNP",
        impact: "HIGH",
        phenotype: "High oleic acid (>80%)",
        mutagen: "EMS",
        cultivar: "Williams 82",
        referenceGenome: "Wm82.a4.v1",
        description:
            "Fatty acid desaturase 2-1A missense; when combined with FAD2-1B produces HOLL.",
        proteinChange: "p.Asp134Asn",
    },
];

/* ------------------------------------------------------------------ */
/*  Page layouts for fallback mode                                    */
/* ------------------------------------------------------------------ */

export const FALLBACK_PAGES: PageLayout[] = [
    {
        page: "index",
        title: "SoyMutDB — Multi-Species Mutant Database",
        description:
            "A comprehensive multi-species mutant database (soybean as the first/default species) providing massive variant data, gene information, mutant resources, and a genome browser.",
        widgets: [
            {
                name: "hero_stats",
                data_source: "static",
                cache_ttl: 3600,
                fallback_html: `
<section class="widget-hero" style="padding:4rem 2rem;text-align:center">
  <h1 style="font-family:'Fraunces',serif;font-size:clamp(2rem,5vw,3.5rem);font-weight:600;color:#2F6F4F;margin:0 0 1rem">
    SoyMutDB Next
  </h1>
  <p style="font-size:1.125rem;color:#555;max-width:640px;margin:0 auto 2rem">
    A comprehensive multi-species mutant database providing variant data, gene
    information, mutant resources, and a genome browser for plant functional
    genomics research.
  </p>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem;max-width:800px;margin:0 auto">
    <div style="padding:1.5rem;border:1px solid #e0e0e0;border-radius:12px">
      <div style="font-size:2rem;font-weight:700;color:#2F6F4F">${FALLBACK_VARIANTS.length.toLocaleString()}+</div>
      <div style="color:#666">Indexed Variants</div>
    </div>
    <div style="padding:1.5rem;border:1px solid #e0e0e0;border-radius:12px">
      <div style="font-size:2rem;font-weight:700;color:#2F6F4F">20</div>
      <div style="color:#666">Chromosomes</div>
    </div>
    <div style="padding:1.5rem;border:1px solid #e0e0e0;border-radius:12px">
      <div style="font-size:2rem;font-weight:700;color:#2F6F4F">6</div>
      <div style="color:#666">Mutagens</div>
    </div>
    <div style="padding:1.5rem;border:1px solid #e0e0e0;border-radius:12px">
      <div style="font-size:2rem;font-weight:700;color:#2F6F4F">4</div>
      <div style="color:#666">Reference Genomes</div>
    </div>
  </div>
</section>`,
            },
            {
                name: "chromosome_density",
                data_source: "dynamic",
                cache_ttl: 0,
                params: { resolution: "mb" },
            },
            {
                name: "recent_releases",
                data_source: "static",
                cache_ttl: 3600,
                fallback_html: `
<section style="padding:2rem;max-width:960px;margin:0 auto">
  <h2 style="font-family:'Fraunces',serif;font-size:1.5rem;color:#2F6F4F">Recent Data Releases</h2>
  <ul style="list-style:none;padding:0">
    <li style="padding:0.75rem 0;border-bottom:1px solid #eee"><strong>v4.1</strong> — EMS mutant catalogue update (${FALLBACK_VARIANTS.length} novel variants)</li>
    <li style="padding:0.75rem 0;border-bottom:1px solid #eee"><strong>v4.0</strong> — Wm82.a4.v1 reference genome lifted annotations</li>
    <li style="padding:0.75rem 0"><strong>v3.2</strong> — Pan-genome variant set across 30 cultivars</li>
  </ul>
</section>`,
            },
        ],
    },
    {
        page: "about",
        title: "About — SoyMutDB",
        description: "About the SoyMutDB project, consortium, and methodology.",
        widgets: [
            {
                name: "about_content",
                data_source: "static",
                cache_ttl: 86400,
                fallback_html: `
<article style="max-width:768px;margin:2rem auto;padding:0 1rem;line-height:1.7">
  <h1 style="font-family:'Fraunces',serif;color:#2F6F4F">About SoyMutDB</h1>
  <p>SoyMutDB (Multi-Species Mutant Database) is a curated, open-access resource
     for chemically- and radiation-induced mutations, currently covering
     <em>Glycine max</em> (soybean) as the first/default species.</p>
  <h2>Consortium</h2>
  <p>The database is maintained by an international consortium of plant
     genetics laboratories and is released under a CC-BY 4.0 license.</p>
  <h2>Methodology</h2>
  <p>Variants are called from whole-genome sequencing of M3 mutant pools,
     aligned to the Wm82.a4.v1 reference, and annotated with SnpEff.</p>
</article>`,
            },
        ],
    },
    {
        page: "browse",
        title: "Browse Variants — SoyMutDB",
        description: "Browse variants (soybean as the current default species) by chromosome, gene, or phenotype.",
        widgets: [
            {
                name: "variant_browser",
                data_source: "dynamic",
                cache_ttl: 0,
                params: { default_limit: 50 },
            },
        ],
    },
    {
        page: "search",
        title: "Search — SoyMutDB",
        description: "Full-text and advanced search across SoyMutDB variants.",
        widgets: [
            {
                name: "search_interface",
                data_source: "dynamic",
                cache_ttl: 0,
            },
        ],
    },
    {
        page: "guide",
        title: "User Guide — SoyMutDB",
        description: "How to use SoyMutDB — tutorials, API docs, and FAQs.",
        widgets: [
            {
                name: "guide_content",
                data_source: "static",
                cache_ttl: 86400,
                fallback_html: `
<article style="max-width:768px;margin:2rem auto;padding:0 1rem;line-height:1.7">
  <h1 style="font-family:'Fraunces',serif;color:#2F6F4F">User Guide</h1>
  <h2>Quick Start</h2>
  <ol>
    <li>Use <strong>Browse</strong> to explore all variants by chromosome.</li>
    <li>Use <strong>Search</strong> for gene IDs, phenotypes, or dbSNP rsIDs.</li>
    <li>Use <strong>Downloads</strong> for bulk VCF / TSV exports.</li>
  </ol>
  <h2>API Access</h2>
  <pre style="background:#f5f5f5;padding:1rem;border-radius:8px;overflow-x:auto"><code>curl https://soymutdb.org/api/v1/variant/SMDB-00001</code></pre>
</article>`,
            },
        ],
    },
    {
        page: "downloads",
        title: "Downloads — SoyMutDB",
        description: "Bulk data downloads — VCF, TSV, GFF, and annotation tracks.",
        widgets: [
            {
                name: "download_index",
                data_source: "static",
                cache_ttl: 3600,
                fallback_html: `
<section style="max-width:768px;margin:2rem auto;padding:0 1rem">
  <h1 style="font-family:'Fraunces',serif;color:#2F6F4F">Downloads</h1>
  <table style="width:100%;border-collapse:collapse">
    <thead><tr><th style="text-align:left;padding:0.5rem;border-bottom:2px solid #2F6F4F">File</th><th style="text-align:left;padding:0.5rem;border-bottom:2px solid #2F6F4F">Format</th><th style="text-align:left;padding:0.5rem;border-bottom:2px solid #2F6F4F">Size</th></tr></thead>
    <tbody>
      <tr><td style="padding:0.5rem;border-bottom:1px solid #eee">All variants (v4.1)</td><td>VCF</td><td>128 MB</td></tr>
      <tr><td style="padding:0.5rem;border-bottom:1px solid #eee">Gene annotations</td><td>GFF3</td><td>42 MB</td></tr>
      <tr><td style="padding:0.5rem;border-bottom:1px solid #eee">SNP effects (SnpEff)</td><td>TSV</td><td>215 MB</td></tr>
      <tr><td style="padding:0.5rem">Phenotype ontology</td><td>OBO</td><td>3 MB</td></tr>
    </tbody>
  </table>
</section>`,
            },
        ],
    },
    {
        page: "publications",
        title: "Publications — SoyMutDB",
        description: "Peer-reviewed publications using or describing SoyMutDB.",
        widgets: [
            {
                name: "publication_list",
                data_source: "static",
                cache_ttl: 86400,
                fallback_html: `
<section style="max-width:768px;margin:2rem auto;padding:0 1rem">
  <h1 style="font-family:'Fraunces',serif;color:#2F6F4F">Publications</h1>
  <ul style="padding-left:1.2rem;line-height:1.7">
    <li>SoyMutDB v4: a comprehensive soybean mutant database. <em>In preparation</em>, 2026.</li>
    <li>Liu et al. A high-density EMS mutant resource for soybean functional genomics. <em>Plant Cell</em>, 2024.</li>
    <li>Wang et al. Pan-genome variation across 30 soybean cultivars. <em>Nature Comm.</em>, 2023.</li>
  </ul>
</section>`,
            },
        ],
    },
    {
        page: "help",
        title: "Help & Contact — SoyMutDB",
        description: "Support, FAQs, and contact information for SoyMutDB.",
        widgets: [
            {
                name: "help_content",
                data_source: "static",
                cache_ttl: 86400,
                fallback_html: `
<article style="max-width:768px;margin:2rem auto;padding:0 1rem;line-height:1.7">
  <h1 style="font-family:'Fraunces',serif;color:#2F6F4F">Help</h1>
  <h2>Frequently Asked Questions</h2>
  <details><summary>How do I cite SoyMutDB?</summary><p>See the Publications page.</p></details>
  <details><summary>Can I submit my own mutant data?</summary><p>Yes — contact the consortium via the link below.</p></details>
  <h2>Contact</h2>
  <p>Email: <a href="mailto:help@soymutdb.org">help@soymutdb.org</a></p>
</article>`,
            },
        ],
    },
    {
        page: "sra",
        title: "SRA Run Browser — SoyMutDB",
        description: "Look up NCBI SRA run metadata for plant sequencing runs (soybean as the current default species).",
        widgets: [
            {
                name: "sra_run",
                data_source: "dynamic",
                cache_ttl: 3600,
                params: { run: "SRR30334525" },
                fallback_html: `
<section style="max-width:960px;margin:2rem auto;padding:0 1rem">
  <h1 style="font-family:'Fraunces',serif;color:#2F6F4F">SRA Run Browser</h1>
  <p>Look up NCBI SRA sequencing run metadata. Default demo:
     <a href="https://trace.ncbi.nlm.nih.gov/Traces/sra?run=SRR30334525" style="color:#2F6F4F">SRR30334525</a>.</p>
  <p><em>Enable JavaScript for the interactive browser.</em></p>
</section>`,
            },
        ],
    },
    {
        page: "compare",
        title: "Variant Comparison — SoyMutDB",
        description: "Side-by-side comparison of mutant variants with impact distribution charts.",
        widgets: [
            {
                name: "compare_intro",
                data_source: "static",
                cache_ttl: 86400,
                fallback_html: `
<section style="max-width:960px;margin:2rem auto;padding:0 1rem;line-height:1.7">
  <h1 style="font-family:'Fraunces',serif;color:#2F6F4F">Variant Comparison</h1>
  <p>Select 2–4 variants to compare gene, impact, mutagen, and phenotype side-by-side.</p>
  <p><em>Enable JavaScript for the interactive comparison tool.</em></p>
</section>`,
            },
        ],
    },
];

/* ------------------------------------------------------------------ */
/*  Sample detail widget HTML (used by generate-samples)              */
/* ------------------------------------------------------------------ */

export function renderSampleDetailHtml(variant: SampleVariant): string {
    const impactColor =
        variant.impact === "HIGH"
            ? "#c0392b"
            : variant.impact === "MODERATE"
              ? "#e67e22"
              : variant.impact === "LOW"
                ? "#f39c12"
                : "#7f8c8d";

    return `
<article class="sample-detail" style="max-width:800px;margin:2rem auto;padding:0 1rem;line-height:1.7">
  <header style="margin-bottom:1.5rem">
    <div style="font-family:'JetBrains Mono',monospace;font-size:0.875rem;color:#777">${variant.id}</div>
    <h1 style="font-family:'Fraunces',serif;font-size:2rem;color:#2F6F4F;margin:0.25rem 0">
      ${variant.geneName} <span style="font-weight:400;color:#555">(${variant.gene})</span>
    </h1>
    <span style="display:inline-block;padding:0.25rem 0.75rem;border-radius:999px;background:${impactColor};color:#fff;font-size:0.75rem;font-weight:600;text-transform:uppercase">
      ${variant.impact} impact
    </span>
  </header>

  <p style="font-size:1.1rem;color:#333">${variant.description}</p>

  <dl style="display:grid;grid-template-columns:max-content 1fr;gap:0.5rem 1.5rem;margin:1.5rem 0;padding:1rem;background:#f8f8f5;border-radius:8px">
    <dt style="font-weight:600;color:#555">Chromosome</dt><dd style="font-family:'JetBrains Mono',monospace">${variant.chromosome}:${variant.position.toLocaleString()}</dd>
    <dt style="font-weight:600;color:#555">Ref / Alt</dt><dd style="font-family:'JetBrains Mono',monospace">${variant.refAllele} → ${variant.altAllele} (${variant.mutationType})</dd>
    ${variant.proteinChange ? `<dt style="font-weight:600;color:#555">Protein</dt><dd style="font-family:'JetBrains Mono',monospace">${variant.proteinChange}</dd>` : ""}
    <dt style="font-weight:600;color:#555">Phenotype</dt><dd>${variant.phenotype}</dd>
    <dt style="font-weight:600;color:#555">Mutagen</dt><dd>${variant.mutagen}</dd>
    <dt style="font-weight:600;color:#555">Cultivar</dt><dd>${variant.cultivar}</dd>
    <dt style="font-weight:600;color:#555">Reference</dt><dd>${variant.referenceGenome}</dd>
  </dl>

  <nav style="margin-top:2rem;display:flex;gap:1rem">
    <a href="/browse" style="color:#2F6F4F;text-decoration:none;font-weight:600">← Browse all variants</a>
    <a href="/search" style="color:#2F6F4F;text-decoration:none;font-weight:600">Search →</a>
  </nav>
</article>`;
}
