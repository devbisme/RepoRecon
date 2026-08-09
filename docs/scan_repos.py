#!/usr/bin/env python3
"""
Repository Scanner and Enricher.

This script provides functionality to discover, gather, and enrich GitHub repository data
based on predefined topics. It uses the GitHub API for discovery and an LLM (via Ollama)
for content analysis, acceptance checking, and summary generation.

The workflow typically involves:
1. Scanning: Finding repositories matching specific search terms within date ranges.
2. Filtering: For topics that list exemplar repos, embedding each candidate's
   topics/description/README and discarding those that don't resemble any exemplar.
3. Enrichment: Fetching READMEs, analyzing them against criteria using an LLM,
   and generating concise summaries for the results.

A topic in the topics file may add these optional keys to turn on step 2:

    "exemplars": [
        "https://github.com/owner/a-good-example",
        "https://github.com/owner/another-good-example"
    ],
    "similarity_threshold": 0.62

Two or more exemplars are enough; the threshold is calibrated from them and only
needs to be set by hand when the calibrated value turns out to be too loose or tight.
"""

import hashlib
import json
import os
import sys
from datetime import datetime as dt
from github import Auth, Github
from github.Repository import RepositorySearchResult
import html_text
import numpy as np
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

# Embedding configuration for the exemplar similarity filter. The filter compares a
# candidate repo's topics/description/README against the same content taken from the
# exemplar repos a topic lists, and drops candidates that don't look like any of them.
embed_model = "nomic-embed-text"
embed_max_chars = 8000  # Roughly the model's context; the repo text is truncated to fit.
# Threshold used when a topic lists only one exemplar and so nothing can be calibrated
# against. Cosine scores from this model bunch up well above zero, hence the high value.
default_similarity_threshold = 0.55
# The calibrated threshold is the tightest exemplar-to-exemplar similarity, relaxed by
# this factor so candidates that are merely as on-topic as the exemplars still pass.
threshold_slack = 0.95

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


def ollama_embed(texts):
    """
    Embed a list of texts with the local Ollama embedding model.

    Args:
        texts (list of str): The texts to embed.

    Returns:
        numpy.ndarray or None: An (len(texts), dim) array of unit-normalized
        vectors, or None if the embeddings could not be generated. Unit-normalizing
        here means a cosine similarity later is just a dot product.
    """
    if not texts:
        return None

    timeouts = [60, 120]
    for timeout in timeouts:
        try:
            url = "http://localhost:11434/api/embed"
            payload = {
                "model": embed_model,
                "input": [t[:embed_max_chars] for t in texts],
            }
            r = requests.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            vectors = np.array(r.json().get("embeddings", []), dtype=np.float32)
            if vectors.ndim != 2 or len(vectors) != len(texts):
                logger.warning("Ollama returned a malformed set of embeddings.")
                return None
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            # A zero-length vector has no direction to compare against, so leave it
            # alone rather than dividing by zero; it will simply score 0 everywhere.
            norms[norms == 0] = 1.0
            return vectors / norms
        except Exception as e:
            logger.warning(f"Ollama embedding error: {e}")
    logger.warning("Failed to get embeddings from Ollama after multiple retries.")
    return None


def parse_repo_url(url):
    """
    Extract the 'owner/name' portion of a GitHub repository link.

    Args:
        url (str): A repo URL such as https://github.com/owner/name, or a bare
            'owner/name' pair.

    Returns:
        str or None: The 'owner/name' slug, or None if the link can't be parsed.
    """
    if not url:
        return None

    slug = url.strip().rstrip("/")
    for prefix in ("https://", "http://"):
        if slug.startswith(prefix):
            slug = slug[len(prefix):]
    if slug.startswith("www."):
        slug = slug[len("www."):]
    if slug.startswith("github.com/"):
        slug = slug[len("github.com/"):]
    if slug.endswith(".git"):
        slug = slug[: -len(".git")]

    parts = [p for p in slug.split("/") if p]
    if len(parts) < 2:
        logger.warning(f"Unable to parse repository link: {url}")
        return None
    # Anything past owner/name (tree/main, a sub-path, ...) is not part of the slug.
    return f"{parts[0]}/{parts[1]}"


