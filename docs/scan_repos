#!/usr/bin/env python3

import json
import subprocess

with open("topics.json", "r") as topic_file:
    topics = json.load(topic_file)
    for topic in topics:
        subprocess.run(["./get_gh_repos", topic["title"], topic["search_terms"], topic["JSON_file"]])
