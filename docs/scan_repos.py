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

import hashlib
import json
import os
import sys
from datetime import datetime as dt
from github import Auth, Github
from github.Repository import RepositorySearchResult
import html_text
import requests
import base64
from loguru import logger
from zoneinfo import ZoneInfo

# Configuration
debug = True

ctx_size = 4096
model = "gemma4:e2b-it-qat-128k"  # reasonably accurate, 390 repos/hour
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


def get_digest(repo_info):
    """Return a stable hash for repository content used for enrichment decisions."""
    return hashlib.sha256(repo_info.encode("utf-8")).hexdigest()[:16] # Shorten for storage efficiency


def get_repo_file_extensions(repo):
    """Return the sorted list of file extensions present in a repository tree."""
    try:
        tree = repo.get_git_tree(sha=repo.default_branch, recursive=True)
    except Exception as e:
        owner = repo.owner.login
        repo_name = repo.name
        logger.warning(f"Unable to read {owner}/{repo_name} repository tree: {e}")
        return []

    file_extensions = {os.path.splitext(elem.path)[1] for elem in tree.tree}
    return sorted(file_extensions)


def get_repo_readme(repo):
    """Fetch a repository README and return its extracted text."""
    try:
        return html_text.extract_text(
            base64.b64decode(repo.get_readme().content).decode("utf-8")
        )
    except Exception as e:
        owner = repo.owner.login
        repo_name = repo.name
        logger.warning(f"Unable to fetch {owner}/{repo_name} README: {e}")
        return ""


def evaluate_repository(repo_info, criteria, search_terms):
    """Use a single Ollama call to decide acceptance and return a summary or rejection reasons."""

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


