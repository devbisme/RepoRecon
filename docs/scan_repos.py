#!/usr/bin/env python3
"""
Repository Scanner and Enricher.

This script provides functionality to discover, gather, and enrich GitHub repository data
based on predefined topics. It uses the GitHub API for discovery and an LLM (via Ollama)
for content analysis, acceptance checking, and summary generation.

The workflow typically involves:
1. Scanning: Finding repositories matching specific search terms within date ranges.
2. Enrichment: Fetching READMEs, analyzing them against criteria using an LLM,
   and generating concise summaries for the results.
"""

import json
import os
import subprocess
import sys
from datetime import datetime as dt
from github import Github
import requests
import base64
from loguru import logger

# Configuration
debug = True

# Use large context model (131K tokens)
model = "gemma4-claude"

# Authenticate with GitHub using a personal access token.
# If not found, then Github access will be slower and may hit rate limits sooner.
token = os.getenv("REPORECON_GITHUB_TOKEN")
g = Github(token)


def is_timeout(start_time, timeout):
    """
    Check if the elapsed time since start_time exceeds the specified timeout in seconds.

    Args:
        start_time (datetime): The starting timestamp of an operation.
        timeout (int or None): The maximum allowed duration in seconds.

    Returns:
        bool: True if timed out, False otherwise.
    """
    return timeout is not None and (dt.now() - start_time).total_seconds() > timeout


def get_default_repo_branch(owner, repo):
    """
    Fetch the default branch name for a given GitHub repository using the REST API.

    Args:
        owner (str): The owner of the repository.
        repo (str): The name of the repository.

    Returns:
        str: The name of the default branch (e.g., 'main' or 'master').
    """
    url = f"https://api.github.com/repos/{owner}/{repo}"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Claude-Code-Fetch-Default-Branch-Name",
    }

    if token:
        headers["Authorization"] = f"token {token}"

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except Exception:
        logger.warning(f"Failed to get default branch for {owner}/{repo}")
        return "master" # Just take a guess...

    data = response.json()
    return data["default_branch"]


def get_repo_file_extensions(owner, repo):
    """
    Retrieve all unique file extensions present in a repository's tree structure.

    Args:
        owner (str): The owner of the repository.
        repo (str): The name of the repository.

    Returns:
        set: A set of lowercase file extensions found in the repo.
    """
    branch = get_default_repo_branch(owner, repo)
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Claude-Code-Fetch-Repo-Files",
    }

    if token:
        headers["Authorization"] = f"token {token}"

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except Exception:
        logger.warning(f"Failed to get file extensions for {owner}/{repo}")
        return set()

    file_extensions = set()
    data = response.json()
    for item in data.get("tree", []):
        if item["type"] == "blob":  # blob = file, tree = directory
            path = item["path"]
            file_extensions.add(os.path.splitext(path.lower())[1])

    return file_extensions


