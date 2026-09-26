import http from "k6/http";
import { check, sleep } from "k6";
import { Rate } from "k6/metrics";

/**
 * Stress test for variant query endpoints - the most performance-critical path.
 * 100 VUs, 8 scenarios, p95<3s, error<2%.
 *
 * Tests variant listing with various filter combinations to ensure
 * ClickHouse query performance meets targets at scale.
 *
 * Run with:
 *   k6 run tests/load/variant-stress.js
 */

const BASE_URL = __ENV.BASE_URL || "http://localhost:8010";
const API_PREFIX = "/api/v1";

export const errorRate = new Rate("errors");

export const options = {
  stages: [
    { duration: "1m", target: 10 },    // Warm up
    { duration: "2m", target: 30 },    // Moderate load
    { duration: "2m", target: 60 },    // High load
    { duration: "1m", target: 100 },   // Spike
    { duration: "1m", target: 0 },     // Cool down
  ],
  thresholds: {
    http_req_duration: ["p(95)<3000"], // 95th percentile < 3s for variant queries
    "errors": ["rate<0.02"],           // Error rate < 2%
  },
};

const GENE_IDS = [
  "Glyma.01G001000",
  "Glyma.02G005000",
  "Glyma.05G123000",
  "Glyma.10G256000",
  "Glyma.13G042000",
  "Glyma.18G199000",
];

const CHROMOSOMES = [
  "Gm01", "Gm02", "Gm05", "Gm10", "Gm13", "Gm18",
];

const IMPACTS = ["HIGH", "MODERATE", "LOW", "MODIFIER"];
const VARIANT_TYPES = ["SNP", "INS", "DEL", "MNP"];

export default function () {
  const geneId = GENE_IDS[Math.floor(Math.random() * GENE_IDS.length)];
  const chromosome = CHROMOSOMES[Math.floor(Math.random() * CHROMOSOMES.length)];
  const impact = IMPACTS[Math.floor(Math.random() * IMPACTS.length)];
  const variantType = VARIANT_TYPES[Math.floor(Math.random() * VARIANT_TYPES.length)];

  const scenarios = [
    // 1. Simple gene variant list
    {
      name: "variants_by_gene",
      path: `/variants?gene_id=${geneId}&page_size=20&release=v1.0`,
    },
    // 2. Variant list with impact filter
    {
      name: "variants_by_gene_impact",
      path: `/variants?gene_id=${geneId}&impact=${impact}&page_size=20&release=v1.0`,
    },
    // 3. Variant list with variant type filter
    {
      name: "variants_by_type",
      path: `/variants?chromosome=${chromosome}&variant_type=${variantType}&page_size=20&release=v1.0`,
    },
    // 4. Variant stats for a gene
    {
      name: "variant_stats_gene",
      path: `/variants/stats?gene_id=${geneId}&release=v1.0`,
    },
    // 5. Variant stats for a chromosome
    {
      name: "variant_stats_chromosome",
      path: `/variants/stats?chromosome=${chromosome}&release=v1.0`,
    },
    // 6. Density at 10kb resolution (heaviest query)
    {
      name: "variant_density_10kb",
      path: `/variants/density?chromosome=${chromosome}&resolution=10kb&release=v1.0`,
    },
    // 7. Consequence matrix for a gene
    {
      name: "consequence_matrix",
      path: `/variants/consequences?gene_id=${geneId}&release=v1.0`,
    },
    // 8. Substitution spectrum
    {
      name: "substitution_spectrum",
      path: `/variants/substitution-spectrum?gene_id=${geneId}&release=v1.0`,
    },
  ];

  const scenario = scenarios[Math.floor(Math.random() * scenarios.length)];
  const url = `${BASE_URL}${API_PREFIX}${scenario.path}`;

  const params = {
    tags: { name: scenario.name },
    headers: { "Accept": "application/json" },
  };

  const res = http.get(url, params);

  check(res, {
    "status is 200 or 404": (r) => r.status === 200 || r.status === 404,
    "response time < 5s": (r) => r.timings.duration < 5000,
  }) || errorRate.add(res.status !== 404 ? 1 : 0);

  sleep(2 + Math.random() * 3);
}
