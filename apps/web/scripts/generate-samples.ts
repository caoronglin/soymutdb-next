#!/usr/bin/env tsx
/**
 * Generate Sample Detail Pages
 *
 * For each variant/sample, generates a static HTML page at
 * dist/samples/{id}.html using the sample_detail widget template.
 * Also generates dist/samples/index.html (listing). Only release artifacts
 * include dist/sitemap.xml; demo and preview artifacts deliberately do not.
 *
 * Production builds fail closed when release data is unavailable. Embedded
 * fixtures are available only when VITE_DEPLOYMENT_MODE=demo.
 */

import { writeFileSync, mkdirSync, existsSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { renderBaseTemplate, discoverAssets } from "./base-template";
import { FALLBACK_VARIANTS, renderSampleDetailHtml, type SampleVariant } from "./fallback-data";
import { normalizeBasePath, resolveAppUrl, resolveDeploymentMode } from "../src/lib/deployment";

/* ------------------------------------------------------------------ */
/*  Configuration                                                     */
/* ------------------------------------------------------------------ */

const API_BASE = (process.env.VITE_API_BASE_URL ?? process.env.SOYMUTDB_API_URL ?? "").trim();
const DIST_DIR = join(process.cwd(), "dist");
const SAMPLES_DIR = join(DIST_DIR, "samples");
const FETCH_TIMEOUT = Number(process.env.SOYMUTDB_FETCH_TIMEOUT ?? 5000);
const SITE_URL = process.env.SOYMUTDB_SITE_URL ?? "https://soymutdb.org";
const BASE_PATH = normalizeBasePath(process.env.VITE_BASE_URL ?? "/");
const DEMO_MODE = resolveDeploymentMode(process.env.VITE_DEPLOYMENT_MODE) === "demo";
const PUBLICATION_MODE = resolvePublicationMode(process.env.SOYMUTDB_PUBLICATION_MODE, DEMO_MODE);
const NON_RELEASE_MODE = PUBLICATION_MODE !== "release";
const SAFE_SAMPLE_ID = /^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$/;
const SITEMAP_PATH = join(DIST_DIR, "sitemap.xml");

type PublicationMode = "release" | "preview" | "demo";

function resolvePublicationMode(value: string | undefined, demoDeployment: boolean): PublicationMode {
    switch (value?.trim().toLowerCase()) {
        case "preview":
            return "preview";
        case "demo":
            return "demo";
        case "release":
        case undefined:
        case "":
            return demoDeployment ? "demo" : "release";
        default:
            throw new Error(`Unsupported SOYMUTDB_PUBLICATION_MODE: ${value}`);
    }
}

interface ApiVariantListResponse {
    items?: unknown;
}

type ApiVariant = Record<string, unknown>;

function requiredString(item: ApiVariant, field: string): string {
    const value = item[field];
    if (typeof value !== "string" || !value.trim()) {
        throw new Error(`Variant API item has invalid ${field}`);
    }
    return value.trim();
}

function optionalString(item: ApiVariant, field: string): string | undefined {
    const value = item[field];
    return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function mapApiVariant(value: unknown): SampleVariant {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
        throw new Error("Variant API returned a non-object item");
    }
    const item = value as ApiVariant;
    const id = optionalString(item, "variant_id") ?? requiredString(item, "id");
    if (!SAFE_SAMPLE_ID.test(id)) throw new Error(`Invalid variant ID: ${id}`);

    const chromosome = requiredString(item, "chromosome");
    const position = item.position;
    if (!Number.isSafeInteger(position) || (position as number) < 0) {
        throw new Error(`Variant API item ${id} has invalid position`);
    }
    const mutationType = requiredString(item, "variant_type");
    if (!["SNP", "INS", "DEL", "MNV", "SV"].includes(mutationType)) {
        throw new Error(`Variant API item ${id} has invalid variant_type`);
    }
    const rawImpact = optionalString(item, "impact") ?? "UNKNOWN";
    if (!["HIGH", "MODERATE", "LOW", "MODIFIER", "UNKNOWN"].includes(rawImpact)) {
        throw new Error(`Variant API item ${id} has invalid impact`);
    }

    const gene = optionalString(item, "gene_id") ?? "Not annotated";
    const geneName = optionalString(item, "gene_symbol") ?? gene;
    const refAllele = requiredString(item, "ref_allele");
    const altAllele = requiredString(item, "alt_allele");
    const unavailable = "Not provided by variant list API";

    return {
        id,
        gene,
        geneName,
        chromosome,
        position: position as number,
        refAllele,
        altAllele,
        mutationType: mutationType as SampleVariant["mutationType"],
        impact: rawImpact as SampleVariant["impact"],
        phenotype: optionalString(item, "phenotype") ?? unavailable,
        mutagen: optionalString(item, "mutagen") ?? unavailable,
        cultivar: optionalString(item, "cultivar") ?? unavailable,
        referenceGenome: optionalString(item, "assembly_id") ?? unavailable,
        description:
            optionalString(item, "description") ??
            `Variant ${id}: ${refAllele} to ${altAllele} at ${chromosome}:${position}.`,
        proteinChange: optionalString(item, "hgvs_p"),
    };
}

function variantsEndpoint(): string {
    if (!API_BASE) throw new Error("Variant API base URL is required for production SSG");
    const apiUrl = new URL(API_BASE);
    const apiPath = apiUrl.pathname.replace(/\/+$/, "");
    apiUrl.pathname = `${apiPath.endsWith("/api/v1") ? apiPath : `${apiPath}/api/v1`}/variants`;
    apiUrl.search = "";
    apiUrl.searchParams.set("limit", "200");
    return apiUrl.toString();
}

/* ------------------------------------------------------------------ */
/*  HTTP helpers                                                      */
/* ------------------------------------------------------------------ */

async function fetchVariantsFromApi(): Promise<SampleVariant[]> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT);
    try {
        const endpoint = variantsEndpoint();
        console.log(`[ssg:samples] Fetching ${endpoint}`);
        const res = await fetch(endpoint, {
            headers: { Accept: "application/json" },
            signal: ctrl.signal,
        });
        if (!res.ok) throw new Error(`Variant API returned HTTP ${res.status}`);
        const data = await res.json() as ApiVariantListResponse;
        if (!Array.isArray(data.items)) {
            throw new Error("Variant API response does not contain an items array");
        }
        const variants = data.items.map(mapApiVariant);
        if (variants.length === 0) throw new Error("Variant API returned no release variants");
        return variants;
    } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        throw new Error(`Variant API unavailable or invalid: ${message}`, { cause: error });
    } finally {
        clearTimeout(timer);
    }
}