class VectorFilter:
    """
    Similarity filter built from the exemplar repos a topic lists.

    One unit-normalized embedding is kept per exemplar rather than a single averaged
    vector. A candidate scores as its highest similarity against any one exemplar, so
    a topic spanning several distinct flavors of project isn't reduced to a midpoint
    that matches none of them.
    """

    def __init__(self, vectors, threshold):
        """
        Args:
            vectors (numpy.ndarray): An (n_exemplars, dim) array of unit-normalized
                exemplar embeddings.
            threshold (float): Minimum similarity a candidate must reach to pass.
        """
        self.vectors = vectors
        self.threshold = threshold

    def score(self, text):
        """
        Score a candidate's repo text against the exemplars.

        Args:
            text (str): The candidate's topics/description/README text.

        Returns:
            float or None: The highest similarity against any exemplar, or None if
            the candidate could not be embedded.
        """
        vectors = ollama_embed([text])
        if vectors is None:
            return None
        return float(np.max(self.vectors @ vectors[0]))

    def accepts(self, text):
        """
        Decide whether a candidate is sufficiently aligned with the exemplars.

        Args:
            text (str): The candidate's topics/description/README text.

        Returns:
            (bool, float or None): Whether the candidate passes, and its score. A
            candidate that can't be embedded passes with a score of None, so a
            broken embedding service doesn't silently discard the whole scan.
        """
        score = self.score(text)
        if score is None:
            return True, None
        return score >= self.threshold, score


def calibrate_threshold(vectors):
    """
    Derive a similarity threshold from how tightly the exemplars resemble each other.

    Each exemplar is scored the same way a candidate will be -- against every other
    exemplar, keeping the best match. The loosest of those scores is the weakest link
    the topic already tolerates, so it becomes the bar, relaxed by threshold_slack.

    Args:
        vectors (numpy.ndarray): An (n_exemplars, dim) array of unit-normalized
            exemplar embeddings.

    Returns:
        float: The calibrated threshold. Falls back to default_similarity_threshold
        when there are fewer than two exemplars to compare.
    """
    if len(vectors) < 2:
        logger.warning(
            f"Only {len(vectors)} exemplar(s) given, so the similarity threshold "
            f"can't be calibrated. Using {default_similarity_threshold}. Add more "
            "exemplars or set 'similarity_threshold' in the topic."
        )
        return default_similarity_threshold

    similarities = vectors @ vectors.T
    # Ignore each exemplar's perfect match with itself, i.e. score it leave-one-out.
    np.fill_diagonal(similarities, -np.inf)
    return float(np.min(np.max(similarities, axis=1))) * threshold_slack


def build_vector_filter(topic, threshold_override=None):
    """
    Build a topic's exemplar similarity filter from the repo links it lists.

    Args:
        topic (dict): Topic configuration. The 'exemplars' key holds the repo links;
            an optional 'similarity_threshold' key pins the threshold instead of
            letting it be calibrated from the exemplars.
        threshold_override (float or None): Threshold that wins over both the topic
            setting and calibration, for trying values out from the command line.

    Returns:
        VectorFilter or None: None when the topic lists no exemplars, or when none
        of them could be fetched and embedded -- in which case scanning proceeds
        unfiltered rather than discarding everything.
    """
    title = topic["title"]
    urls = topic.get("exemplars") or []
    if not urls:
        return None

    texts = []
    for url in urls:
        slug = parse_repo_url(url)
        if not slug:
            continue
        try:
            r = g.get_repo(slug)
        except Exception as e:
            logger.warning(f"{title}: Unable to fetch exemplar {slug}: {e}")
            continue
        texts.append(format_embed_text(get_repo_content(r, with_extensions=False)))

    if not texts:
        logger.warning(
            f"{title}: None of the {len(urls)} exemplar repos could be read, "
            "so no similarity filtering will be done."
        )
        return None

    vectors = ollama_embed(texts)
    if vectors is None:
        logger.warning(
            f"{title}: Exemplar repos could not be embedded, "
            "so no similarity filtering will be done."
        )
        return None

    if threshold_override is not None:
        threshold = threshold_override
    elif topic.get("similarity_threshold") is not None:
        threshold = topic["similarity_threshold"]
    else:
        threshold = calibrate_threshold(vectors)

    logger.info(
        f"{title}: Filtering against {len(texts)} exemplar repos "
        f"at a similarity threshold of {threshold:.3f}."
    )
    return VectorFilter(vectors, threshold)


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


