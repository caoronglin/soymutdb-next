/**
 * JBrowse 2 configuration builder for the standalone SoyMutDB genome browser.
 *
 * Builds a complete JBrowse configuration from assembly and track definitions,
 * supporting four track categories: reference, variant, annotation, quantitative.
 * Includes Trix text-search index configuration for gene/feature lookup.
 */

/** A single JBrowse track configuration. */
export interface JBrowseTrack {
    /** Unique track ID within JBrowse. */
    trackId: string;
    /** Display name. */
    name: string;
    /** JBrowse track type, e.g. "ReferenceSequenceTrack". */
    type: string;
    /** Assembly names this track belongs to. */
    assemblyNames: string[];
    /** Category path for the track selector. */
    category?: string[];
    /** Human-readable description. */
    description?: string;
    /** Adapter configuration. */
    adapter: JBrowseAdapter;
    /** Renderer configuration (for feature tracks). */
    renderer?: JBrowseRenderer;
    /** Display configurations. */
    displays?: JBrowseDisplay[];
    /** Additional metadata. */
    metadata?: Record<string, string>;
}

export interface JBrowseAdapter {
    type: string;
    [key: string]: unknown;
}

export interface JBrowseRenderer {
    type: string;
    [key: string]: unknown;
}

export interface JBrowseDisplay {
    type: string;
    displayId: string;
    [key: string]: unknown;
}

/** JBrowse assembly configuration. */
export interface JBrowseAssembly {
    name: string;
    aliases?: string[];
    sequence: {
        /** Required identifier for the reference sequence track. */
        trackId: string;
        type: string;
        adapter: JBrowseAdapter;
    };
    refNameAliases?: {
        adapter: JBrowseAdapter;
    };
}

/** Complete JBrowse configuration. */
export interface JBrowseConfig {
    assemblies: JBrowseAssembly[];
    tracks: JBrowseTrack[];
    aggregateTextSearchAdapters?: TrixSearchAdapter[];
    defaultSession?: unknown;
}

/** Trix text-search adapter for gene/feature autocomplete. */
export interface TrixSearchAdapter {
    type: "TrixTextSearchAdapter";
    textSearchAdapterId: string;
    ixFilePath: { uri: string; locationType: string };
    ixxFilePath: { uri: string; locationType: string };
    metaFilePath: { uri: string; locationType: string };
    assemblyNames: string[];
}

/**
 * Track types supported by the @soymutdb/genome-view default renderers.
 * Tracks with types outside this set are skipped by GenomeBrowser instead of
 * failing the whole view.
 */
export const SUPPORTED_TRACK_TYPES = [
    "ReferenceSequenceTrack",
    "VariantTrack",
    "FeatureTrack",
    "QuantitativeTrack",
    "AlignmentsTrack",
] as const;

/** Base URL for JBrowse data files. */
const JBROWSE_DATA_URL =
    (import.meta.env?.VITE_JBROWSE_DATA_URL as string | undefined) ??
    "/jbrowse-data";

/** Default reference assembly — soybean Williams 82 v4.0 (first/default species; more species can be added). */
export const DEFAULT_ASSEMBLY: JBrowseAssembly = {
    name: "Wm82v4.0",
    aliases: ["Glycine max v4.0", "Wm82 v4.0"],
    sequence: {
        trackId: "reference_sequence",
        type: "ReferenceSequenceTrack",
        adapter: {
            type: "BgzipFastaAdapter",
            fastaLocation: uri(`${JBROWSE_DATA_URL}/Wm82_v4.0.fa.gz`),
            faiLocation: uri(`${JBROWSE_DATA_URL}/Wm82_v4.0.fa.gz.fai`),
            gziLocation: uri(`${JBROWSE_DATA_URL}/Wm82_v4.0.fa.gz.gzi`),
        },
    },
    refNameAliases: {
        adapter: {
            type: "ChromSizesAdapter",
            sizesLocation: uri(`${JBROWSE_DATA_URL}/Wm82_v4.0.chrom.sizes`),
        },
    },
};

/**
 * Build an assembly config for the given assembly name, using default data URLs.
 * Falls back to DEFAULT_ASSEMBLY if the name is not recognised.
 */