/* ------------------------------------------------------------------ */
/*  Index page listing                                                */
/* ------------------------------------------------------------------ */

function escapeHtmlText(value: string): string {
    return value
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#x27;");
}

function renderSampleIndex(variants: SampleVariant[], demo: boolean): string {
    const rows = variants
        .map(
            (v) => `
    <tr>
      <td style="padding:0.5rem;border-bottom:1px solid #eee;font-family:'JetBrains Mono',monospace;font-size:0.875rem">
        <a href="${escapeHtmlText(resolveAppUrl(BASE_PATH, `samples/${v.id}.html`))}" style="color:#2F6F4F;text-decoration:none">${escapeHtmlText(v.id)}</a>
      </td>
      <td style="padding:0.5rem;border-bottom:1px solid #eee;font-weight:600">${escapeHtmlText(v.geneName)}</td>
      <td style="padding:0.5rem;border-bottom:1px solid #eee;font-family:'JetBrains Mono',monospace;font-size:0.8rem;color:#666">${escapeHtmlText(v.gene)}</td>
      <td style="padding:0.5rem;border-bottom:1px solid #eee;font-family:'JetBrains Mono',monospace;font-size:0.8rem">${escapeHtmlText(v.chromosome)}</td>
      <td style="padding:0.5rem;border-bottom:1px solid #eee">${escapeHtmlText(v.mutationType)}</td>
      <td style="padding:0.5rem;border-bottom:1px solid #eee;color:#555">${escapeHtmlText(v.phenotype)}</td>
    </tr>`,
        )
        .join("");

    return `
<section style="max-width:1100px;margin:2rem auto;padding:0 1rem">
  <h1 style="font-family:'Fraunces',serif;color:#2F6F4F;margin-bottom:1rem">Sample Variants</h1>
  ${demo ? '<aside role="note" style="padding:0.75rem 1rem;background:#fff3cd;border:1px solid #e0b100;border-radius:6px"><strong>Demo fixture — demonstration data:</strong> these records are not published scientific release data.</aside>' : ""}
  <p style="color:#666;margin-bottom:1.5rem">${variants.length} variants available as static pre-rendered pages.</p>
  <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:0.9rem">
      <thead>
        <tr>
          <th style="text-align:left;padding:0.5rem;border-bottom:2px solid #2F6F4F">ID</th>
          <th style="text-align:left;padding:0.5rem;border-bottom:2px solid #2F6F4F">Gene</th>
          <th style="text-align:left;padding:0.5rem;border-bottom:2px solid #2F6F4F">Locus</th>
          <th style="text-align:left;padding:0.5rem;border-bottom:2px solid #2F6F4F">Chr</th>
          <th style="text-align:left;padding:0.5rem;border-bottom:2px solid #2F6F4F">Type</th>
          <th style="text-align:left;padding:0.5rem;border-bottom:2px solid #2F6F4F">Phenotype</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
</section>`;
}

