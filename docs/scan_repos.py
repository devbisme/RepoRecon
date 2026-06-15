#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from datetime import datetime
from datetime import datetime as dt
# pip install PyGithub
from github import Github
import requests
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

model = "gemma4:12b-it-qat"

# Authenticate with GitHub using a personal access token. If not found, then Github access will be slower.
token = os.getenv("REPORECON_GITHUB_TOKEN")
g = Github(token)

def fetch_readme(owner, repo):
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Claude-Code-Fetch-Repo-Readme"
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
            candidates = ["README.md", "README.rst", "README.txt", "README", "readme.md", "readme.rst", "readme"]
            for name in candidates:
                for f in files:
                    if f["name"] == name:
                        file_resp = requests.get(f["download_url"], headers=headers, timeout=10)
                        return file_resp.text
    except Exception:
        pass
    return None

def ollama_process(prompt, context=""):
    try:
        # Assuming Ollama is running locally on the default port
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": model,
            "prompt": f"{context}\n\n{prompt}",
            "stream": False
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
        return True
    prompt = f"Based on the following README content, does this repository satisfy these acceptance criteria? Answer only 'Yes' or 'No'.\n\nCriteria: {criteria}\n\nREADME Content:\n{readme[:2000]}" # Truncate to avoid context overflow
    response = ollama_process(prompt)
    if response and "yes" in response.lower():
        return True
    return False

def generate_summary(readme):
    prompt = f"Summarize the following repository README into a concise description of 100 words or less, focusing on what the project does and its core features:\n\n{readme[:2000]}"
    summary = ollama_process(prompt)
    return summary if summary else ""

def gather_github_repos(topic):
    title = topic["title"]
    search_term = topic["search_terms"]
    repo_file = topic["JSON_file"] + ".json"
    criteria = topic.get("acceptance_criteria", "Placeholder: define criteria here")

    # Load the previously found repos from the JSON file.
    try:
        with open(repo_file, "r") as f:
            try:
                prev_repos = json.load(f)
            except json.JSONDecodeError:
                prev_repos = []
    except FileNotFoundError:
        prev_repos = []

    earliest_start_yr = 2008
    earliest_start_mo = 1
    if not prev_repos:
        # If no repos from a previous search, then start search at earliest possible data.
        start_yr = earliest_start_yr
        start_mo = earliest_start_mo
        # If no existing repos, just search for repos by creation date.
        date_types = ["created"]
    else:
        # Else, find the most recent repo and start searching from that year/month.
        for repo in prev_repos:
            repo["pushed"] = repo["pushed"] or repo["created"] or repo["updated"]
        latest_repo = max(prev_repos, key=lambda x: dt.strptime(x["pushed"][0:7], "%Y-%m"))
        # Get the year/month of the most recent repo.
        start_yr = int(latest_repo["pushed"][0:4])
        start_mo = int(latest_repo["pushed"][5:7])
        # If there are existing repos, also search by pushed date to catch old repos that were recently pushed.
        date_types = ["pushed", "created"]

    # The current year is the last year of the search range.
    end_yr = dt.now().year

    # Search for repos from start year to end year.
    new_repos = []
    for y in range(start_yr, end_yr + 1):
        if y == end_yr:
            end_mo = datetime.now().month
        else:
            end_mo = 12

        # Loop through each month of the current search year.
        for m in range(start_mo, end_mo + 1):
            print(f"Gathering {title} repos for {y}-{m:02} ...")
            search_date = f"{y}-{m:02}"

            for date_type in date_types:
                print(f"    Searching {title} repos for {date_type}:{search_date} ...")
                query = f"{search_term} in:name,description,topics,readme {date_type}:{search_date}"
                yr_mo_repos = g.search_repositories(query)

                for repo in yr_mo_repos:
                    try:
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
                    except AttributeError as e:
                        dflt_date = dt.strptime(search_date + "-01", "%Y-%m-%d").isoformat()
                        repo_info = {
                            "repo": repo.name,
                            "description": repo.description,
                            "owner": repo.owner.login,
                            "stars": repo.stargazers_count,
                            "forks": repo.forks_count,
                            "size": repo.size,
                            "created": dflt_date,
                            "updated": dflt_date,
                            "pushed": dflt_date,
                            "url": repo.html_url,
                            "id": repo.id,
                        }
                    new_repos.append(repo_info)
        start_mo = 1

    total_repos = prev_repos
    total_repos.extend(new_repos)

    # Deduplicate candidates by ID and keep the one with most recent push date.
    latest_repo_dates = {}
    for repo in total_repos:
        repo_id = repo["id"]
        repo_date = dt.strptime(repo["pushed"].split("T")[0], "%Y-%m-%d").date()
        if repo_id not in latest_repo_dates or repo_date > latest_repo_dates[repo_id]:
            latest_repo_dates[repo_id] = repo_date

    no_dup_repos = []
    for repo in total_repos:
        repo_id = repo["id"]
        repo_date = dt.strptime(repo["pushed"].split("T")[0], "%Y-%m-%d").date()
        if repo_id in latest_repo_dates and repo_date == latest_repo_dates[repo_id]:
            no_dup_repos.append(repo)
            del latest_repo_dates[repo_id]

    # --- Enrichment Phase Start ---
    print(f"Processing {len(no_dup_repos)} candidate repos for enrichment...")
    from concurrent.futures import ThreadPoolExecutor, as_completed

    final_repos = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        future_to_repo = {}
        for repo in no_dup_repos:
            def process_candidate(r, c=criteria):
                owner = r['owner']
                repo = r['repo']
                readme = fetch_readme(owner, repo)
                if not readme or not check_acceptance(readme, c):
                    print(f"Discarded {owner}/{repo}")
                    return None
                print(f"Accepted {owner}/{repo}")
                summary = generate_summary(readme)
                # Update repo info with the new summary
                r["description"] = summary if summary else r["description"]
                return r

            future_to_repo[executor.submit(process_candidate, repo)] = repo.get("id")

        for future in as_completed(future_to_repo):
            res = future.result()
            if res:
                final_repos.append(res)

    with open(repo_file, "w") as f:
        json.dump(final_repos, f, indent=4)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("topic_file", nargs="?", default="topics.json", help="The name of the topics file.")
    args = parser.parse_args()

    with open(args.topic_file, "r") as topic_file:
        topics = json.load(topic_file)
        for topic in topics:
            gather_github_repos(topic)
