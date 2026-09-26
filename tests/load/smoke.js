import http from "k6/http";
import { check } from "k6";
import { Rate } from "k6/metrics";

/**
 * Smoke test - quick verification of all key endpoints.
 * 1 VU, 1 iteration, 8 endpoints.
 *
 * Run with:
 *   k6 run tests/load/smoke.js
 */

const BASE_URL = __ENV.BASE_URL || "http://localhost:8010";
const API_PREFIX = "/api/v1";

export const errorRate = new Rate("errors");

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    "errors": ["rate<0.01"],
  },
};

const smokeEndpoints = [
  // Health
  { path: "/health", name: "health" },

  // Stats
  { path: "/stats/summary", name: "stats_summary" },

  // Genes
  { path: "/genes/search?q=Glyma&page_size=5", name: "gene_search" },

  // Variants
  { path: "/variants/stats?release=v1.0", name: "variant_stats" },
  { path: "/variants/density?chromosome=Gm01&resolution=1mb&release=v1.0", name: "variant_density" },

  // Mutants
  { path: "/mutants?page_size=5", name: "mutant_list" },

  // Releases
  { path: "/releases", name: "release_list" },

  // BLAST
  { path: "/blast/databases", name: "blast_databases" },
];

export default function () {
  for (const ep of smokeEndpoints) {
    const url = `${BASE_URL}${API_PREFIX}${ep.path}`;
    const res = http.get(url, { tags: { name: ep.name } });

    const ok = check(res, {
      [`${ep.name}: status 200`]: (r) => r.status === 200,
      [`${ep.name}: valid JSON`]: (r) => {
        try {
          JSON.parse(r.body);
          return true;
        } catch {
          return false;
        }
      },
    });

    if (!ok) {
      errorRate.add(1);
      console.error(`Smoke test failed for ${ep.name}: status=${res.status}`);
    }
  }
}