export function buildAssembly(name: string): JBrowseAssembly {
    if (name === DEFAULT_ASSEMBLY.name) return DEFAULT_ASSEMBLY;
    // For other assembly names, clone the default but override the name.
    return {
        ...DEFAULT_ASSEMBLY,
        name,
        sequence: {
            ...DEFAULT_ASSEMBLY.sequence,
            trackId: `reference_sequence_${name.replace(/[^a-zA-Z0-9]/g, "_")}`,
        },
    };
}

/** Reference sequence track (always available). */
export const REFERENCE_TRACK: JBrowseTrack = {
    trackId: "reference_sequence",
    name: "Reference Sequence",
    type: "ReferenceSequenceTrack",
    assemblyNames: [DEFAULT_ASSEMBLY.name],
    category: ["Reference"],
    description: "Williams 82 reference genome v4.0",
    adapter: {
        type: "BgzipFastaAdapter",
        fastaLocation: uri(`${JBROWSE_DATA_URL}/Wm82_v4.0.fa.gz`),
        faiLocation: uri(`${JBROWSE_DATA_URL}/Wm82_v4.0.fa.gz.fai`),
        gziLocation: uri(`${JBROWSE_DATA_URL}/Wm82_v4.0.fa.gz.gzi`),
    },
};

/** Variant tracks (SNPs/indels + structural variants). */
export const VARIANT_TRACKS: JBrowseTrack[] = [
    {
        trackId: "variants_v4",
        name: "SNPs & Indels (v4.0)",
        type: "VariantTrack",
        assemblyNames: [DEFAULT_ASSEMBLY.name],
        category: ["Variants"],
        description: "Single nucleotide polymorphisms and indels from release v4.0",
        adapter: {
            type: "VcfTabixAdapter",
            vcfGzLocation: uri(`${JBROWSE_DATA_URL}/variants.vcf.gz`),
            index: { location: uri(`${JBROWSE_DATA_URL}/variants.vcf.gz.tbi`) },
        },
        displays: [
            {
                type: "LinearVariantDisplay",
                displayId: "variants_v4-linear",
                renderer: { type: "SvgFeatureRenderer" },
            },
        ],
    },
    {
        trackId: "sv_v4",
        name: "Structural Variants (v4.0)",
        type: "VariantTrack",
        assemblyNames: [DEFAULT_ASSEMBLY.name],
        category: ["Variants"],
        description: "Structural variants (DEL, DUP, INV, TRA) from release v4.0",
        adapter: {
            type: "VcfTabixAdapter",
            vcfGzLocation: uri(`${JBROWSE_DATA_URL}/structural_variants.vcf.gz`),
            index: {
                location: uri(`${JBROWSE_DATA_URL}/structural_variants.vcf.gz.tbi`),
            },
        },
        displays: [
            {
                type: "LinearVariantDisplay",
                displayId: "sv_v4-linear",
                renderer: { type: "SvgFeatureRenderer" },
            },
        ],
    },
];

/** Annotation tracks (gene models + repeats). */
export const ANNOTATION_TRACKS: JBrowseTrack[] = [
    {
        trackId: "gene_models",
        name: "Gene Models",
        type: "FeatureTrack",
        assemblyNames: [DEFAULT_ASSEMBLY.name],
        category: ["Annotation"],
        description: "Phytozome v13 gene annotations",
        adapter: {
            type: "Gff3TabixAdapter",
            gffGzLocation: uri(`${JBROWSE_DATA_URL}/genes.gff3.gz`),
            index: { location: uri(`${JBROWSE_DATA_URL}/genes.gff3.gz.tbi`) },
        },
        renderer: { type: "SvgFeatureRenderer" },
        displays: [
            {
                type: "LinearBasicDisplay",
                displayId: "gene_models-linear",
            },
        ],
    },
    {
        trackId: "repeats",
        name: "Repeat Regions",
        type: "FeatureTrack",
        assemblyNames: [DEFAULT_ASSEMBLY.name],
        category: ["Annotation"],
        description: "RepeatMasker repeat annotations",
        adapter: {
            type: "BigBedAdapter",
            bigBedLocation: uri(`${JBROWSE_DATA_URL}/repeats.bb`),
        },
        displays: [
            {
                type: "LinearBasicDisplay",
                displayId: "repeats-linear",
            },
        ],
    },
];