def get_repo_topics(repo):
    """Return a repository's GitHub topics, or an empty list if they can't be read."""
    try:
        return repo.get_topics()
    except Exception as e:
        owner = repo.owner.login
        repo_name = repo.name
        logger.warning(f"Unable to fetch {owner}/{repo_name} topics: {e}")
        return []


def get_repo_content(repo, with_extensions=True):
    """
    Gather the repository content that the evaluation and filtering steps work from.

    Args:
        repo: A PyGithub repository object.
        with_extensions (bool): Whether to also read the repository tree for its file
            extensions. That is an extra API call, so it is skipped when the content
            is only headed for the similarity filter, which ignores extensions.

    Returns:
        dict: The repo's 'topics', 'extensions', 'description' and 'readme'.
    """
    return {
        "topics": get_repo_topics(repo),
        "extensions": get_repo_file_extensions(repo) if with_extensions else [],
        "description": repo.description,
        "readme": get_repo_readme(repo),
    }


def format_repo_info(content):
    """Render repo content as the text the LLM evaluates and the digest covers."""
    return (
        f"Topics: {content['topics']}\n"
        f"File extensions: {content['extensions']}\n"
        f"Description: {content['description']}\n"
        f"README:\n{content['readme']}"
    )


def format_embed_text(content):
    """
    Render repo content as the text the similarity filter embeds.

    File extensions are left out: they describe what a repo is built with rather than
    what it is about, and they would crowd out README text under the embedding model's
    context limit. Topics and description lead so they survive truncation of a long
    README, which is where a project usually states what it is anyway.
    """
    return (
        f"Topics: {content['topics']}\n"
        f"Description: {content['description']}\n"
        f"README:\n{content['readme']}"
    )[:embed_max_chars]


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


