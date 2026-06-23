#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from datetime import datetime as dt
from github import Github
import requests
import base64

debug = True

# Use large context model (131K tokens)
model = "gemma4-claude"

# Authenticate with GitHub using a personal access token. If not found, then Github access will be slower.
token = os.getenv("REPORECON_GITHUB_TOKEN")
g = Github(token)


def is_timeout(start_time, timeout):
    return timeout is not None and (dt.now() - start_time).total_seconds() > timeout


def get_default_repo_branch(owner, repo):
    url = f"https://api.github.com/repos/{owner}/{repo}"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Claude-Code-Fetch-Default-Branch-Name",
    }

    if token:
        headers["Authorization"] = f"token {token}"

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()
    return data["default_branch"]


def get_repo_file_extensions(owner, repo):
    branch = get_default_repo_branch(owner, repo)
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Claude-Code-Fetch-Repo-Files",
    }

    if token:
        headers["Authorization"] = f"token {token}"

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()

    file_extensions = set()
    for item in data.get("tree", []):
        if item["type"] == "blob":  # blob = file, tree = directory
            path = item["path"]
            file_extensions.add(os.path.splitext(path.lower())[1])

    return file_extensions


def fetch_readme(owner, repo):
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Claude-Code-Fetch-Repo-Readme",
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/readme"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return base64.b64decode(data["content"]).decode("utf-8")
    except Exception:
        pass

    # Fallback: scan repo root
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
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
                        file_resp = requests.get(
                            f["download_url"], headers=headers, timeout=10
                        )
                        return file_resp.text
    except Exception:
        pass
    return ""


def ollama_process(prompt, context=""):
    try:
        # Assuming Ollama is running locally on the default port
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": model,
            "prompt": f"{context}\n\n{prompt[:3500]}",
            "stream": False,
        }
        r = requests.post(url, json=payload, timeout=60)
        if r.status_code == 200:
            return r.json().get("response", "").strip()
    except Exception as e:
        print(f"Ollama error: {e}")
    return None


def check_acceptance(readme, criteria):
    if not readme or not criteria or "Placeholder" in criteria:
        # If no criteria defined or no readme found, treat as pass (or handle as needed)
        return True, "No criteria defined or no readme found so accept it by default."

    if debug:
        prompt = f"Does the following content satisfy these criteria? Start answer with an initial 'Yes' or 'No' followed by an explanation for your decision.\n\nCriteria: {criteria}\n\nContent:\n{readme}"
    else:
        prompt = f"Does the following content satisfy these criteria? Answer only 'Yes' or 'No'.\n\nCriteria: {criteria}\n\nContent:\n{readme}"

    # Test the repository against the criteria to see if it meets the requirements.
    yes_no = []
    num_checks = 1
    while len(yes_no) < num_checks:
        response = ollama_process(prompt)
        if response:
            if "yes" in response[:3].lower():
                yes_no.append(1)
            elif "no" in response[:2].lower():
                yes_no.append(0)

    # Accept the repo if it passed acceptance more than it failed.
    return sum(yes_no) > num_checks // 2, response


def generate_summary(readme, search_terms):
    if not readme:
        return ""
    prompt = f"Create a terse, 50-word summary of the following, focusing on what the project does and how it relates to {search_terms}. Then append three keywords (excluding {search_terms}) to categorize this project:\n\n{readme}"
    summary = ollama_process(prompt)
    return summary if summary else ""


def enrich_repos(repos, criteria, search_terms, count, timeout):

    # Sort repos by push date descending (newest first).
    repos.sort(
        key=lambda x: dt.strptime(x["pushed"].split("T")[0], "%Y-%m-%d").date(),
        reverse=True,
    )

    # Enrich the requested number of repos or all if count is None
    if count is not None:
        repos = repos[:count]

    print(f"Enriching {len(repos)} unenriched repos from local file...")

    start_time = dt.now()
    for idx, repo in enumerate(repos, 1):

        if is_timeout(start_time, timeout):
            break

        owner = repo["owner"]
        repo_name = repo["repo"]

        file_extensions = get_repo_file_extensions(owner, repo_name)
        file_extensions = "File extensions: " + ",".join(list(file_extensions))
        readme = fetch_readme(owner, repo_name)
        desc = repo["description"] or ""
        repo_info = f"{file_extensions}\n{readme} {desc}"

        is_accepted, response = check_acceptance(repo_info, criteria)

        if is_accepted:
            if debug:
                print(
                    f"{idx:6d}: Accepted {owner}/{repo_name} - {response}\n\n",
                    file=sys.stderr,
                )
            summary = generate_summary(readme, search_terms)
            # Update repo info with the new summary
            repo["description"] = summary if summary else repo["description"]
            repo["enriched"] = True
        else:
            repo["discarded"] = True
            if debug:
                print(
                    f"{idx:6d}: Discarded {owner}/{repo_name} - {response}\n\n",
                    file=sys.stderr,
                )