def fetch_readme(owner, repo):
    """
    Fetch the content of a repository's README file from GitHub.
    Attempts to use the /readme endpoint first, falling back to scanning root contents.

    Args:
        owner (str): The owner of the repository.
        repo (str): The name of the repository.

    Returns:
        str: The content of the README as a UTF-8 string, or an empty string if not found.
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Claude-Code-Fetch-Repo-Readme",
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        # Try the dedicated readme endpoint
        url = f"https://api.github.com/repos/{owner}/{repo}/readme"
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        return base64.b64decode(data["content"]).decode("utf-8")
    except Exception:
        pass

    # Fallback: scan repo root for common README filenames
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/"
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
    except Exception:
        logger.warning(f"Failed to get README for {owner}/{repo}")
        return ""

    files = r.json()
    candidates = [
        "README.md",
        "README.rst",
        "README.txt",
        "README",
        "readme.md",
        "readme.rst",
        "readme",
    ]
    for name in candidates:
        for f in files:
            if f["name"] == name:
                try:
                    file_resp = requests.get(
                        f["download_url"], headers=headers, timeout=10
                    )
                    file_resp.raise_for_status()
                    return file_resp.text
                except Exception:
                    pass
    
    logger.warning(f"Failed to get README for {owner}/{repo}")
    return ""


def ollama_process(prompt, context=""):
    """
    Send a prompt to a local Ollama instance for processing and return the response.

    Args:
        prompt (str): The primary instruction or question for the LLM.
        context (str): Optional additional context to prepend to the prompt.

    Returns:
        str or None: The stripped string response from Ollama, or None if an error occurs.
    """
    num_retries = 2
    for _ in range(num_retries):
        try:
            # Assuming Ollama is running locally on the default port
            url = "http://localhost:11434/api/generate"
            payload = {
                "model": model,
                "prompt": f"{context}\n\n{prompt[:3500]}",  # Truncate to stay within limits
                "stream": False,
            }
            r = requests.post(url, json=payload, timeout=60)
            r.raise_for_status()
            return r.json().get("response", "").strip()
        except Exception as e:
            logger.warning(f"Ollama error: {e}")
    logger.error("Failed to get response from Ollama after multiple retries.")
    return None


def check_acceptance(readme, criteria):
    """
    Use an LLM to determine if a repository's content satisfies specific acceptance criteria.

    Args:
        readme (str): The content of the README file.
        criteria (str): The requirements/criteria string.

    Returns:
        tuple: (bool, str) - A boolean indicating acceptance and the raw LLM response.
    """
    if not readme or not criteria or "Placeholder" in criteria:
        # If no criteria defined or no readme found, treat as pass by default.
        return True, "No criteria defined or no readme found so accept it by default."

    if debug:
        prompt = f"Does the following content satisfy these criteria? Start answer with an initial 'Yes' or 'No' followed by an explanation for your decision.\n\nCriteria: {criteria}\n\nContent:\n{readme}"
    else:
        # In production, we want a more deterministic response.
        prompt = f"Does the following content satisfy these criteria? Answer only 'Yes' or 'No'.\n\nCriteria: {criteria}\n\nContent:\n{readme}"

    # Test the repository against the criteria to see if it meets requirements.
    yes_no = []
    num_checks = 1  # Number of times we want to verify (could be increased for higher confidence)
    while len(yes_no) < num_checks:
        response = ollama_process(prompt)
        if response:
            # Check the beginning of the response for 'yes' or 'no'.
            if "yes" in response[:3].lower():
                yes_no.append(1)
            elif "no" in response[:2].lower():
                yes_no.append(0)

    # Accept if majority of checks passed (or 1/1 for num_checks=1).
    return sum(yes_no) > num_checks // 2, response


def generate_summary(readme, search_terms):
    """
    Generate a concise summary and keywords for a repository using an LLM.

    Args:
        readme (str): The content of the README file.
        search_terms (str): Keywords to focus on or exclude from categorization.

    Returns:
        str: A generated summary string, or empty if failed.
    """
    if not readme:
        return ""
    prompt = f"Create a terse, 50-word summary of the following, focusing on what the project does and how it relates to {search_terms}. Then append three keywords (excluding {search_terms}) to categorize this project:\n\n{readme}"
    summary = ollama_process(prompt)
    return summary if summary else ""


def enrich_repos(repos, criteria, search_terms, count, timeout, batch_size=5):
    """
    Iterate through a list of repositories and perform enrichment (acceptance check & summarization).

    Args:
        repos (list): List of repository dictionaries.
        criteria (str): Acceptance criteria for the LLM to evaluate against.
        search_terms (str): Terms used for summary generation context.
        count (int or None): Maximum number of repos to enrich.
        timeout (int or None): Global timeout in seconds for this operation.
        batch_size (int): Number of repositories to process in each batch before yielding.

    Returns:
        None: Updates the 'repos' list objects in-place.

    Yields:
        None: Yields control back to the caller after processing each batch.
    """
    # Sort repos by push date descending (newest first).
    repos.sort(
        key=lambda x: dt.strptime(x["pushed"].split("T")[0], "%Y-%m-%d").date(),
        reverse=True,
    )

    # Enrich the requested number of repos or all if count is None
    if count is not None:
        repos = repos[:count]

    logger.info(f"Enriching {len(repos)} repos...")

    start_time = dt.now()
    for idx, repo in enumerate(repos, 1):

        if is_timeout(start_time, timeout):
            break

        owner = repo["owner"]
        repo_name = repo["repo"]

        # Gather metadata for the LLM prompt
        file_extensions = get_repo_file_extensions(owner, repo_name)
        file_extensions = "File extensions: " + ",".join(list(file_extensions))
        readme = fetch_readme(owner, repo_name)
        desc = repo["description"] or ""
        repo_info = f"{file_extensions}\n{readme} {desc}"

        # Perform LLM-based acceptance check
        is_accepted, response = check_acceptance(repo_info, criteria)

        if is_accepted:
            logger.debug(f"{idx:6d}: Accepted {owner}/{repo_name} - {response}")
            summary = generate_summary(readme, search_terms)
            # Update repo info with the new summary if generated successfully
            repo["description"] = summary if summary else repo["description"]
            repo["enriched"] = True
        else:
            repo["discarded"] = True
            logger.debug(f"{idx:6d}: Discarded {owner}/{repo_name} - {response}")

        # Yield back to the caller after processing each batch.
        # The caller can save the repos after each batch so that progress is not lost.
        if idx % batch_size == 0:
            yield


def enrich_local_repos(topic, count=None, timeout=None):
    """
    Load a local JSON file of repositories and perform enrichment based on the topic's configuration.

    Args:
        topic (dict): Configuration dictionary containing 'JSON_file', 'search_terms', etc.
        count (int or None): Max repos to enrich.
        timeout (int or None): Global timeout in seconds.

    Returns:
        None: Updates the local JSON file with enriched data and removes discarded repos.
    """

    repo_file = f"{topic['JSON_file']}.json"
    search_term = topic["search_terms"]
    criteria = topic.get("acceptance_criteria", "Placeholder: define criteria here")
    timeout = timeout or topic.get("timeout", None)
    count = count or topic.get("count", None)

    with open(repo_file, "r") as f:
        try:
            repos = json.load(f)
        except json.JSONDecodeError:
            repos = []

    # Filter for accepted, unenriched repos to process
    to_enrich = [r for r in repos if not r.get("enriched", False)]

    if to_enrich:
        # Process the repos in batches, saving each batch so progress is not lost.
        for _ in enrich_repos(to_enrich, criteria, search_term, count, timeout):
            # Remove discarded repositories and save the partial results
            copy_of_repos = [r for r in repos if not r.get("discarded", False)]
            with open(repo_file, "w") as f:
                json.dump(copy_of_repos, f, indent=4)

        # Save the final, complete results
        with open(repo_file, "w") as f:
            json.dump(repos, f, indent=4)

    else:
        logger.info("No raw repos found to enrich.")


def gather_github_repos(topic, count=None, timeout=None):
    """
    Search GitHub for new repositories matching a topic and date range,
    then update the local JSON file.

    Args:
        topic (dict): Configuration dictionary containing 'title', 'search_terms', etc.
        count (int or None): Max repos to gather/enrich in this pass.
        timeout (int or None): Global timeout in seconds.

    Returns:
        None: Updates the local JSON file with new repository data.
    """
    title = topic["title"]
    search_term = topic["search_terms"]
    repo_file = topic["JSON_file"] + ".json"

    # Load the previously found repos from the JSON file to avoid duplicates and determine start date.
    try:
        with open(repo_file, "r") as f:
            try:
                prev_repos = json.load(f)
            except json.JSONDecodeError:
                prev_repos = []
    except FileNotFoundError:
        prev_repos = []

    # Create a dictionary of previous repos by ID for easy lookup and deduplication.
    prev_repos = {r["id"]: r for r in prev_repos}

    earliest_start_yr = 2008
    earliest_start_mo = 1
    earliest_start_day = 1
    if not prev_repos:
        # If no repos from a previous search, then start search at earliest possible date.
        start_yr = earliest_start_yr
        start_mo = earliest_start_mo
        start_day = earliest_start_day
        date_types = ["created"]
    else:
        # Get the year/month of the most recent repo to determine where to resume search.
        for repo in prev_repos.values():
            repo["pushed"] = repo["pushed"] or repo["created"] or repo["updated"]
        latest_repo = max(
            prev_repos.values(), key=lambda x: dt.strptime(x["pushed"][0:7], "%Y-%m")
        )
        start_yr = int(latest_repo["pushed"][0:4])
        start_mo = int(latest_repo["pushed"][5:7])
        start_day = int(latest_repo["pushed"][8:10])
        # Search by pushed date to catch old repos that were recently updated/pushed.
        date_types = ["pushed", "created"]

    # Calculate the start date for searching new repositories.
    start_date = dt.strptime(
        f"{start_yr:04}-{start_mo:02}-{start_day:02}", "%Y-%m-%d"
    ).date()

    end_yr = dt.now().year

    new_repos = {}
    for y in range(start_yr, end_yr + 1):
        if y == end_yr:
            end_mo = dt.now().month
        else:
            end_mo = 12

        # Loop through each month of the current search year.
        for m in range(start_mo, end_mo + 1):
            logger.info(f"Gathering {title} repos for {y}-{m:02} ...")
            search_date = f"{y:04}-{m:02}"

            for date_type in date_types:
                logger.info(
                    f"    Searching {title} repos for {date_type}:{search_date} ..."
                )
                query = f"{search_term} in:name,description,topics,readme {date_type}:{search_date}"
                yr_mo_repos = g.search_repositories(query)

                for repo in yr_mo_repos:
                    repo_info = {
                        "repo": repo.name,
                        "description": repo.description,
                        "owner": repo.owner.login,
                        "stars": repo.stargazers_count,
                        "forks": repo.forks_count,
                        "size": repo.size,
                        "created": repo.created_at.isoformat(),
                        "updated": repo.updated_at.isoformat(),
                        "pushed": repo.pushed_at.isoformat(),
                        "url": repo.html_url,
                        "id": repo.id,
                    }
                    try:
                        repo_info["created"] = repo.created_at.isoformat()
                        repo_info["updated"] = repo.updated_at.isoformat()
                        repo_info["pushed"] = repo.pushed_at.isoformat()
                    except AttributeError as e:
                        # Fallback if dates are missing from the API response.
                        dflt_date = dt.strptime(
                            search_date + "-01", "%Y-%m-%d"
                        ).isoformat()
                        repo_info["created"] = dflt_date
                        repo_info["updated"] = dflt_date
                        repo_info["pushed"] = dflt_date
                    new_repos[repo.id] = repo_info
        start_mo = 1

    for id, new_repo in new_repos.items():
        new_repo_date = dt.strptime(new_repo["pushed"].split("T")[0], "%Y-%m-%d").date()
        if id in prev_repos:
            # Replace an existing repo if the new one is more recent.
            prev_repo = prev_repos[id]
            prev_repo_date = dt.strptime(
                prev_repo["pushed"].split("T")[0], "%Y-%m-%d"
            ).date()
            # Replace if the new one is more recent.
            if new_repo_date > prev_repo_date:
                prev_repos[id] = new_repo
        elif new_repo_date >= start_date:
            # Add a new repo if it was created after our search boundary.
            prev_repos[id] = new_repo

    # Sort and save the updated repository list to JSON.
    date_sorted_repos = sorted(
        prev_repos.values(),
        key=lambda x: dt.strptime(x["pushed"].split("T")[0], "%Y-%m-%d").date(),
    )
    with open(repo_file, "w") as f:
        json.dump(date_sorted_repos, f, indent=4)

    # Trigger enrichment for the newly gathered repos.
    enrich_local_repos(topic, count=count, timeout=timeout)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("topic_file", help="The name of the topics file.")
    parser.add_argument(
        "--mode",
        choices=["scan", "enrich"],
        default="scan",
        help="Mode of operation: 'scan' (default) or 'enrich'.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Number of repos to enrich in 'enrich' mode.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Timeout in seconds for the entire execution.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debugging.")
    args = parser.parse_args()

    # Configure loguru level based on debug flag
    logger.remove()
    level = "DEBUG" if args.debug else "INFO"
    logger.add(
        sys.stderr,
        level=level,
        format="\n<level>{level}</level> // <green>{time:HH:mm:ss}</green> // <i>{name}:{line}</i>\n<level>{message}</level>\n",
    )
    logger.add(
        "scan_repos.log",
        level=level,
        format="\n<level>{level}</level> // <green>{time:HH:mm:ss}</green> // <i>{name}:{line}</i>\n<level>{message}</level>\n",
    )

    with open(args.topic_file, "r") as topic_file:
        topics = json.load(topic_file)
        if not topics:
            logger.info("No topics found in file.")
            sys.exit(1)

        for topic in topics:
            if args.mode == "scan":
                gather_github_repos(topic, count=args.count, timeout=args.timeout)
            elif args.mode == "enrich":
                enrich_local_repos(topic, count=args.count, timeout=args.timeout)