def enrich_repos(title, repos, criteria, search_terms, count, timeout, before_date=None, no_digest_only=False, batch_size=5, vector_filter=None):
    """
    Iterate through a list of repositories and perform enrichment (acceptance check & summarization).

    Args:
        title (str): The title of the topic whose repos are being processed.
        repos (list): List of repository dictionaries.
        criteria (str): Acceptance criteria for the LLM to evaluate against.
        search_terms (str): Terms used for summary generation context.
        count (int or None): Maximum number of repos to enrich.
        timeout (int or None): Global timeout in seconds for this operation.
        before_date (datetime or None): Only enrich repos dated on or before this date,
            where a repo's date is the most recent of its created, pushed, and updated
            timestamps. Defaults to the current date when None.
        no_digest_only (bool): Only enrich repos that have no stored digest, i.e. those
            that have never been successfully enriched.
        batch_size (int): Number of repositories to process in each batch before yielding.
        vector_filter (VectorFilter or None): Similarity filter built from the topic's
            exemplar repos. Repos that don't resemble any exemplar are discarded
            before the acceptance criteria are ever applied. No filtering when None.

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

    before_date = before_date or dt.now(tz=ZoneInfo("UTC"))

    # Exclude any repos dated after the before-date, then process the remaining
    # eligible repos in descending order of date (newest first). A repo's date is
    # the most recent of its created, pushed, and updated timestamps.
    # When no_digest_only is set, also exclude repos that already carry a digest
    # since those have already been enriched at least once.
    eligible_repos = sorted(
        (
            r
            for r in repos
            if get_date_time(r) <= before_date
            and not (no_digest_only and r.get("digest"))
        ),
        key=get_date_time,
        reverse=True,
    )

    # If count is not specified or is negative, process all eligible repos.
    if count is None or count < 0:
        count = len(eligible_repos)

    logger.info(f"{title}: Enriching {count} repos...")

    start_time = dt.now()
    cnt = 0  # Counts the number of repos that have been processed (not skipped due to unchanged content).
    discard_cnt = 0
    filter_cnt = 0  # Discards attributable to the similarity filter.
    skip_cnt = 0
    enrich_cnt = 0
    defer_cnt = 0
    for repo in eligible_repos:

        # Stop if enough repos have been processed or we've run out of time.
        if is_timeout(start_time, timeout) or cnt >= count:
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
            # Gather information about the repo. The file extensions are held back
            # for now because reading the repo tree is an extra API call that a repo
            # rejected by the similarity filter never needs.
            content = get_repo_content(r, with_extensions=False)

            # Reject repos that don't resemble any of the topic's exemplar repos
            # before spending an LLM call on them.
            passes_filter, similarity = (
                vector_filter.accepts(format_embed_text(content))
                if vector_filter
                else (True, None)
            )

            if not passes_filter:
                logger.debug(
                    f"{cnt:6d}: Discarded {owner}/{repo_name} - similarity "
                    f"{similarity:.3f} below threshold {vector_filter.threshold:.3f}"
                )
                repo["discarded"] = True
                discard_cnt += 1
                filter_cnt += 1
            else:
                content["extensions"] = get_repo_file_extensions(r)
                repo_info = format_repo_info(content)

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
        f"{title}: Enriched {enrich_cnt} repos, discarded {discard_cnt} repos "
        f"({filter_cnt} by the similarity filter), skipped {skip_cnt} unchanged repos, "
        f"deferred decision on {defer_cnt} repos."
    )


def enrich_local_repos(topic, count=None, timeout=None, before_date=None, no_digest_only=False, use_vector_filter=True, threshold_override=None):
    """
    Load a local JSON file of repositories and perform enrichment based on the topic's configuration.

    Args:
        topic (dict): Configuration dictionary containing 'JSON_file', 'search_terms', etc.
        count (int or None): Max repos to enrich.
        timeout (int or None): Global timeout in seconds.
        before_date (datetime or None): Only enrich repos dated on or before this date,
            where a repo's date is the most recent of its created, pushed, and updated
            timestamps. Defaults to the current date when None.
        no_digest_only (bool): Only enrich repos that have no stored digest.
        use_vector_filter (bool): Whether to apply the similarity filter to topics that
            list exemplar repos. Topics without exemplars are unaffected either way.
        threshold_override (float or None): Similarity threshold that wins over the
            topic setting and over calibration.

    Returns:
        None: Updates the local JSON file with enriched data and removes discarded repos.
    """

    repo_file = f"{topic['JSON_file']}.json"
    title = topic["title"]
    search_term = topic["search_terms"]
    criteria = topic.get("acceptance_criteria", "")
    timeout = timeout or topic.get("timeout", None)
    count = count or topic.get("count", None)
    before_date = before_date or dt.now(tz=ZoneInfo("UTC"))

    with open(repo_file, "r") as f:
        try:
            repos = json.load(f)
        except json.JSONDecodeError:
            repos = []

    # Process all repos; the enrichment loop will skip unchanged already-enriched ones
    # by comparing the current content hash with the stored hash.

    # Build the topic's exemplar similarity filter once, up front, so its repos are
    # fetched and embedded a single time no matter how many candidates are scanned.
    vector_filter = build_vector_filter(topic, threshold_override) if use_vector_filter else None

    # Process the repos in batches, saving each batch so progress is not lost.
    for _ in enrich_repos(
        title,
        repos,
        criteria,
        search_term,
        count,
        timeout,
        before_date,
        no_digest_only=no_digest_only,
        vector_filter=vector_filter,
    ):
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


def parse_before_date(date_str):
    """
    Parse a before-date string into a UTC datetime.

    Args:
        date_str (str or None): An ISO date/datetime string, or None for the current date.

    Returns:
        datetime: The before-date in UTC. A date without a time component covers
        the entire day so that all repos dated on that day are considered eligible.
    """
    if not date_str:
        return dt.now(tz=ZoneInfo("UTC"))
    parsed = dt.fromisoformat(date_str)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    # If only a date (midnight, no time component) was given, include the whole day.
    if (parsed.hour, parsed.minute, parsed.second, parsed.microsecond) == (0, 0, 0, 0):
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


def gather_github_repos(topic, count=None, timeout=None, before_date=None, no_digest_only=False, use_vector_filter=True, threshold_override=None):
    """
    Search GitHub for new repositories matching a topic and date range,
    then update the local JSON file.

    Args:
        topic (dict): Configuration dictionary containing 'title', 'search_terms', etc.
        count (int or None): Max repos to gather/enrich in this pass.
        timeout (int or None): Global timeout in seconds.
        before_date (datetime or None): Only enrich repos dated on or before this date.
            Defaults to the current date when None.
        no_digest_only (bool): Only enrich repos that have no stored digest.
        use_vector_filter (bool): Whether to apply the topic's exemplar similarity filter.
        threshold_override (float or None): Similarity threshold that wins over the
            topic setting and over calibration.

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
    enrich_local_repos(
        topic,
        count=count,
        timeout=timeout,
        before_date=before_date,
        no_digest_only=no_digest_only,
        use_vector_filter=use_vector_filter,
        threshold_override=threshold_override,
    )


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
    parser.add_argument(
        "--before",
        default=None,
        help=(
            "Before-date (ISO format, e.g. 2026-07-26) for enrichment. "
            "Repos dated after this date are not enriched; eligible repos are "
            "processed newest-first. A repo's date is the most recent of its "
            "created, pushed, and updated timestamps. Defaults to the current date."
        ),
    )
    parser.add_argument(
        "--no-digest",
        action="store_true",
        help=(
            "Only enrich repos that have no digest, i.e. those that have never been "
            "successfully enriched. Repos with a digest are left untouched."
        ),
    )
    parser.add_argument(
        "--no-vector-filter",
        action="store_true",
        help=(
            "Disable the exemplar similarity filter. By default, a topic that lists "
            "'exemplars' repo links in the topics file has each candidate repo's "
            "topics/description/README embedded and compared against those exemplars, "
            "and candidates that don't resemble any of them are discarded before the "
            "acceptance criteria are applied. Topics with no exemplars are unaffected."
        ),
    )
    parser.add_argument(
        "--vector-threshold",
        type=float,
        default=None,
        help=(
            "Similarity threshold for the exemplar filter, overriding both a topic's "
            "'similarity_threshold' setting and the value calibrated from how tightly "
            "its exemplars resemble each other. Useful for trying values out."
        ),
    )
    parser.add_argument("--debug", action="store_true", help="Enable debugging.")
    args = parser.parse_args()

    before_date = parse_before_date(args.before)

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
            gather_github_repos(
                topic,
                count=args.count,
                timeout=args.timeout,
                before_date=before_date,
                no_digest_only=args.no_digest,
                use_vector_filter=not args.no_vector_filter,
                threshold_override=args.vector_threshold,
            )
        elif args.mode == "enrich":
            enrich_local_repos(
                topic,
                count=args.count,
                timeout=args.timeout,
                before_date=before_date,
                no_digest_only=args.no_digest,
                use_vector_filter=not args.no_vector_filter,
                threshold_override=args.vector_threshold,
            )
