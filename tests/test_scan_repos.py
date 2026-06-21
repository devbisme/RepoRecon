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

    @patch('docs.scan_repos.get_repo_file_extensions')
    @patch('docs.scan_repos.fetch_readme')
    @patch('docs.scan_repos.check_acceptance')
    @patch('docs.scan_repos.generate_summary')
    def test_enrich_repos_success(self, mock_gen_sum, mock_acc, mock_fetch, mock_ext):
        # Setup mocks
        mock_ext.return_value = {".py", ".js"}
        mock_fetch.return_value = "This is a machine learning project in Python."
        mock_acc.return_value = (True, "Accepted")
        mock_gen_sum.return_value = "A ML project using Python."

        results = enrich_repos(self.mock_repos, self.criteria, self.search_terms)

        # Verify results
        for repo in results:
            if repo["repo"] == "ml-project-a":
                self.assertTrue(repo["enriched"])
                self.assertEqual(repo["description"], "A ML project using Python.")
            if repo["repo"] == "ml-project-b":
                self.assertTrue(repo["enriched"])

    @patch('docs.scan_repos.get_repo_file_extensions')
    @patch('docs.scan_repos.fetch_readme')
    @patch('docs.scan_repos.check_acceptance')
    def test_enrich_repos_rejected(self, mock_acc, mock_fetch, mock_ext):
        mock_ext.return_value = {".py"}
        mock_fetch.return_value = "Not ML."
        mock_acc.return_value = (False, "Rejected")

        results = enrich_repos(self.mock_repos, self.criteria, self.search_terms)

        for repo in results:
            if repo["repo"] == "ml-project-a":
                self.assertFalse(repo["enriched"])
                self.assertFalse(repo["accepted"])

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
            # Mock enrich_repos to return the input list (simulating success)
            mock_enrich.side_effect = lambda repos, criteria, search_terms: [
                {**r, "enriched": True} for r in repos
            ]

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
            mock_enrich.assert_not_called()
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

if __name__ == "__main__":
    unittest.main()
