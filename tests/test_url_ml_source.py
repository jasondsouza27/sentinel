import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from url_ml_fixtures import HAS_ML, fixture_psl

@unittest.skipUnless(HAS_ML, "Optional URL ML environment is not installed")
class SourceTests(unittest.TestCase):
    def setUp(self):
        try:
            from sentinel.url_ml import source
        except ImportError:
            self.fail("Audited URL importer is missing")
        from sentinel.url_ml.urls import UrlParser
        from sentinel.url_ml.contracts import DatasetError
        self.source, self.Error = source, DatasetError
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parser = UrlParser(fixture_psl(self.root))

    def csv(self, rows, headers=("URL", "label", "WebpageFeature")):
        p = self.root / "input.csv"
        with p.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(headers); w.writerows(rows)
        return p

    def test_inversion_dedup_conflicts_exclusions_and_private_manifest(self):
        p = self.csv([
            ["HTTPS://Bad.COM:443/A?Token=secret", 0, 999],
            ["https://good.org/", 1, 999],
            ["https://bad.com/A?Token=secret", 0, 999],
            ["https://conflict.com/a", 0, 999],
            ["https://CONFLICT.com:443/a", 1, 999],
            ["https://invalid.org/", "bad", 999],
            ["ftp://no.org/", 0, 999],
            ["https://huge.com/" + "a"*2048, 0, 999]])
        out = self.root / "audited"
        bundle = self.source.import_phiusiil(p, self.parser, out)
        self.assertEqual([r.label for r in bundle.rows], [1, 0])
        self.assertEqual(bundle.manifest["excluded"]["conflicting_label"], 2)
        self.assertEqual(bundle.manifest["excluded"]["duplicate"], 1)
        self.assertEqual(bundle.manifest["input_rows"], 8)
        self.assertNotIn("Token=secret", json.dumps(bundle.manifest))
        self.assertNotIn("WebpageFeature", json.dumps(bundle.manifest))
        self.assertEqual(bundle, self.source.load_dataset(out, self.parser))
        with self.assertRaises(self.Error): self.source.import_phiusiil(p, self.parser, out)

    def test_unicode_alias_conflicts_and_ambiguous_ip_exclusions(self):
        p=self.csv([
            ["http://127.0.0.1/",0,0],
            ["http://\uff11\uff12\uff17\uff0e\uff10\uff0e\uff10\uff0e\uff11/",1,0],
            ["https://example.com/A",0,0],
            ["https://example.com\u3002/A",1,0],
            ["http://127.1/",0,0],
            ["http://0x7f000001/",1,0],
            ["https://good.org/",1,0]])
        bundle=self.source.import_phiusiil(p,self.parser,self.root / "aliases")
        self.assertEqual(len(bundle.rows),1)
        self.assertEqual(bundle.rows[0].url,"https://good.org/")
        self.assertEqual(bundle.manifest["excluded"]["conflicting_label"],4)
        self.assertEqual(bundle.manifest["excluded"]["url_ambiguous_ipv4"],2)

    def test_missing_columns_and_empty_supported_data_refused(self):
        with self.assertRaises(self.Error):
            self.source.import_phiusiil(self.csv([[1]], ("Other",)), self.parser, self.root / "bad")
        with self.assertRaises(self.Error):
            self.source.import_phiusiil(self.csv([["ftp://a.com",0,1]]), self.parser, self.root / "empty")

    def test_derived_data_and_suffix_tampering_rejected(self):
        out=self.root / "audited"
        self.source.import_phiusiil(self.csv([["https://a.com/",0,999]]), self.parser, out)
        with (out / "rows.jsonl").open("a", encoding="utf-8") as f: f.write("{}\n")
        with self.assertRaises(self.Error): self.source.load_dataset(out, self.parser)

    def test_member_is_read_only_with_size_and_name_checks(self):
        archive=self.root / "sample.zip"
        with zipfile.ZipFile(archive,"w") as z:
            z.writestr("../../escaped.txt", "never extract")
            z.writestr(self.source.CSV_MEMBER, "URL,label\nhttps://a.com,0\n")
        dest=self.root / "member.csv"
        self.source.read_member(archive,dest)
        self.assertTrue(dest.read_text().startswith("URL,label"))
        self.assertFalse((self.root.parent / "escaped.txt").exists())
        with self.assertRaises(self.Error): self.source.read_member(archive,dest)
        with patch.object(self.source, "MAX_MEMBER_BYTES", 5), self.assertRaises(self.Error):
            self.source.read_member(archive,self.root / "oversize.csv")

    def test_source_allowlist_and_acquisition_byte_verified_reuse(self):
        for url in ("http://archive.ics.uci.edu/a", "https://example.org/a", "https://archive.ics.uci.edu@evil.org/a"):
            with self.assertRaises(self.Error): self.source.validate_source_url(url)
        archive=self.root / "sample.zip"
        with zipfile.ZipFile(archive,"w") as z:
            z.writestr(self.source.CSV_MEMBER,"URL,label\nhttps://a.com,0\n")
        def fake_download(url, path):
            path.write_bytes(archive.read_bytes() if url==self.source.UCI_URL else self.parser.psl_path.read_bytes())
        out=self.root / "acquisition"
        with patch.object(self.source,"_download", side_effect=fake_download) as download:
            first=self.source.fetch_sources(out)
            self.assertEqual(first,self.source.fetch_sources(out))
            self.assertEqual(download.call_count,2)
        (out / "raw" / "suffix.dat").write_text("changed")
        with self.assertRaises(self.Error): self.source.fetch_sources(out)

if __name__ == "__main__": unittest.main()