def enrich_local_repos(topic, count=None, timeout=None):
    repo_file = f"{topic['JSON_file']}.json"
    search_term = topic["search_terms"]
    criteria = topic.get("acceptance_criteria", "Placeholder: define criteria here")
    with open(repo_file, "r") as f:
        try:
            repos = json.load(f)
        except json.JSONDecodeError:
            repos = []

    # Filter for accepted, unenriched repos
    to_enrich = [r for r in repos if not r.get("enriched", False)]

    if to_enrich:
        enrich_repos(to_enrich, criteria, search_term, count, timeout)
        repos = [r for r in repos if not r.get("discarded", False)]

        with open(repo_file, "w") as f:
            json.dump(repos, f, indent=4)
    else:
        print("No unenriched repositories found to process.")


def gather_github_repos(topic, count=None, timeout=None):
    title = topic["title"]
    search_term = topic["search_terms"]
    repo_file = topic["JSON_file"] + ".json"
    criteria = topic.get("acceptance_criteria", None)

    # Load the previously found repos from the JSON file.
    try:
        with open(repo_file, "r") as f:
            try:
                prev_repos = json.load(f)
            except json.JSONDecodeError:
                prev_repos = []
    except FileNotFoundError:
        prev_repos = []

    # Create a dictionary of previous repos by ID for easy lookup.
    prev_repos = {r["id"]: r for r in prev_repos}

    earliest_start_yr = 2008
    earliest_start_mo = 1
    earliest_start_day = 1
    if not prev_repos:
        # If no repos from a previous search, then start search at earliest possible date.
        start_yr = earliest_start_yr
        start_mo = earliest_start_mo
        start_day = earliest_start_day
        # If no existing repos, just search for repos by creation date.
        date_types = ["created"]
    else:
        # Else, get date of the most recent repo and start searching from that year/month.
        for repo in prev_repos.values():
            repo["pushed"] = repo["pushed"] or repo["created"] or repo["updated"]
        latest_repo = max(
            prev_repos.values(), key=lambda x: dt.strptime(x["pushed"][0:7], "%Y-%m")
        )
        # Get the year/month of the most recent repo.
        start_yr = int(latest_repo["pushed"][0:4])
        start_mo = int(latest_repo["pushed"][5:7])
        start_day = int(latest_repo["pushed"][8:10])
        # If there are existing repos, also search by pushed date to catch old repos that were recently pushed.
        date_types = ["pushed", "created"]

    # Start gathering new repos after the latest date for which we have existing repo data.
    start_date = dt.strptime(
        f"{start_yr:04}-{start_mo:02}-{start_day:02}", "%Y-%m-%d"
    ).date()

    # The current year is the last year of the search range.
    end_yr = dt.now().year

    # Search for repos from start year to end year.
    new_repos = {}
    for y in range(start_yr, end_yr + 1):
        if y == end_yr:
            end_mo = dt.now().month
        else:
            end_mo = 12

        # Loop through each month of the current search year.
        for m in range(start_mo, end_mo + 1):
            print(f"Gathering {title} repos for {y}-{m:02} ...")
            search_date = f"{y:04}-{m:02}"

            for date_type in date_types:
                print(f"    Searching {title} repos for {date_type}:{search_date} ...")
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
            if new_repo_date > prev_repo_date:
                prev_repos[id] = new_repo
        elif new_repo_date >= start_date:
            # Add a new repo if it was created after the start date.
            prev_repos[id] = new_repo

    date_sorted_repos = sorted(
        prev_repos.values(),
        key=lambda x: dt.strptime(x["pushed"].split("T")[0], "%Y-%m-%d").date(),
    )
    with open(repo_file, "w") as f:
        json.dump(date_sorted_repos, f, indent=4)

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

    debug = args.debug

    with open(args.topic_file, "r") as topic_file:
        topics = json.load(topic_file)
        if not topics:
            print("No topics found in file.")
            sys.exit(1)

        for topic in topics:
            if args.mode == "scan":
                gather_github_repos(topic, count=args.count, timeout=args.timeout)
            elif args.mode == "enrich":
                enrich_local_repos(topic, count=args.count, timeout=args.timeout)
