#!/usr/bin/env python3
"""
Semantic ranker for RepoRecon topic files.

Given a topic JSON file (e.g. kicad.json) and a natural-language query, this
script ranks every repo by how closely its description matches the query and
writes a new JSON file identical to the input except that each repo gains a
"rank" field (1 = best match).

Embeddings are produced by a local Ollama instance -- the same service
scan_repos.py already uses -- so no new infrastructure or API keys are needed.
Repo-description embeddings are expensive, so they are cached in a sidecar
".vec.npz" file keyed by repo id and a hash of the embedded text. Re-ranking an
already-embedded topic with a new query is therefore near-instant, and only
repos whose description changed are re-embedded on later runs.

The input topic file is never modified.

Examples:
    # Rank kicad.json for a query, writing kicad.ranked.json next to it.
    ./rank.py kicad.json --query "cheap open-source autorouter"

    # Same, but keep only the 200 best matches in the output.
    ./rank.py kicad.json --query "STM32 dev board" --top 200
"""

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np
import requests
from loguru import logger

# Ollama connection -- mirrors scan_repos.py's assumptions.
OLLAMA_URL = "http://localhost:11434"

# Default embedding model. A purpose-built embedding model gives far better
# results than a generative one; install it once with:  ollama pull nomic-embed-text
DEFAULT_MODEL = "nomic-embed-text"

# Number of texts sent to Ollama per /api/embed request.
BATCH_SIZE = 64


def text_hash(text):
    """Stable short hash of the embedded text, used to detect stale cache rows."""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def embed_field(repo, field):
    """Return the text used to represent a repo in the semantic space."""
    return (repo.get(field) or "").strip()


def ollama_embed(texts, model):
    """
    Embed a list of texts via Ollama, returning an (N, D) float32 array.

    Tries the modern /api/embed batch endpoint first, then falls back to the
    older single-input /api/embeddings endpoint for compatibility.
    """
    # Modern batch endpoint.
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": model, "input": texts},
            timeout=300,
        )
        if r.status_code == 200:
            data = r.json()
            vecs = data.get("embeddings")
            if vecs:
                return np.asarray(vecs, dtype=np.float32)
        else:
            _raise_embed_error(r)
    except requests.RequestException as e:
        logger.error(f"Ollama /api/embed request failed: {e}")
        raise SystemExit(1)

    # Legacy per-text endpoint.
    out = []
    for text in texts:
        r = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=120,
        )
        if r.status_code != 200:
            _raise_embed_error(r)
        vec = r.json().get("embedding")
        if not vec:
            logger.error("Ollama returned an empty embedding.")
            raise SystemExit(1)
        out.append(vec)
    return np.asarray(out, dtype=np.float32)


def _raise_embed_error(response):
    """Turn an Ollama error response into an actionable message and exit."""
    try:
        msg = response.json().get("error", response.text)
    except ValueError:
        msg = response.text
    logger.error(f"Ollama embedding request failed ({response.status_code}): {msg}")
    logger.error(
        "Make sure an embedding model is installed and the server supports "
        "embeddings, e.g.:\n    ollama pull nomic-embed-text"
    )
    raise SystemExit(1)


def normalize(mat):
    """L2-normalize rows so cosine similarity reduces to a dot product."""
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def load_cache(cache_path, model):
    """
    Load cached embeddings as {id: (text_hash, vector)}.

    A cache built with a different model is ignored, since vectors from
    different models are not comparable.
    """
    if not os.path.exists(cache_path):
        return {}
    try:
        data = np.load(cache_path, allow_pickle=False)
    except Exception as e:
        logger.warning(f"Could not read cache {cache_path} ({e}); rebuilding.")
        return {}
    if str(data.get("model")) != model:
        logger.info("Cache was built with a different model; rebuilding.")
        return {}
    ids = data["ids"]
    hashes = data["hashes"]
    vecs = data["vecs"]
    return {int(i): (str(h), vecs[k]) for k, (i, h) in enumerate(zip(ids, hashes))}


def save_cache(cache_path, model, cache):
    """Persist {id: (text_hash, vector)} to a compact .npz sidecar."""
    if not cache:
        return
    ids = np.array(list(cache.keys()), dtype=np.int64)
    hashes = np.array([cache[i][0] for i in cache], dtype="U40")
    vecs = np.vstack([cache[i][1] for i in cache]).astype(np.float32)
    # np.savez appends ".npz"; write to a sibling temp path, then move it
    # atomically into place.
    tmp_base = cache_path + ".tmp"
    np.savez(tmp_base, model=np.array(model), ids=ids, hashes=hashes, vecs=vecs)
    os.replace(tmp_base + ".npz", cache_path)


