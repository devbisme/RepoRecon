import base64
import unittest
from unittest.mock import patch, MagicMock
import json
import os
from datetime import datetime as dt

# Use absolute imports relative to project root
from docs.scan_repos import enrich_repos, enrich_local_repos

class TestScanRepos(unittest.TestCase):
    def setUp(self):
        # Mock data for testing
        self.criteria = "A project that uses Python and is related to machine learning."
        self.search_terms = "machine learning python"
        self.mock_repos = [
            {
                "owner": "user1",
                "repo": "ml-project-a",
                "description": "Old description",
                "pushed": "2023-01-01T00:00:00Z",
                "created": "2022-01-01T00:00:00Z",
                "enriched": False,
                "accepted": False
            },
            {
                "owner": "user2",
                "repo": "ml-project-b",
                "description": "Newer description",
                "pushed": "2024-05-15T00:00:00Z",
                "created": "2023-05-15T00:00:00Z",
                "enriched": False,
                "accepted": False
            }
        ]

    @patch('docs.scan_repos.g', MagicMock(get_repo=MagicMock(return_value=MagicMock())))
    @patch('docs.scan_repos.get_repo_file_extensions')
    @patch('docs.scan_repos.fetch_readme')
    @patch('docs.scan_repos.evaluate_repository')
    def test_enrich_repos_success(self, mock_eval, mock_fetch, mock_ext):
        # Setup mocks
        mock_ext.return_value = {".py", ".js"}
        mock_fetch.return_value = "This is a machine learning project in Python."
        mock_eval.return_value = (
            True,
            "A short summary of a Python ML project. keywords: ai, training, dataset",
        )

        list(enrich_repos(self.mock_repos, self.criteria, self.search_terms, None, None, batch_size=1))

        # Verify results
        for repo in self.mock_repos:
            self.assertTrue(repo["enriched"])
            self.assertTrue(repo["accepted"])
            self.assertEqual(
                repo["description"],
                "A short summary of a Python ML project. keywords: ai, training, dataset",
            )

    @patch('docs.scan_repos.g', MagicMock(get_repo=MagicMock(return_value=MagicMock())))
    @patch('docs.scan_repos.get_repo_file_extensions')
    @patch('docs.scan_repos.fetch_readme')
    @patch('docs.scan_repos.evaluate_repository')
    def test_enrich_repos_rejected(self, mock_eval, mock_fetch, mock_ext):
        mock_ext.return_value = {".py"}
        mock_fetch.return_value = "Not ML."
        mock_eval.return_value = (False, "The project does not match the machine learning criteria.")

        list(enrich_repos(self.mock_repos, self.criteria, self.search_terms, None, None, batch_size=1))

        for repo in self.mock_repos:
            self.assertFalse(repo.get("enriched", False))
            self.assertFalse(repo.get("accepted", False))

    @patch('docs.scan_repos.evaluate_repository')
    @patch('docs.scan_repos.html_text.extract_text')
    def test_enrich_skips_unchanged_already_enriched_repo(self, mock_extract, mock_eval):
        fake_repo = MagicMock()
        fake_repo.default_branch = "main"
        fake_repo.get_git_tree.return_value = MagicMock(tree=[MagicMock(path="repo.py")])
        fake_repo.get_readme.return_value = MagicMock(
            content=base64.b64encode(b"# Example repo").decode("utf-8")
        )

        repo_info = "file extensions in repo: ['.py']\n# Example repo Original description"
        repo = {
            "owner": "octo",
            "repo": "demo",
            "description": "Original description",
            "created": "2024-01-01T00:00:00Z",
            "updated": "2024-01-01T00:00:00Z",
            "pushed": "2024-01-01T00:00:00Z",
            "enriched": True,
            "repo_info_hash": "unchanged-hash",
        }

        with patch('docs.scan_repos.g', MagicMock(get_repo=MagicMock(return_value=fake_repo))):
            mock_extract.return_value = "# Example repo"
            mock_eval.return_value = (True, "Summary")
            with patch('docs.scan_repos.repo_info_hash', return_value='unchanged-hash'):
                list(enrich_repos([repo], self.criteria, self.search_terms, None, None, batch_size=1))

        self.assertTrue(repo.get("enriched", False))
        self.assertEqual(repo.get("description"), "Original description")
        mock_eval.assert_not_called()

    @patch('docs.scan_repos.enrich_repos')
    def test_enrich_from_local_sorting_and_count(self, mock_enrich):
        # Create a dummy JSON file for testing
        test_topic = {
            "JSON_file": "test_repo",
            "search_terms": "test",
            "acceptance_criteria": "test"
        }

        # Mock the repos in the file (b is newer than a)
        repos_data = [
            {"id": 1, "pushed": "2023-01-01T00:00:00Z", "created": "2023-01-01T00:00:00Z", "enriched": False},
            {"id": 2, "pushed": "2024-05-15T00:00:00Z", "created": "2024-05-15T00:00:00Z", "enriched": False}
        ]

        # We need to mock the open() call or just create a real temp file.
        # Let's use a temporary file for simplicity in this environment.
        test_file = "test_repo.json"
        with open(test_file, "w") as f:
            json.dump(repos_data, f)

        try:
            # Mock enrich_repos to simulate the actual sorting by pushed date and enrich the newest repo.
            def enrich_side_effect(repos, criteria, search_terms, count=None, timeout=None):
                repos.sort(
                    key=lambda x: dt.strptime(x["pushed"].split("T")[0], "%Y-%m-%d").date(),
                    reverse=True,
                )
                if count is not None:
                    repos = repos[:count]
                if repos:
                    repos[0]["enriched"] = True
                return [None]

            mock_enrich.side_effect = enrich_side_effect

            # Create a mock args object with count=1
            class MockArgs:
                count = 1

            args = MockArgs()
            enrich_local_repos(test_topic, args.count)

            # Verify that only the newest one (id: 2) was enriched because of --count 1
            with open(test_file, "r") as f:
                updated_repos = json.load(f)

            enriched_ids = [r["id"] for r in updated_repos if r.get("enriched")]
            self.assertEqual(len(enriched_ids), 1)
            self.assertIn(2, enriched_ids)
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

    @patch('docs.scan_repos.enrich_repos')
    def test_enrich_from_local_no_unenriched(self, mock_enrich):
        test_topic = {
            "JSON_file": "test_repo",
            "search_terms": "test",
            "acceptance_criteria": "test"
        }
        repos_data = [
            {"id": 1, "pushed": "2023-01-01T00:00:00Z", "enriched": True},
            {"id": 2, "pushed": "2024-05-15T00:00:00Z", "enriched": True}
        ]

        test_file = "test_repo.json"
        with open(test_file, "w") as f:
            json.dump(repos_data, f)

        try:
            class MockArgs:
                count = 1
            args = MockArgs()
            enrich_local_repos(test_topic, args)
            mock_enrich.assert_called_once()
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

if __name__ == "__main__":
    unittest.main()