/** Quantitative tracks (GC content, expression). */
export const QUANTITATIVE_TRACKS: JBrowseTrack[] = [
    {
        trackId: "gc_content",
        name: "GC Content",
        type: "QuantitativeTrack",
        assemblyNames: [DEFAULT_ASSEMBLY.name],
        category: ["Quantitative"],
        description: "GC percentage across the genome",
        adapter: {
            type: "BigWigAdapter",
            bigWigLocation: uri(`${JBROWSE_DATA_URL}/gc_content.bw`),
        },
        displays: [
            {
                type: "LinearWiggleDisplay",
                displayId: "gc_content-linear",
            },
        ],
    },
];

/** All built-in tracks by category. */
export const ALL_TRACKS: JBrowseTrack[] = [
    REFERENCE_TRACK,
    ...VARIANT_TRACKS,
    ...ANNOTATION_TRACKS,
    ...QUANTITATIVE_TRACKS,
];

/** Default tracks shown on initial load. */
export const DEFAULT_TRACKS = ["reference_sequence", "gene_models", "variants_v4"];

/** Trix text-search adapter for gene lookup. */
export function buildTrixAdapter(assemblyName: string): TrixSearchAdapter {
    return {
        type: "TrixTextSearchAdapter",
        textSearchAdapterId: "gene_index",
        ixFilePath: uri(`${JBROWSE_DATA_URL}/genes.ix`),
        ixxFilePath: uri(`${JBROWSE_DATA_URL}/genes.ixx`),
        metaFilePath: uri(`${JBROWSE_DATA_URL}/genes_meta.json`),
        assemblyNames: [assemblyName],
    };
}

/**
 * Validate track types against supported core plugin types.
 * Tracks with unsupported types are converted to FeatureTrack with a warning.
 * This prevents the "TrackType 'undefined' not found" error at runtime.
 */
export function validateTrackTypes(tracks: JBrowseTrack[]): JBrowseTrack[] {
    const supported = new Set<string>(SUPPORTED_TRACK_TYPES);
    return tracks.map((track) => {
        if (supported.has(track.type)) return track;
        console.warn(
            `[JBrowse] Track "${track.trackId}" has unsupported type "${track.type}", falling back to FeatureTrack`,
        );
        return { ...track, type: "FeatureTrack" };
    });
}

/**
 * Build a complete JBrowse configuration from an assembly and track list.
 *
 * @param assembly Assembly configuration (defaults to Wm82v4.0).
 * @param tracks Additional tracks to include alongside the reference track.
 * @returns Complete JBrowse configuration with Trix search index.
 */
export function buildJBrowseConfig(
    assembly: JBrowseAssembly = DEFAULT_ASSEMBLY,
    tracks: JBrowseTrack[] = ALL_TRACKS,
): JBrowseConfig {
    // Ensure the reference track is always present and deduplicate by trackId.
    const seen = new Set<string>();
    const merged: JBrowseTrack[] = [];

    // Build a reference track matching the assembly name.
    const referenceTrack: JBrowseTrack = {
        ...REFERENCE_TRACK,
        trackId: assembly.sequence.trackId,
        assemblyNames: [assembly.name],
        adapter: assembly.sequence.adapter,
    };

    for (const track of [referenceTrack, ...tracks]) {
        // Override assemblyNames to match the current assembly.
        const trackWithAssembly: JBrowseTrack = {
            ...track,
            assemblyNames: [assembly.name],
        };
        if (seen.has(trackWithAssembly.trackId)) continue;
        seen.add(trackWithAssembly.trackId);
        merged.push(trackWithAssembly);
    }

    return {
        assemblies: [assembly],
        tracks: validateTrackTypes(merged),
        aggregateTextSearchAdapters: [buildTrixAdapter(assembly.name)],
        defaultSession: {
            name: "SoyMutDB",
            view: {
                id: "linear_genome_view",
                type: "LinearGenomeView",
                bpPerPx: 200,
                tracks: DEFAULT_TRACKS.map((id) => {
                    // Map "reference_sequence" to the actual reference trackId.
                    const actualId = id === "reference_sequence"
                        ? assembly.sequence.trackId
                        : id;
                    return {
                        id: actualId,
                        type: merged.find((t) => t.trackId === actualId)?.type ?? "FeatureTrack",
                        displays: [],
                    };
                }),
            },
        },
    };
}

/** Build a JBrowse theme object matching the SoyMutDB green scientific theme. */
/** Helper to create a URI location object. */
function uri(path: string): { uri: string; locationType: "UriLocation" } {
    return { uri: path, locationType: "UriLocation" };
}
