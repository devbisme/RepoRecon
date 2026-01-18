#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from datetime import datetime
from datetime import datetime as dt
from github import Github


# Authenticate with GitHub using a personal access token. If not found, then Github access will be slower.
# g = Github()
g = Github(os.getenv("REPORECON_GITHUB_TOKEN"))


def gather_github_repos(title, search_term, repo_file):
    '''
    Gather Github repos using their search API and the command-line JSON processor.

    Arguments:
        title: Topic title for the RepoRecon page.
        search_term: Search term for selecting repos.
        repo_file: Filename for storing Github repos as JSON.
    
    Supporting documentation:
      Github search API: https://docs.github.com/en/rest/search/search?apiVersion=2022-11-28#search-repositories
      Github search examples: https://gist.github.com/jasonrudolph/6065289
    '''

    # Filename for storing Github repos as JSON.
    repo_file = repo_file + ".json"

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
        # Search for repos in each month of the year. This keeps #repos < 1000 (Github search API limit).

        # Set the end month for the current search year.
        if y == end_yr:
            # End month for the current date.
            end_mo = datetime.now().month
        else:
            # End month for any preceding year.
            end_mo = 12

        # Loop through each month of the current search year.
        for m in range(start_mo, end_mo + 1):
            # Clear the screen and report progress.
            print(f"Gathering {title} repos for {y}-{m:02} ...")

            # Search for repos created in this month-year.
            search_date = f"{y}-{m:02}"

            # Do searches for repos based on these different types of dates.
            # There will always be more pushed repos because all the older repos can potentially be pushed.
            # This could exceed the search limit of 1000 results, so also search based on creation date
            # so that new repos aren't missed (there will be fewer of them).
            # Never use "updated"! It seems to grab a lot of repos without regard to dates.
            for date_type in date_types:
                print(f"    Searching {title} repos for {date_type}:{search_date} ...")

                # Define the search query.
                query = f"{search_term} in:name,description,topics,readme {date_type}:{search_date}"

                # Search for repositories matching the query.
                yr_mo_repos = g.search_repositories(query)

                # Loop through all pages of results and extract the desired information.
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
                        # Missing dates are a problem for some repos.
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

            # Date type done.
        # Month done.

        # Dump what we have so far.
        # with open("checkpoint.json", "w") as f:
        #     json.dump(new_repos, f, indent=4)

        # Reset the start month to 1 for the next year.
        start_mo = 1

    total_repos = prev_repos
    total_repos.extend(new_repos)

    # Create a dictionary to store the latest date for each repo id.
    latest_repo_dates = {}
    for repo in total_repos:
        repo_id = repo["id"]
        repo_date = dt.strptime(repo["pushed"].split("T")[0], "%Y-%m-%d").date()
        if repo_id not in latest_repo_dates or repo_date > latest_repo_dates[repo_id]:
            latest_repo_dates[repo_id] = repo_date

    # Filter the list to keep only the latest repo for any duplicated repos with the same id.
    no_dup_repos = []
    for repo in total_repos:
        repo_id = repo["id"]
        repo_date = dt.strptime(repo["pushed"].split("T")[0], "%Y-%m-%d").date()
        if repo_id in latest_repo_dates and repo_date == latest_repo_dates[repo_id]:
            no_dup_repos.append(repo)
            # Created & updated scans will duplicate repos with the same dates, so remove this date to prevent dupes.
            del latest_repo_dates[repo_id]

    with open(repo_file, "w") as f:
        json.dump(no_dup_repos, f, indent=4)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("topic_file", nargs="?", default="topics.json", help="The name of the topics file.")
    args = parser.parse_args()

    with open(args.topic_file, "r") as topic_file:
        topics = json.load(topic_file)
        for topic in topics:
            gather_github_repos(topic["title"], topic["search_terms"], topic["JSON_file"])

