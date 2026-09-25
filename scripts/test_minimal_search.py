"""Focused tests for the local unpublished-data search preview."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scripts import minimal_search

GENE_A = "Glyma.01G000100.Wm82.a6.v1"
GENE_B = "Glyma.01G000200.Wm82.a6.v1"
HEADERS = [
    "株系",
    "突变体系（株系母+位置）",
    "染色体号",
    "位点",
    "可信度（高/中/低）",
    "基因号",
    "特征",
    "可获得",
    "W82_V4",
]


def write_fixture(root: Path, sites: list[dict[str, str]] | None = None) -> Path:
    annotation_dir = root / "01_annot"
    mutation_dir = root / "02_mut-infor"
    annotation_dir.mkdir(parents=True)
    mutation_dir.mkdir(parents=True)
    (annotation_dir / "Gmax_880_v6.0.fa.fai").write_text(
        "Gm01\t1000\t0\t60\t61\nGm02\t800\t1000\t60\t61\n", encoding="utf-8"
    )
    (annotation_dir / "Gmax_880_Wm82.a6.v1.gene.gff3").write_text(
        "##gff-version 3\n"
        "##assembly-version v6.0\n"
        "##annot-version Wm82.a6.v1\n"
        f"Gm01\tref\tgene\t100\t200\t.\t+\t.\tID={GENE_A};Name=Gene A\n"
        f"Gm01\tref\tgene\t300\t400\t.\t-\t.\tID={GENE_B};Name=Gene B\n",
        encoding="utf-8",
    )
    rows = sites or [
        {
            "株系": "LINE-1",
            "突变体系（株系母+位置）": "TEST-Gm01-150",
            "染色体号": "Gm01",
            "位点": "150",
            "可信度（高/中/低）": "H",
            "基因号": GENE_A,
            "特征": "gene|50",
            "可获得": "Y",
            "W82_V4": "",
        },
        {
            "株系": "LINE-1",
            "突变体系（株系母+位置）": "TEST-Gm01-250",
            "染色体号": "Gm01",
            "位点": "250",
            "可信度（高/中/低）": "L",
            "基因号": GENE_A,
            "特征": "us|-50",
            "可获得": "N",
            "W82_V4": "Glyma.01G100000.Wm82.a4.v1",
        },
        {
            "株系": "LINE-2",
            "突变体系（株系母+位置）": "TEST-Gm01-350",
            "染色体号": "Gm01",
            "位点": "350",
            "可信度（高/中/低）": "M",
            "基因号": GENE_B,
            "特征": "gene|0",
            "可获得": "Y",
            "W82_V4": "",
        },
    ]
    with (mutation_dir / "mu-infor_Gmax_880_Wm82-test.txt").open("w", encoding="utf-8", newline="") as handle:
        handle.write("\t".join(HEADERS) + "\n")
        for row in rows:
            handle.write("\t".join(row[column] for column in HEADERS) + "\n")
    return root


class DatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = write_fixture(Path(self.temp_dir.name))
        self.index = minimal_search.SearchIndex(self.data_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_gene_id_search_and_inclusive_overlap_filter(self) -> None:
        result = self.index.search_genes(GENE_A.casefold(), "Gm01", None, None, 1, 20)
        self.assertEqual([item["gene_id"] for item in result["items"]], [GENE_A])
        # Both gene intervals touch the 200..300 interval at an inclusive edge.
        overlap = self.index.search_genes("", "Gm01", 200, 300, 1, 20)
        self.assertEqual({item["gene_id"] for item in overlap["items"]}, {GENE_A, GENE_B})

    def test_test_site_search_preserves_source_annotation_outside_gene_span(self) -> None:
        result = self.index.search_test_sites("Gm01", 250, 250, "", "", "", "", 1, 20)
        item = result["items"][0]
        self.assertEqual(item["gene_id"], GENE_A)
        self.assertEqual(item["feature"], "us|-50")
        self.assertEqual(item["gene_span_relation"], "outside_annotated_gene_span")
        self.assertEqual(item["gene_start"], 100)
        self.assertEqual(item["gene_end"], 200)

    def test_tsv_gene_chromosome_mismatch_rejects_the_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_fixture(Path(tmp), [
                {
                    "株系": "LINE-1",
                    "突变体系（株系母+位置）": "TEST-Gm02-150",
                    "染色体号": "Gm02",
                    "位点": "150",
                    "可信度（高/中/低）": "H",
                    "基因号": GENE_A,
                    "特征": "us|-50",
                    "可获得": "Y",
                    "W82_V4": "",
                }
            ])
            with self.assertRaisesRegex(minimal_search.DatasetError, "is on Gm01, not Gm02"):
                minimal_search.SearchIndex(root)

    def test_tsv_unmatched_gene_id_rejects_the_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_fixture(Path(tmp), [
                {
                    "株系": "LINE-1",
                    "突变体系（株系母+位置）": "TEST-Gm01-150",
                    "染色体号": "Gm01",
                    "位点": "150",
                    "可信度（高/中/低）": "H",
                    "基因号": "not-a-gff-id",
                    "特征": "gene|0",
                    "可获得": "Y",
                    "W82_V4": "",
                }
            ])
            with self.assertRaisesRegex(minimal_search.DatasetError, "has no exact GFF3 match"):
                minimal_search.SearchIndex(root)

    def test_out_of_reference_coordinate_rejects_the_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_fixture(Path(tmp), [
                {
                    "株系": "LINE-1",
                    "突变体系（株系母+位置）": "TEST-Gm01-1001",
                    "染色体号": "Gm01",
                    "位点": "1001",
                    "可信度（高/中/低）": "H",
                    "基因号": GENE_A,
                    "特征": "ds|0",
                    "可获得": "Y",
                    "W82_V4": "",
                }
            ])
            with self.assertRaisesRegex(minimal_search.DatasetError, "position is outside Gm01"):
                minimal_search.SearchIndex(root)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.index = minimal_search.SearchIndex(write_fixture(Path(cls.temp_dir.name)))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), minimal_search.make_handler(cls.index))
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temp_dir.cleanup()

    def get(self, path: str):
        try:
            return urlopen(self.base_url + path, timeout=3)
        except HTTPError as error:
            return error

    def test_meta_and_success_responses_include_provenance_and_security_headers(self) -> None:
        response = self.get("/api/meta")
        payload = json.loads(response.read())
        self.assertEqual(payload["assembly"], "Gmax_880_v6.0")
        self.assertEqual(payload["annotation"], "Wm82.a6.v1")
        self.assertEqual(payload["publication_status"], "unpublished_test_data")
        self.assertEqual(payload["record_kind"], "test_site")
        self.assertFalse(payload["has_ref_alt"])
        self.assertEqual(payload["test_site_count"], 3)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_gene_and_position_search_with_filter_and_pagination(self) -> None:
        response = self.get("/api/genes?" + urlencode({"query": "Gene A", "page_size": "1"}))
        genes = json.loads(response.read())
        self.assertEqual(genes["total"], 1)
        self.assertEqual(genes["items"][0]["gene_id"], GENE_A)
        self.assertEqual(genes["publication_status"], "unpublished_test_data")
        self.assertEqual(genes["coordinate_system"], "1-based-inclusive")

        response = self.get("/api/test-sites?" + urlencode({
            "chromosome": "Gm01", "start": "100", "end": "300", "confidence": "L",
            "available": "N", "page": "1", "page_size": "1",
        }))
        sites = json.loads(response.read())
        self.assertEqual(sites["total"], 1)
        self.assertEqual(sites["items"][0]["test_site_id"], "TEST-Gm01-250")
        self.assertEqual(sites["items"][0]["gene_id"], GENE_A)
        self.assertEqual(sites["items"][0]["feature"], "us|-50")
        self.assertEqual(sites["items"][0]["gene_span_relation"], "outside_annotated_gene_span")
        self.assertEqual(sites["coordinate_system"], "1-based-inclusive")

    def test_invalid_or_ambiguous_parameters_are_rejected(self) -> None:
        invalid_urls = [
            "/api/test-sites?chromosome=Gm99&start=1&end=2",
            "/api/test-sites?chromosome=Gm01&start=2&end=1",
            "/api/test-sites?chromosome=Gm01&start=1&end=1001",
            "/api/test-sites?start=1&end=2",
            "/api/test-sites?chromosome=Gm01&start=1&end=2&confidence=X",
            "/api/genes?page_size=101",
            "/api/genes?page=0",
            "/api/genes?query=a&query=b",
            "/api/genes?unexpected=value",
        ]
        for path in invalid_urls:
            with self.subTest(path=path):
                response = self.get(path)
                try:
                    self.assertEqual(response.status, 400)
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                    self.assertIn("error", json.loads(response.read()))
                finally:
                    response.close()

    def test_untrusted_search_input_is_not_reflected_and_post_is_blocked(self) -> None:
        payload = "<img src=x onerror=alert(1)>"
        response = self.get("/api/genes?" + urlencode({"query": payload}))
        body = response.read().decode()
        self.assertNotIn(payload, body)
        self.assertEqual(response.headers["Content-Type"].split(";", 1)[0], "application/json")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

        request = Request(self.base_url + "/api/meta", data=b"", method="POST")
        try:
            urlopen(request, timeout=3)
        except HTTPError as error:
            try:
                self.assertEqual(error.status, 405)
                self.assertEqual(error.headers["Allow"], "GET")
                self.assertEqual(error.headers["X-Content-Type-Options"], "nosniff")
                error.read()
            finally:
                error.close()
        else:
            self.fail("POST should be rejected")


REAL_DATA_DIR = os.environ.get("SOYMUTDB_TEST_DATA_DIR")


@unittest.skipUnless(REAL_DATA_DIR, "set SOYMUTDB_TEST_DATA_DIR for the supplied-data integration audit")
class SuppliedDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert REAL_DATA_DIR is not None
        cls.index = minimal_search.SearchIndex(Path(REAL_DATA_DIR))

    def test_real_file_record_counts_and_exact_example_search(self) -> None:
        self.assertEqual(len(self.index.chromosome_lengths), 20)
        self.assertEqual(len(self.index.genes), 48_387)
        self.assertEqual(len(self.index.test_sites), 3_697)
        self.assertEqual(
            sum(site.gene_span_relation == "outside_annotated_gene_span" for site in self.index.test_sites),
            495,
        )
        genes = self.index.search_genes(GENE_A, "Gm01", None, None, 1, 20)
        self.assertEqual([item["gene_id"] for item in genes["items"]], [GENE_A])
        sites = self.index.search_test_sites("Gm01", 98_256, 98_256, GENE_A, "", "", "", 1, 20)
        self.assertEqual(sites["total"], 1)
        self.assertEqual(sites["items"][0]["test_site_id"], "SOYTE1M-Gm01-98256")
        self.assertEqual(sites["items"][0]["feature"], "gene|-5225.5")
        self.assertEqual(sites["items"][0]["gene_span_relation"], "within_annotated_gene_span")


if __name__ == "__main__":
    unittest.main()
