import json
import tempfile
import unittest
from pathlib import Path

from paired_fixtures import complete_reviews, intake_case, write_intake
from sentinel.paired.contracts import StudyCriteria
from sentinel.paired.protocol import (
    allocate_partitions, connected_groups, freeze_study,
    load_development, load_final_test,
)
from sentinel.url_ml.urls import UrlParser


SMALL = StudyCriteria(min_total=20, min_per_class=10, min_test_per_class=2, min_test_domains=3)
SUFFIX = Path(__file__).resolve().parents[1] / "resources" / "url-v2-suffix.dat"


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parser = UrlParser(SUFFIX)

    def _rows(self):
        rows = []
        for i in range(40):
            row = intake_case(i, source="shared")
            row["message"] = f"Unique synthetic phrase number {i} {row['url']}"
            row.update(label=str(i % 2), domain_group=f"case{i}.example")
            rows.append(row)
        return rows

    def _reviewed_root(self, root):
        rows = self._rows()
        write_intake(root, [{key: value for key, value in row.items() if key != "label" and key != "domain_group"}
                            for row in rows])
        complete_reviews(root, [i % 2 for i in range(40)])

    def test_all_link_and_campaign_relationships_join_components(self):
        rows = self._rows()[:5]
        rows[0]["url"] = "https://case0.com/verify"
        rows[1]["url"] = "https://sub.case0.com/other"
        rows[2]["message"] += " https://case1.example/also"
        rows[3]["campaign_group"] = "shared-campaign"
        rows[4]["campaign_group"] = "shared-campaign"
        rows[3]["message"] = rows[2]["message"].replace("2.example", "3.example")
        groups = connected_groups(rows, self.parser)
        self.assertEqual(groups["case-0"], groups["case-1"])
        self.assertEqual(groups["case-1"], groups["case-2"])
        self.assertEqual(groups["case-3"], groups["case-4"])
        wording = self._rows()[:2]
        wording[1]["message"] = wording[0]["message"].replace("0.example", "1.example")
        self.assertEqual(connected_groups(wording, self.parser)["case-0"],
                         connected_groups(wording, self.parser)["case-1"])

    def test_four_partitions_are_deterministic_and_disjoint(self):
        rows = self._rows()
        one = allocate_partitions(rows, self.parser, criteria=SMALL)
        two = allocate_partitions(rows, self.parser, criteria=SMALL)
        self.assertEqual({key: [row["case_id"] for row in value] for key, value in one.items()},
                         {key: [row["case_id"] for row in value] for key, value in two.items()})
        self.assertEqual(set(one), {"train", "validation", "calibration", "test"})
        all_groups = connected_groups(rows, self.parser)
        group_sets = [{all_groups[row["case_id"]] for row in one[name]} for name in one]
        for i in range(4):
            for j in range(i + 1, 4):
                self.assertFalse(group_sets[i] & group_sets[j])
        for name in one:
            self.assertEqual({row["label"] for row in one[name]}, {"0", "1"})
        self.assertGreaterEqual(sum(row["label"] == "0" for row in one["test"]), 2)

    def test_production_gates_and_giant_component_fail(self):
        rows = self._rows()
        with self.assertRaisesRegex(ValueError, "insufficient"):
            allocate_partitions(rows, self.parser)
        for row in rows[:32]:
            row["campaign_group"] = "one-huge-group"
        with self.assertRaisesRegex(ValueError, "component"):
            allocate_partitions(rows, self.parser, criteria=SMALL)

    def test_freeze_checks_hashes_and_never_replaces_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._reviewed_root(root)
            manifest = freeze_study(root, self.parser, criteria=SMALL)
            self.assertEqual(manifest["seed"], 42)
            development = load_development(root, self.parser)
            self.assertEqual(set(development), {"train", "validation", "calibration"})
            receipt = {"state": "reserved", "protocol_sha256": manifest["manifest_sha256"]}
            self.assertTrue(load_final_test(root, self.parser, receipt))
            with self.assertRaises(FileExistsError):
                freeze_study(root, self.parser, criteria=SMALL)
            path = root / "study-v1" / "validation.csv"
            path.write_bytes(path.read_bytes() + b"tampered")
            with self.assertRaisesRegex(ValueError, "validation.csv"):
                load_development(root, self.parser)

    def test_corrupt_source_or_manifest_blocks_load(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._reviewed_root(root)
            manifest = freeze_study(root, self.parser, criteria=SMALL)
            with self.assertRaises(ValueError):
                load_final_test(root, self.parser, {"state": "reserved", "protocol_sha256": "bad"})
            source = root / "final_pairs.csv"
            original = source.read_bytes()
            source.write_bytes(original + b"changed")
            with self.assertRaises(ValueError):
                load_development(root, self.parser)
            source.write_bytes(original)
            manifest_path = root / "study-v1" / "manifest.json"
            manifest_path.write_bytes(manifest_path.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "manifest.json"):
                load_development(root, self.parser)


if __name__ == "__main__":
    unittest.main()