/* ------------------------------------------------------------------ */
/*  Sitemap                                                           */
/* ------------------------------------------------------------------ */

function renderSitemap(urls: string[]): string {
    const now = new Date().toISOString().split("T")[0];
    const body = urls
        .map(
            (u) =>
                `  <url><loc>${escapeXml(resolveSiteUrl(u))}</loc><lastmod>${now}</lastmod><changefreq>weekly</changefreq></url>`,
        )
        .join("\n");
    return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`;
}

function resolveSiteUrl(path: string): string {
    const site = new URL(SITE_URL);
    if (site.protocol !== "https:" && site.protocol !== "http:") {
        throw new Error("SOYMUTDB_SITE_URL must use http or https");
    }
    return new URL(resolveAppUrl(BASE_PATH, path), site.origin).toString();
}

function escapeXml(value: string): string {
    return value
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&apos;");
}

/* ------------------------------------------------------------------ */
/*  Main                                                              */
/* ------------------------------------------------------------------ */

async function generate() {
    console.log(
        `[ssg:samples] Mode: ${DEMO_MODE ? "demo fixtures" : "release API"}; publication: ${PUBLICATION_MODE}`,
    );

    const variants = DEMO_MODE ? FALLBACK_VARIANTS : await fetchVariantsFromApi();

    if (!existsSync(SAMPLES_DIR)) {
        mkdirSync(SAMPLES_DIR, { recursive: true });
    }

    const assets = discoverAssets();

    console.log(`[ssg:samples] Generating ${variants.length} sample pages…`);

    const sitemapUrls: string[] = [];

    for (const variant of variants) {
        if (!SAFE_SAMPLE_ID.test(variant.id)) {
            throw new Error(`Invalid variant ID: ${variant.id}`);
        }
        const detailHtml = `${DEMO_MODE ? '<aside role="note" style="max-width:800px;margin:1rem auto;padding:0.75rem 1rem;background:#fff3cd;border:1px solid #e0b100;border-radius:6px"><strong>Demo fixture — demonstration data:</strong> this record is not published scientific release data.</aside>' : ""}${renderSampleDetailHtml(variant, BASE_PATH)}`;
        const samplePath = `samples/${variant.id}.html`;
        const page = renderBaseTemplate({
            title: `${variant.id} — ${variant.geneName} | SoyMutDB`,
            description: `${variant.geneName} (${variant.gene}) ${variant.mutationType} on ${variant.chromosome}: ${variant.phenotype}`,
            widgetsHtml: detailHtml,
            canonical: NON_RELEASE_MODE ? undefined : resolveSiteUrl(samplePath),
            jsonLd: NON_RELEASE_MODE ? undefined : {
                "@context": "https://schema.org",
                "@type": "Dataset",
                name: `${variant.id} — ${variant.geneName}`,
                description: variant.description,
                identifier: variant.id,
                genre: "GenomicVariant",
                keywords: [
                    "soybean",
                    "Glycine max",
                    variant.geneName,
                    variant.mutationType,
                    variant.phenotype,
                ],
            },
            assets,
            robots: NON_RELEASE_MODE ? "noindex, nofollow" : undefined,
            pagePath: resolveAppUrl(BASE_PATH, samplePath),
            // /samples/*.html is a deliberately standalone static namespace;
            // there is no matching TanStack Router route to mount safely.
            spaEntrypoint: false,
        });

        const outPath = join(SAMPLES_DIR, `${variant.id}.html`);
        writeFileSync(outPath, page, "utf8");
        if (!NON_RELEASE_MODE) sitemapUrls.push(samplePath);
    }

    // Index page
    const indexHtml = renderBaseTemplate({
        title: "Sample Variants — SoyMutDB",
        description: `Browse ${variants.length} pre-rendered soybean variant pages (current default species).`,
        widgetsHtml: renderSampleIndex(variants, DEMO_MODE),
        canonical: NON_RELEASE_MODE ? undefined : resolveSiteUrl("samples/"),
        assets,
        robots: NON_RELEASE_MODE ? "noindex, nofollow" : undefined,
        pagePath: resolveAppUrl(BASE_PATH, "samples/"),
        spaEntrypoint: false,
    });
    writeFileSync(join(SAMPLES_DIR, "index.html"), indexHtml, "utf8");
    if (!NON_RELEASE_MODE) sitemapUrls.push("samples/");

    if (NON_RELEASE_MODE) {
        if (existsSync(SITEMAP_PATH)) unlinkSync(SITEMAP_PATH);
        console.log("[ssg:samples] Omitted sitemap.xml for non-release publication.");
    } else {
        // Top-level sitemap entries for static pages too
        for (const page of ["", "about", "browser", "search", "guide", "downloads", "publications", "help"]) {
            sitemapUrls.push(page);
        }

        const sitemap = renderSitemap(sitemapUrls);
        writeFileSync(SITEMAP_PATH, sitemap, "utf8");
        console.log(`[ssg:samples] Wrote sitemap.xml with ${sitemapUrls.length} URLs.`);
    }

    // `noindex` and `nofollow` are emitted as page-level meta directives;
    // robots.txt denies all crawling for defense in depth on non-release artifacts.
    const robots = NON_RELEASE_MODE
        ? "# Non-release artifact: HTML pages declare noindex, nofollow.\nUser-agent: *\nDisallow: /\n"
        : `User-agent: *\nAllow: ${BASE_PATH}\nSitemap: ${resolveSiteUrl("sitemap.xml")}\n`;
    writeFileSync(join(DIST_DIR, "robots.txt"), robots, "utf8");
    console.log("[ssg:samples] Wrote robots.txt");

    console.log(`[ssg:samples] Done. ${variants.length} sample pages in ${SAMPLES_DIR}`);
}

generate().catch((err) => {
    const message = err instanceof Error ? err.message : String(err);
    process.stderr.write(
        `[ssg:samples] Failed: production sample generation requires available API release data. ${message}\n`,
    );
    process.exitCode = 1;
});
