"""Tests for the exemplar similarity filter. Fully mocked; no network required."""
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from loguru import logger

from docs import scan_repos as sr

logger.remove()


def unit(vec):
    v = np.array(vec, dtype=np.float32)
    return v / np.linalg.norm(v)


class TestParseRepoUrl(unittest.TestCase):
    def test_forms(self):
        cases = {
            "https://github.com/owner/name": "owner/name",
            "http://www.github.com/owner/name/": "owner/name",
            "owner/name": "owner/name",
            "https://github.com/owner/name.git": "owner/name",
            "https://github.com/owner/name/tree/main/sub": "owner/name",
            "github.com/owner/name": "owner/name",
        }
        for url, expected in cases.items():
            self.assertEqual(sr.parse_repo_url(url), expected, url)

    def test_unparseable(self):
        for url in ["https://github.com/owner", "", None, "   "]:
            self.assertIsNone(sr.parse_repo_url(url))


class TestCalibrateThreshold(unittest.TestCase):
    def test_uses_loosest_exemplar_pairing(self):
        # Two tight vectors and one loose outlier: the bar is set by the outlier's
        # best match, which is the weakest link the topic already tolerates.
        vectors = np.stack([unit([1, 0]), unit([1, 0.1]), unit([1, 1])])
        expected = float(unit([1, 0.1]) @ unit([1, 1])) * sr.threshold_slack
        self.assertAlmostEqual(sr.calibrate_threshold(vectors), expected, places=5)

    def test_single_exemplar_falls_back(self):
        vectors = np.stack([unit([1, 0])])
        self.assertEqual(
            sr.calibrate_threshold(vectors), sr.default_similarity_threshold
        )


class TestVectorFilter(unittest.TestCase):
    def setUp(self):
        self.vectors = np.stack([unit([1, 0]), unit([0, 1])])
        self.filter = sr.VectorFilter(self.vectors, 0.9)

    def test_scores_best_matching_exemplar(self):
        # Max-over-exemplars: matching either exemplar is enough, so a topic with
        # two distinct flavors accepts both.
        with patch.object(sr, "ollama_embed", return_value=np.stack([unit([0, 1])])):
            ok, score = self.filter.accepts("text")
        self.assertTrue(ok)
        self.assertAlmostEqual(score, 1.0, places=5)

    def test_rejects_dissimilar(self):
        with patch.object(sr, "ollama_embed", return_value=np.stack([unit([1, 1])])):
            ok, score = self.filter.accepts("text")
        self.assertFalse(ok)
        self.assertAlmostEqual(score, 0.7071, places=3)

    def test_embedding_failure_does_not_reject(self):
        with patch.object(sr, "ollama_embed", return_value=None):
            ok, score = self.filter.accepts("text")
        self.assertTrue(ok)
        self.assertIsNone(score)


class TestBuildVectorFilter(unittest.TestCase):
    def test_no_exemplars_means_no_filter(self):
        self.assertIsNone(sr.build_vector_filter({"title": "T"}))
        self.assertIsNone(sr.build_vector_filter({"title": "T", "exemplars": []}))

    def _topic(self, **extra):
        return {"title": "T", "exemplars": ["o/a", "o/b"], **extra}

    def _patched(self):
        return (
            patch.object(sr, "g", MagicMock(get_repo=MagicMock())),
            patch.object(
                sr, "get_repo_content", return_value={
                    "topics": [], "extensions": [], "description": "", "readme": ""
                }
            ),
            patch.object(
                sr, "ollama_embed",
                return_value=np.stack([unit([1, 0]), unit([1, 0.5])]),
            ),
        )

    def test_calibrates_by_default(self):
        for p in self._patched():
            p.start()
        try:
            vf = sr.build_vector_filter(self._topic())
        finally:
            patch.stopall()
        expected = float(unit([1, 0]) @ unit([1, 0.5])) * sr.threshold_slack
        self.assertAlmostEqual(vf.threshold, expected, places=5)

    def test_topic_setting_beats_calibration(self):
        for p in self._patched():
            p.start()
        try:
            vf = sr.build_vector_filter(self._topic(similarity_threshold=0.42))
        finally:
            patch.stopall()
        self.assertEqual(vf.threshold, 0.42)

    def test_override_beats_topic_setting(self):
        for p in self._patched():
            p.start()
        try:
            vf = sr.build_vector_filter(
                self._topic(similarity_threshold=0.42), threshold_override=0.77
            )
        finally:
            patch.stopall()
        self.assertEqual(vf.threshold, 0.77)

    def test_embedding_failure_disables_filtering(self):
        with patch.object(sr, "g", MagicMock(get_repo=MagicMock())), \
             patch.object(sr, "get_repo_content", return_value={
                 "topics": [], "extensions": [], "description": "", "readme": ""}), \
             patch.object(sr, "ollama_embed", return_value=None):
            self.assertIsNone(sr.build_vector_filter(self._topic()))


