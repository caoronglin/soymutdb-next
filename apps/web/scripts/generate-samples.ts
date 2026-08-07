#!/usr/bin/env tsx
/**
 * Generate Sample Detail Pages
 *
 * For each variant/sample, generates a static HTML page at
 * dist/samples/{id}.html using the sample_detail widget template.
 * Also generates dist/samples/index.html (listing) and dist/sitemap.xml.
 *
 * Falls back to embedded sample data when the API is unreachable.
 */

import { writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { renderBaseTemplate, discoverAssets } from "./base-template";
import { FALLBACK_VARIANTS, renderSampleDetailHtml, type SampleVariant } from "./fallback-data";

/* ------------------------------------------------------------------ */
/*  Configuration                                                     */
/* ------------------------------------------------------------------ */

const API_BASE = process.env.SOYMUTDB_API_URL ?? "http://localhost:8000";
const DIST_DIR = join(process.cwd(), "dist");
const SAMPLES_DIR = join(DIST_DIR, "samples");
const FETCH_TIMEOUT = Number(process.env.SOYMUTDB_FETCH_TIMEOUT ?? 5000);
const SITE_URL = process.env.SOYMUTDB_SITE_URL ?? "https://soymutdb.org";

/* ------------------------------------------------------------------ */
/*  HTTP helpers                                                      */
/* ------------------------------------------------------------------ */

async function fetchVariantsFromApi(): Promise<SampleVariant[] | null> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT);
    try {
        const res = await fetch(`${API_BASE}/api/v1/variants?limit=1000`, {
            headers: { Accept: "application/json" },
            signal: ctrl.signal,
        });
        if (!res.ok) return null;
        const data = await res.json();
        // Expecting { variants: [...] } or direct array
        const list = Array.isArray(data) ? data : (data as { variants?: SampleVariant[] }).variants;
        if (!list || !Array.isArray(list)) return null;
        return list as SampleVariant[];
    } catch {
        return null;
    } finally {
        clearTimeout(timer);
    }
}

/* ------------------------------------------------------------------ */
/*  Index page listing                                                */
/* ------------------------------------------------------------------ */

function renderSampleIndex(variants: SampleVariant[]): string {
    const rows = variants
        .map(
            (v) => `
    <tr>
      <td style="padding:0.5rem;border-bottom:1px solid #eee;font-family:'JetBrains Mono',monospace;font-size:0.875rem">
        <a href="/samples/${v.id}.html" style="color:#2F6F4F;text-decoration:none">${v.id}</a>
      </td>
      <td style="padding:0.5rem;border-bottom:1px solid #eee;font-weight:600">${v.geneName}</td>
      <td style="padding:0.5rem;border-bottom:1px solid #eee;font-family:'JetBrains Mono',monospace;font-size:0.8rem;color:#666">${v.gene}</td>
      <td style="padding:0.5rem;border-bottom:1px solid #eee;font-family:'JetBrains Mono',monospace;font-size:0.8rem">${v.chromosome}</td>
      <td style="padding:0.5rem;border-bottom:1px solid #eee">${v.mutationType}</td>
      <td style="padding:0.5rem;border-bottom:1px solid #eee;color:#555">${v.phenotype}</td>
    </tr>`,
        )
        .join("");

    return `
<section style="max-width:1100px;margin:2rem auto;padding:0 1rem">
  <h1 style="font-family:'Fraunces',serif;color:#2F6F4F;margin-bottom:1rem">Sample Variants</h1>
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
                `  <url><loc>${SITE_URL}${u}</loc><lastmod>${now}</lastmod><changefreq>weekly</changefreq></url>`,
        )
        .join("\n");
    return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`;
}

/* ------------------------------------------------------------------ */
/*  Main                                                              */
/* ------------------------------------------------------------------ */

async function generate() {
    console.log(`[ssg:samples] API base: ${API_BASE}`);

    if (!existsSync(SAMPLES_DIR)) {
        mkdirSync(SAMPLES_DIR, { recursive: true });
    }

    const assets = discoverAssets();

    // Fetch variants (or fall back)
    let variants = await fetchVariantsFromApi();
    if (!variants || variants.length === 0) {
        console.warn(
            "[ssg:samples] Could not fetch variants from API — using fallback data.",
        );
        variants = FALLBACK_VARIANTS;
    }

    console.log(`[ssg:samples] Generating ${variants.length} sample pages…`);

    const sitemapUrls: string[] = [];

    for (const variant of variants) {
        const detailHtml = renderSampleDetailHtml(variant);
        const page = renderBaseTemplate({
            title: `${variant.id} — ${variant.geneName} | SoyMutDB`,
            description: `${variant.geneName} (${variant.gene}) ${variant.mutationType} on ${variant.chromosome}: ${variant.phenotype}`,
            widgetsHtml: detailHtml,
            canonical: `${SITE_URL}/samples/${variant.id}.html`,
            jsonLd: {
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
        });

        const outPath = join(SAMPLES_DIR, `${variant.id}.html`);
        writeFileSync(outPath, page, "utf8");
        sitemapUrls.push(`/samples/${variant.id}.html`);
    }

    // Index page
    const indexHtml = renderBaseTemplate({
        title: "Sample Variants — SoyMutDB",
        description: `Browse ${variants.length} pre-rendered soybean variant pages.`,
        widgetsHtml: renderSampleIndex(variants),
        canonical: `${SITE_URL}/samples/`,
        assets,
    });
    writeFileSync(join(SAMPLES_DIR, "index.html"), indexHtml, "utf8");
    sitemapUrls.push("/samples/");

    // Top-level sitemap entries for static pages too
    for (const page of ["", "about", "browse", "search", "guide", "downloads", "publications", "help"]) {
        sitemapUrls.push(page === "" ? "/" : `/${page}`);
    }

    // Write sitemap
    const sitemap = renderSitemap(sitemapUrls);
    writeFileSync(join(DIST_DIR, "sitemap.xml"), sitemap, "utf8");
    console.log(`[ssg:samples] Wrote sitemap.xml with ${sitemapUrls.length} URLs.`);

    // Write a simple robots.txt that points to the sitemap
    const robots = `User-agent: *\nAllow: /\nSitemap: ${SITE_URL}/sitemap.xml\n`;
    writeFileSync(join(DIST_DIR, "robots.txt"), robots, "utf8");
    console.log("[ssg:samples] Wrote robots.txt");

    console.log(`[ssg:samples] Done. ${variants.length} sample pages in ${SAMPLES_DIR}`);
}

generate().catch((err) => {
    console.error("[ssg:samples] Failed:", err);
    process.exit(1);
});
