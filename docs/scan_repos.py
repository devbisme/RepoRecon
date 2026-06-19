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

debug = True

# Use large context model (131K tokens)
model = "gemma4-claude"

# Authenticate with GitHub using a personal access token. If not found, then Github access will be slower.
token = os.getenv("REPORECON_GITHUB_TOKEN")
g = Github(token)

def get_default_repo_branch(owner, repo):
    url = f"https://api.github.com/repos/{owner}/{repo}"
    
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Claude-Code-Fetch-Default-Branch-Name"
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
        "User-Agent": "Claude-Code-Fetch-Repo-Files"
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
    return ""

def ollama_process(prompt, context=""):
    try:
        # Assuming Ollama is running locally on the default port
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": model,
            "prompt": f"{context}\n\n{prompt[:3500]}",
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
        return True, "No criteria defined or no readme found so accept it by default."
    if debug:
        prompt = f"Does the following content satisfy these criteria? Start answer with an initial 'Yes' or 'No' followed by an explanation for your decision.\n\nCriteria: {criteria}\n\nContent:\n{readme}"
    else:
        prompt = f"Does the following content satisfy these criteria? Answer only 'Yes' or 'No'.\n\nCriteria: {criteria}\n\nContent:\n{readme}"
    yes_no = []
    eval_set_size = 1
    while len(yes_no) < eval_set_size:
        response = ollama_process(prompt)
        if response:
            if "yes" in response[:3].lower():
                yes_no.append(1)
            elif "no" in response[:2].lower():
                yes_no.append(0)
    return sum(yes_no) > eval_set_size // 2, response

def generate_summary(readme, search_terms):
    if not readme:
        return ""
    prompt = f"Summarize the following in 50 words or less, focusing on what the project does and how it pertains to {search_terms}:\n\n{readme}"
    summary = ollama_process(prompt)
    return summary if summary else ""

def enrich_repos(repos, criteria, search_terms):
    print(f"Processing {len(repos)} candidate repos for enrichment...")

    enriched_repos = []
    for idx, repo in enumerate(repos, 1):
        owner = repo['owner']
        repo_name = repo['repo']
        file_extensions = get_repo_file_extensions(owner, repo_name)
        file_extensions = "File extensions: " +",".join(list(file_extensions))
        readme = fetch_readme(owner, repo_name)
        desc = repo['description'] or ""
        repo_info = f"{file_extensions}\n{readme} {desc}"
        # repo_info = f"{readme} {desc}\n{file_extensions}"
        is_accepted, response = check_acceptance(repo_info, criteria)
        if is_accepted:
            if debug:
                print(f"{idx:6d}: Accepted {owner}/{repo_name} - {response}\n\n", file=sys.stderr)
            summary = generate_summary(readme, search_terms)
            # Update repo info with the new summary
            repo["description"] = summary if summary else repo["description"]
            enriched_repos.append(repo)
        else:
            if debug:
                print(f"{idx:6d}: Discarded {owner}/{repo_name} - {response}\n\n", file=sys.stderr)

    return enriched_repos

def gather_github_repos(topic):
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
                        dflt_date = dt.strptime(search_date + "-01", "%Y-%m-%d").isoformat()
                        repo_info["created"] = dflt_date
                        repo_info["updated"] = dflt_date
                        repo_info["pushed"] = dflt_date
                    new_repos.append(repo_info)
        start_mo = 1

    new_repos = enrich_repos(new_repos, criteria, search_term)

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

    with open(repo_file, "w") as f:
        json.dump(no_dup_repos, f, indent=4)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("topic_file", help="The name of the topics file.")
    parser.add_argument("repo_file", help="The name of the file with repo entries.")
    args = parser.parse_args()

    with open(args.topic_file, "r") as topic_file:
        topics = json.load(topic_file)
        # for topic in topics:
        #     gather_github_repos(topic)

        topic = topics[0]
        title = topic["title"]
        search_term = topic["search_terms"]
        criteria = topic.get("acceptance_criteria", "Placeholder: define criteria here")
        with open(args.repo_file, "r") as repo_file:
            repos = json.load(repo_file)
            enriched_repos = enrich_repos(repos, criteria, search_term)
            json.dump(enriched_repos, fp=sys.stdout, indent=4)
