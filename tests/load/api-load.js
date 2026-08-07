import http from "k6/http";
import { check, sleep } from "k6";
import { Rate } from "k6/metrics";

/**
 * Load test for SoyMutDB API endpoints.
 * 50 VUs, 10 endpoints, p95<2s, error<1%.
 *
 * Run with:
 *   k6 run tests/load/api-load.js
 *
 * Environment variables:
 *   BASE_URL - API base URL (default: http://localhost:8000)
 *   VUS      - Virtual users (default: 50)
 *   DURATION - Test duration (default: 1m)
 */

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const API_PREFIX = "/api/v1";

export const errorRate = new Rate("errors");

export const options = {
  stages: [
    { duration: "30s", target: 20 },   // Ramp up to 20 VUs
    { duration: "1m", target: 50 },    // Ramp up to 50 VUs (steady state)
    { duration: "30s", target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ["p(95)<2000"], // 95th percentile < 2s
    "errors": ["rate<0.01"],           // Error rate < 1%
  },
};

export default function () {
  const endpoints = [
    // Health check
    { method: "GET", path: "/health", weight: 5, name: "health" },

    // Stats
    { method: "GET", path: "/stats/summary", weight: 3, name: "stats_summary" },

    // Gene search
    { method: "GET", path: "/genes/search?q=Glyma.01G&page=1&page_size=20", weight: 5, name: "gene_search" },
    { method: "GET", path: "/genes/search?q=kinase&page=1&page_size=20", weight: 3, name: "gene_search_kinase" },

    // Gene detail
    { method: "GET", path: "/genes/Glyma.01G001000", weight: 4, name: "gene_detail" },

    // Variant stats
    { method: "GET", path: "/variants/stats?gene_id=Glyma.01G001000&release=v1.0", weight: 4, name: "variant_stats_gene" },

    // Variant search
    { method: "GET", path: "/variants?gene_id=Glyma.01G001000&page_size=20&release=v1.0", weight: 5, name: "variant_list_gene" },

    // Variant density (chromosome overview)
    { method: "GET", path: "/variants/density?chromosome=Gm01&resolution=1mb&release=v1.0", weight: 2, name: "variant_density_1mb" },

    // Mutant lines
    { method: "GET", path: "/mutants?page=1&page_size=20", weight: 2, name: "mutant_list" },

    // Releases
    { method: "GET", path: "/releases", weight: 1, name: "release_list" },
  ];

  // Weighted random selection
  const totalWeight = endpoints.reduce((sum, e) => sum + e.weight, 0);
  let random = Math.random() * totalWeight;
  let selected = endpoints[0];

  for (const ep of endpoints) {
    random -= ep.weight;
    if (random <= 0) {
      selected = ep;
      break;
    }
  }

  const url = `${BASE_URL}${API_PREFIX}${selected.path}`;
  const params = {
    tags: { name: selected.name },
    headers: {
      "Accept": "application/json",
    },
  };

  const res = http.get(url, params);

  check(res, {
    "status is 200": (r) => r.status === 200,
    "response time < 2s": (r) => r.timings.duration < 2000,
  }) || errorRate.add(1);

  // Think time between requests (1-3 seconds)
  sleep(1 + Math.random() * 2);
}
