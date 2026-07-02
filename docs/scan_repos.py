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
import sys
from datetime import datetime as dt
from github import Auth, Github
import html_text
import requests
import base64
from loguru import logger

# Configuration
debug = True

ctx_size = 4096
model = "gemma4:e2b-it-qat-128k" # reasonably accurate, 390 repos/hour
# model = "gemma4-claude"  # accurate, 34s per repo eval
# model = "gemma4:12b-it-qat"  # accurate, 34s per repo eval
# model = "gemma4:e2b" # too permissive, 8s per repo eval
# model = "gemma4:e4b" # too permissive, 12s per repo eval
# model = "qwen3.5:9b" # terminates because of thinking too much and exceeds length

# Authenticate with GitHub using a personal access token.
# If not found, then Github access will be slower and may hit rate limits sooner.
token = os.getenv("REPORECON_GITHUB_TOKEN")
auth = Auth.Token(token)
g = Github(auth=auth)


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


def ollama_process(prompt, context=""):
    """
    Send a prompt to a local Ollama instance for processing and return the response.

    Args:
        prompt (str): The primary instruction or question for the LLM.
        context (str): Optional additional context to prepend to the prompt.

    Returns:
        str or None: The stripped string response from Ollama, or None if an error occurs.
    """
    chars_per_token = 4  # Approximate number of characters per token
    prompt_size = int(ctx_size * chars_per_token * 0.95)
    timeouts = [60, 120]
    for timeout in timeouts:
        try:
            # Assuming Ollama is running locally on the default port
            url = "http://localhost:11434/api/generate"
            payload = {
                "model": model,
                "prompt": f"{context}\n\n{prompt[:prompt_size]}",  # Truncate to stay within limits
                "stream": False,
            }
            r = requests.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            response = r.json().get("response", "").strip()
            # if not response:
            #     breakpoint()
            #     logger.warning("Ollama finished without errors but generated no response.")
            return response
        except Exception as e:
            logger.warning(f"Ollama error: {e}")
    logger.warning("Failed to get response from Ollama after multiple retries.")
    return None


def parse_acceptance_response(response):
    """Parse the model response into an acceptance boolean and the remaining text."""
    if not response:
        # Don't reject a repo just because the LLM got borked and didn't generate a response.
        return True, ""

    text = response.strip()

    tokens = text.split(None, 1)
    if tokens:
        first = tokens[0].lower().rstrip(".,;:")
        remainder = tokens[1].strip() if len(tokens) > 1 else ""
        if first == "yes":
            if not remainder:
                logger.debug(f"Accepted but no reponse.")
            return True, remainder or ""
        if first == "no":
            return (
                False,
                remainder or "Rejected but no rejection reasons were returned.",
            )

    lower_text = text.lower()
    if lower_text.startswith("yes"):
        return True, text[3:].strip() or ""
    if lower_text.startswith("no"):
        return (
            False,
            text[2:].strip() or "Rejected but no rejection reasons were returned.",
        )

    # Something strange happened, but don't reject the repo because of that.
    logger.debug(f"Strange reponse: {text}")
    return True, ""


def evaluate_repository(repo_info, criteria, search_terms):
    """Use a single Ollama call to decide acceptance and return a summary or rejection reasons."""
    if not repo_info or not criteria or "Placeholder" in criteria:
        # Don't reject the repo. It will be re-evaluated some other time.
        return True, ""

    prompt = (
        "Determine if the repository content meets the acceptance criteria. "
        "Answer with a single initial token 'Yes' or 'No', followed by a concise explanation.\n\n"
        f"If the repo is accepted, follow 'Yes' with summary of what the project does followed "
        "by a newline and three parenthesized keywords "
        f"(do not use '{search_terms}' in the keywords).\n"
        "If the repo is rejected, follow 'No' with the reasons it was rejected.\n\n"
        "Output format:\n"
        "Yes <summary>\n(<keyword 1>, <keyword 2>, <keyword 3>)\n"
        "or\n"
        "No <rejection reasons>\n\n"
        f"Acceptance criteria:\n{criteria}\n\n"
        f"Repository content:\n{repo_info}"
    )

    response = ollama_process(prompt)
    accepted, body = parse_acceptance_response(response)
    return accepted, body


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
        try:
            r = g.get_repo(f"{owner}/{repo_name}")
        except Exception as e:
            logger.debug(
                f"{idx:6d}: Deferred {owner}/{repo_name} - Repository not found"
            )
        else:
            # Gather information about the repo to feed to the LLM.
            file_extensions = set()
            try:
                tree = r.get_git_tree(sha=r.default_branch, recursive=True)
            except Exception as e:
                logger.warning(f"{idx:6d}: {owner}/{repo_name} - {e}")
            else:
                for elem in tree.tree:
                    file_extensions.add(os.path.splitext(elem.path)[1])

            try:
                readme = html_text.extract_text(
                    base64.b64decode(r.get_readme().content).decode("utf-8")
                )
            except Exception as e:
                logger.warning(f"{idx:6d}: {owner}/{repo_name} - {e}")
                readme = ""

            desc = repo["description"] or ""

            repo_info = f"{file_extensions}\n{readme} {desc}"

            # Perform LLM-based evaluation and enrich if accepted.
            is_accepted, response = evaluate_repository(repo_info, criteria, search_terms)

            if not response:
                # No response, so don't accept or reject the repo.
                # It will be re-evaluated some other time, maybe with a definitive result.
                logger.debug(f"{idx:6d}: Deferred {owner}/{repo_name} - No response")
                pass
            elif is_accepted:
                logger.debug(f"{idx:6d}: Accepted {owner}/{repo_name} - {response}")
                repo["description"] = response
                repo["enriched"] = True
            else:
                logger.debug(f"{idx:6d}: Discarded {owner}/{repo_name} - {response}")
                repo["discarded"] = True

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
            copy_of_repos = [r for r in repos if not r.get("discarded", False)]
            json.dump(copy_of_repos, f, indent=4)

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
            prev_repos.values(), key=lambda x: dt.strptime(x["pushed"][0:10], "%Y-%m-%d")
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

    new_repos = {}
    for date_type in date_types:
        logger.info(
            f"    Searching {title} repos for {date_type}:>={start_date} ..."
        )

        query = f"{search_term} in:name,description,topics,readme {date_type}:>={start_date}"
        try:
            repos = g.search_repositories(query)
        except Exception as e:
            logger.warning(f"{title } repository search failed: {e}")
            continue
        
        for repo in repos:
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
        rotation="10 MB",
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
