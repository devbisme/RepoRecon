"""Tests for derived topics that filter another topic's repos. Fully mocked; no network required."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from loguru import logger

from docs import scan_repos as sr

logger.remove()


def fake_rank(repos, query, field, model, cache_path):
    """Stand-in for rank.rank_repos that scores repos by a preset 'sim' field."""
    ranked = sorted(repos, key=lambda r: -(r["sim"] if r["sim"] is not None else -1))
    return [dict(r, rank=i, score=r["sim"]) for i, r in enumerate(ranked, start=1)]


class TestFilterSourceRepos(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self.source = [
            {"id": 1, "repo": "low", "description": "a", "sim": 0.3},
            {"id": 2, "repo": "high", "description": "b", "sim": 0.8},
            {"id": 3, "repo": "mid", "description": "c", "sim": 0.65},
            {"id": 4, "repo": "empty", "description": "", "sim": None},
        ]
        with open("src.json", "w") as f:
            json.dump(self.source, f)
        self.topic = {
            "title": "Derived",
            "source_file": "src",
            "query": "something",
            "query_threshold": 0.6,
            "JSON_file": "out",
        }

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def read_out(self):
        with open("out.json") as f:
            return json.load(f)

    @patch("docs.scan_repos.rank.rank_repos", side_effect=fake_rank)
    def test_keeps_matches_above_threshold_best_first(self, mock_rank):
        sr.filter_source_repos(self.topic)
        out = self.read_out()
        self.assertEqual([r["repo"] for r in out], ["high", "mid"])
        self.assertEqual([r["rank"] for r in out], [1, 2])
        self.assertEqual(mock_rank.call_args.args[4], "src.vec.npz")

    @patch("docs.scan_repos.rank.rank_repos", side_effect=fake_rank)
    def test_threshold_override_and_default(self, _):
        sr.filter_source_repos(self.topic, threshold_override=0.7)
        self.assertEqual([r["repo"] for r in self.read_out()], ["high"])
        del self.topic["query_threshold"]
        with patch.object(sr, "default_query_threshold", 0.2):
            sr.filter_source_repos(self.topic)
        self.assertEqual([r["repo"] for r in self.read_out()], ["high", "mid", "low"])

    @patch("docs.scan_repos.rank.rank_repos", side_effect=SystemExit(1))
    def test_embedding_failure_leaves_output_unchanged(self, _):
        with open("out.json", "w") as f:
            json.dump(["previous"], f)
        sr.filter_source_repos(self.topic)
        self.assertEqual(self.read_out(), ["previous"])

    @patch("docs.scan_repos.rank.rank_repos", side_effect=fake_rank)
    def test_skips_bad_config(self, mock_rank):
        sr.filter_source_repos(dict(self.topic, query=""))
        sr.filter_source_repos(dict(self.topic, JSON_file="src"))
        sr.filter_source_repos(dict(self.topic, source_file="missing"))
        mock_rank.assert_not_called()
        self.assertFalse(os.path.exists("out.json"))


if __name__ == "__main__":
    unittest.main()