def enrich_repos(title, repos, criteria, search_terms, count, timeout, batch_size=5):
    """
    Iterate through a list of repositories and perform enrichment (acceptance check & summarization).

    Args:
        title (str): The title of the topic whose repos are being processed.
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

    if not repos:
        logger.info(f"{title}: No repos to enrich.")
        return

    # No need to enrich if there's no criteria.
    if not criteria or criteria.startswith("Placeholder"):
        # Don't reject the repo. It will be re-evaluated some other time.
        logger.info(f"{title}: No acceptance criteria given so enriching 0 repos")
        return

    # Sort repos by push date descending (newest first).
    repos.sort(
        key=lambda r: get_date_time(r),
        reverse=True,
    )

    # If count is not specified or is non-positive, process all repos.
    if not count or count <= 0:
        count = len(repos)

    logger.info(f"{title}: Enriching {count} repos...")

    start_time = dt.now()
    cnt = 1  # Counts the number of repos that have been processed (not skipped due to unchanged content).
    discard_cnt = 0
    skip_cnt = 0
    enrich_cnt = 0
    defer_cnt = 0
    for repo in repos:

        # Stop if enough repos have been processed or we've run out of time.
        if is_timeout(start_time, timeout) or cnt > count:
            break

        repo.pop(
            "enriched", None
        )  # Remove any previous enriched flag since digests now provides this function.

        owner = repo["owner"]
        repo_name = repo["repo"]
        try:
            r = g.get_repo(f"{owner}/{repo_name}")
        except Exception as e:
            # Discard the repo if it hasn't been found after several attempts.
            deferred_count = repo.get("deferred", 0) + 1
            if deferred_count >= 3:
                logger.debug(
                    f"{cnt:6d}: Discarded {owner}/{repo_name} - Not found after {deferred_count} tries"
                )
                repo["discarded"] = True
                discard_cnt += 1
            else:
                logger.debug(
                    f"{cnt:6d}: Deferred {owner}/{repo_name} - Repository not found"
                )
                repo["deferred"] = deferred_count
                defer_cnt += 1
        else:
            # Gather information about the repo to feed to the LLM.
            repo_info = (
                f"Topics: {r.get_topics()}\n"
                f"File extensions: {get_repo_file_extensions(r)}\n"
                f"Description: {r.description}\n"
                f"README:\n{get_repo_readme(r)}"
            )

            # See if the repo has changed since it was previously enriched. If not, skip it to save time and LLM API calls.
            current_hash = get_digest(repo_info)
            if repo.get("digest") == current_hash:
                logger.debug(f"{cnt:6d}: Skipping unchanged {owner}/{repo_name}")
                skip_cnt += 1
                continue

            # Perform LLM-based evaluation and enrich if accepted.
            is_accepted, response = evaluate_repository(
                repo_info, criteria, search_terms
            )

            if not response:
                # Discard the repo if there hasn't been a response after several attempts.
                deferred_count = repo.get("deferred", 0) + 1
                if deferred_count >= 3:
                    logger.debug(
                        f"{cnt:6d}: Discarded {owner}/{repo_name} - No reponse after {deferred_count} tries"
                    )
                    repo["discarded"] = True
                    discard_cnt += 1
                else:
                    logger.debug(
                        f"{cnt:6d}: Deferred {owner}/{repo_name} - No response"
                    )
                    repo["deferred"] = deferred_count
                    defer_cnt += 1
            elif is_accepted:
                logger.debug(f"{cnt:6d}: Accepted {owner}/{repo_name} - {response}")
                repo["description"] = response
                repo["digest"] = current_hash
                repo.pop(
                    "deferred", None
                )  # Remove any deferred count since the repo exists.
                enrich_cnt += 1
            else:
                logger.debug(f"{cnt:6d}: Discarded {owner}/{repo_name} - {response}")
                repo["discarded"] = True
                discard_cnt += 1

        # Yield back to the caller after processing each batch.
        # The caller can save the repos after each batch so that progress is not lost.
        if cnt % batch_size == 0:
            yield

        # Increment the number of repos processed unless they were skipped because they were unchanged.
        cnt += 1

    logger.info(
        f"{title}: Enriched {enrich_cnt} repos, discarded {discard_cnt} repos, skipped {skip_cnt} unchanged repos, deferred decision on {defer_cnt} repos."
    )


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
    title = topic["title"]
    search_term = topic["search_terms"]
    criteria = topic.get("acceptance_criteria", "")
    timeout = timeout or topic.get("timeout", None)
    count = count or topic.get("count", None)

    with open(repo_file, "r") as f:
        try:
            repos = json.load(f)
        except json.JSONDecodeError:
            repos = []

    # Process all repos; the enrichment loop will skip unchanged already-enriched ones
    # by comparing the current content hash with the stored hash.

    # Process the repos in batches, saving each batch so progress is not lost.
    for _ in enrich_repos(title, repos, criteria, search_term, count, timeout):
        # Remove discarded repositories and save the partial results
        copy_of_repos = [r for r in repos if not r.get("discarded", False)]
        with open(repo_file, "w") as f:
            json.dump(copy_of_repos, f, indent=4)

    # Save the final, complete results
    with open(repo_file, "w") as f:
        copy_of_repos = [r for r in repos if not r.get("discarded", False)]
        json.dump(copy_of_repos, f, indent=4)


def get_date_time(repo=None):
    earliest_date_time = "2008-01-01T00:00:00Z"
    date_times = []
    if isinstance(repo, dict):
        date_times.append(dt.fromisoformat(repo.get("created", earliest_date_time)))
        date_times.append(dt.fromisoformat(repo.get("pushed", earliest_date_time)))
        date_times.append(dt.fromisoformat(repo.get("updated", earliest_date_time)))
    elif isinstance(repo, RepositorySearchResult):
        date_times.append(
            dt.fromisoformat(getattr(repo, "created_at", earliest_date_time))
        )
        date_times.append(
            dt.fromisoformat(getattr(repo, "pushed_at", earliest_date_time))
        )
        date_times.append(
            dt.fromisoformat(getattr(repo, "updated_at", earliest_date_time))
        )
    elif not repo:
        date_times.append(dt.fromisoformat(earliest_date_time))
    else:
        raise (Exception, "Can't get date from unknown type.")
    return max(date_times).replace(tzinfo=ZoneInfo("UTC"))


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

    try:
        # Get the date-time for the newest repo.
        start_date_time = get_date_time(
            max(prev_repos.values(), key=lambda r: get_date_time(r))
        )
    except ValueError:
        # If there are no repos, start searching from the date that Github started operations.
        start_date_time = get_date_time()

    # Search and gather new repos starting from the date-time of the newest previous repo.
    new_repos = {}
    for date_type in ["created", "pushed"]:
        logger.info(
            f"    Searching {title} repos for {date_type}:>={start_date_time.isoformat()} ..."
        )

        query = f"{search_term} in:name,description,topics,readme {date_type}:>={start_date_time.isoformat()}"
        try:
            repos = g.search_repositories(query)
        except Exception as e:
            logger.warning(f"{title} repository search failed: {e}")
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
            new_repos[repo.id] = repo_info

    logger.info(f"    Found {len(new_repos)} new {title} repos.")

    # Add new repos to previous repos.
    for id, new_repo in new_repos.items():
        new_repo_date = get_date_time(new_repo)
        if id in prev_repos:
            # Replace an existing repo if the new one is more recent.
            prev_repo_date = get_date_time(prev_repos[id])
            if new_repo_date > prev_repo_date:
                prev_repos[id] = new_repo
        elif new_repo_date >= start_date_time:
            # Add a new repo if it was created after our search boundary.
            prev_repos[id] = new_repo

    # Sort and save the updated repository list to JSON.
    date_sorted_repos = sorted(
        prev_repos.values(),
        key=lambda r: get_date_time(r),
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
        "--topic",
        nargs="*",
        default=[],
        help="Process a specific topic from the topics file.",
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
        try:
            topics = json.load(topic_file)
        except Exception as e:
            logger.error(f"Failed while opening {topic_file.name}: {e}")
            sys.exit(1)
        if not topics:
            logger.info("No topics found in file.")
            sys.exit(0)

    for topic in topics:
        if (
            args.topic
            and topic["title"].lower() not in args.topic
            and topic["JSON_file"].lower() not in args.topic
        ):
            continue
        if args.mode == "scan":
            gather_github_repos(topic, count=args.count, timeout=args.timeout)
        elif args.mode == "enrich":
            enrich_local_repos(topic, count=args.count, timeout=args.timeout)