class TestEnrichReposFiltering(unittest.TestCase):
    """The filter must run before the LLM and before the repo tree is fetched."""

    def setUp(self):
        self.repos = [
            {
                "owner": "u", "repo": "keep",
                "created": "2024-01-01T00:00:00Z",
                "pushed": "2024-01-01T00:00:00Z",
                "updated": "2024-01-01T00:00:00Z",
            },
            {
                "owner": "u", "repo": "drop",
                "created": "2024-01-02T00:00:00Z",
                "pushed": "2024-01-02T00:00:00Z",
                "updated": "2024-01-02T00:00:00Z",
            },
        ]

    def run_enrich(self, vector_filter):
        content = {
            "topics": [], "extensions": [], "description": "d", "readme": "r"
        }
        with patch.object(sr, "g", MagicMock(get_repo=MagicMock())), \
             patch.object(sr, "get_repo_content", return_value=content), \
             patch.object(sr, "get_repo_file_extensions", return_value=[".py"]) as ext, \
             patch.object(sr, "evaluate_repository", return_value=(True, "ok")) as ev:
            list(sr.enrich_repos(
                "T", self.repos, "criteria", "terms", None, None,
                vector_filter=vector_filter,
            ))
        return ext, ev

    def test_filtered_repo_skips_llm_and_tree_fetch(self):
        vf = MagicMock()
        vf.threshold = 0.5
        # 'drop' is processed first (newest-first ordering) and fails the filter.
        vf.accepts.side_effect = [(False, 0.1), (True, 0.9)]

        ext, ev = self.run_enrich(vf)

        dropped = [r for r in self.repos if r["repo"] == "drop"][0]
        kept = [r for r in self.repos if r["repo"] == "keep"][0]
        self.assertTrue(dropped.get("discarded"))
        self.assertFalse(kept.get("discarded", False))
        self.assertEqual(kept["description"], "ok")
        # Only the surviving repo cost a tree fetch and an LLM call.
        self.assertEqual(ext.call_count, 1)
        self.assertEqual(ev.call_count, 1)

    def test_no_filter_evaluates_everything(self):
        ext, ev = self.run_enrich(None)
        self.assertEqual(ev.call_count, 2)
        self.assertEqual(ext.call_count, 2)
        for r in self.repos:
            self.assertFalse(r.get("discarded", False))


class TestDigestUnchanged(unittest.TestCase):
    """The digest string must keep its old format so stored digests stay valid."""

    def test_format_matches_legacy(self):
        content = {
            "topics": ["a", "b"], "extensions": [".py"],
            "description": "desc", "readme": "body",
        }
        legacy = (
            f"Topics: {content['topics']}\n"
            f"File extensions: {content['extensions']}\n"
            f"Description: {content['description']}\n"
            f"README:\n{content['readme']}"
        )
        self.assertEqual(sr.format_repo_info(content), legacy)

    def test_embed_text_omits_extensions_and_truncates(self):
        content = {
            "topics": [], "extensions": [".py"],
            "description": "d", "readme": "x" * (sr.embed_max_chars * 2),
        }
        text = sr.format_embed_text(content)
        self.assertNotIn("File extensions", text)
        self.assertEqual(len(text), sr.embed_max_chars)