def embed_repos(repos, field, model, cache_path):
    """
    Return a normalized (N, D) matrix of repo embeddings, reusing cached rows
    and only embedding repos whose text is new or changed.
    """
    cache = load_cache(cache_path, model)

    texts = [embed_field(r, field) for r in repos]
    hashes = [text_hash(t) for t in texts]

    # Figure out which repos still need embedding.
    todo = []  # indices into `repos`
    for idx, repo in enumerate(repos):
        rid = repo.get("id")
        cached = cache.get(rid)
        if cached is None or cached[0] != hashes[idx]:
            todo.append(idx)

    logger.info(
        f"{len(repos)} repos: {len(repos) - len(todo)} cached, {len(todo)} to embed."
    )

    # Embed the missing ones in batches.
    dim = None
    for start in range(0, len(todo), BATCH_SIZE):
        chunk = todo[start : start + BATCH_SIZE]
        batch_texts = [texts[i] for i in chunk]
        t0 = time.time()
        vecs = ollama_embed(batch_texts, model)
        dim = vecs.shape[1]
        for j, i in enumerate(chunk):
            cache[repos[i]["id"]] = (hashes[i], vecs[j])
        done = min(start + BATCH_SIZE, len(todo))
        logger.info(f"  embedded {done}/{len(todo)} ({time.time() - t0:.1f}s/batch)")

    save_cache(cache_path, model, cache)

    # Assemble the matrix in repo order. Repos that somehow lack a vector (e.g.
    # empty description) get a zero row and will rank last.
    if dim is None:
        # Nothing new was embedded; infer dim from any cached vector.
        any_vec = next(iter(cache.values()))[1] if cache else None
        dim = len(any_vec) if any_vec is not None else 0
    mat = np.zeros((len(repos), dim), dtype=np.float32)
    for idx, repo in enumerate(repos):
        cached = cache.get(repo.get("id"))
        if cached is not None:
            mat[idx] = cached[1]
    return normalize(mat)


def rank_repos(repos, query, field, model, cache_path):
    """
    Attach a 1-based "rank" field to each repo (1 = best match) and return the
    repos sorted best-first. The input list/objects are not mutated.
    """
    repo_mat = embed_repos(repos, field, model, cache_path)
    query_vec = normalize(ollama_embed([query], model))[0]

    sims = repo_mat @ query_vec  # cosine similarity, since everything is unit-norm.

    # Repos with an empty description embed to a zero row (sim 0); push them to
    # the bottom so real matches always outrank them.
    empty = np.array([not embed_field(r, field) for r in repos])
    sims = np.where(empty, -np.inf, sims)

    order = np.argsort(-sims, kind="stable")  # best (highest sim) first.

    ranked = []
    for rank, idx in enumerate(order, start=1):
        repo = dict(repos[idx])  # shallow copy so the input is untouched.
        repo["rank"] = rank
        repo["score"] = None if np.isneginf(sims[idx]) else round(float(sims[idx]), 4)
        ranked.append(repo)
    return ranked


def main():
    parser = argparse.ArgumentParser(
        description="Semantically rank a RepoRecon topic file against a query."
    )
    parser.add_argument("topic_file", help="Input topic JSON file, e.g. kicad.json.")
    parser.add_argument(
        "--query", "-q", required=True, help="Natural-language search query."
    )
    parser.add_argument(
        "--out",
        "-o",
        default=None,
        help="Output JSON file (default: <input>.ranked.json).",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=DEFAULT_MODEL,
        help=f"Ollama embedding model (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--field",
        default="description",
        help="Repo field to embed (default: description).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Keep only the N best matches in the output (default: keep all).",
    )
    parser.add_argument(
        "--cache",
        default=None,
        help="Embedding cache file (default: <input>.vec.npz).",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if args.debug else "INFO",
        format="<level>{level}</level> {message}",
    )

    stem, _ = os.path.splitext(args.topic_file)
    out_path = args.out or f"{stem}.ranked.json"
    cache_path = args.cache or f"{stem}.vec.npz"

    if os.path.abspath(out_path) == os.path.abspath(args.topic_file):
        logger.error("Refusing to overwrite the input topic file.")
        sys.exit(1)

    with open(args.topic_file) as f:
        repos = json.load(f)
    if not isinstance(repos, list) or not repos:
        logger.error("Topic file must be a non-empty JSON array of repos.")
        sys.exit(1)
    logger.info(f'Ranking {len(repos)} repos against: "{args.query}"')

    ranked = rank_repos(repos, args.query, args.field, args.model, cache_path)
    if args.top is not None:
        ranked = ranked[: args.top]

    with open(out_path, "w") as f:
        json.dump(ranked, f, indent=4)

    logger.info(f"Wrote {len(ranked)} ranked repos to {out_path}")
    logger.info("Top matches:")
    for repo in ranked[:10]:
        logger.info(f"  {repo['rank']:>3}. [{repo.get('score')}] {repo['repo']}")


if __name__ == "__main__":
    main()
