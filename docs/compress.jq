# filter.jq
# Keeps only title, description, url, popularity and date.
# popularity = $stars + 10 * $forks$
# date = most recent of created/updated/pushed fields (ISO 8601 string)
#
# Usage:
#   jq --argjson min_pop 50 -f filter.jq input.json > output.json
#   or
#   jq --arg min_pop "50" -f filter.jq input.json > output.json
# If min_pop is omitted it defaults to 0.

# Coerce dotted value to number (string->number or 0)
def to_num:
  ( . // 0 )
  | if type == "string" then (try tonumber catch 0)
    elif type == "number" then .
    else 0
    end;

# Convert a supplied value ($v) to epoch seconds (fallback 0)
def to_epoch($v):
  ($v // null) as $x
  | if ($x | type) == "number" then $x
    elif ($x | type) == "string" then
      (try ($x | fromdateiso8601) catch
       (try ($x | fromdate) catch
        (try ($x | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) catch 0)))
    else 0 end;

def min_pop:
  ( $min_pop // 0 )
  | if type == "string" then (try tonumber catch 0)
    elif type == "number" then .
    else 0
    end;

# compute_pop($obj) returns numeric popularity = stars + 10 * forks
def compute_pop($o):
  (
    (
      ($o.stargazers_count // $o.stargazers // $o.stars // $o.watchers_count // $o.watchers
       // $o.repository?.stargazers_count // $o.repository?.stargazers // $o.repository?.stars // $o.repository?.watchers_count // $o.repository?.watchers)
      | to_num
    )
    + (10 * (
      ($o.forks_count // $o.forks // $o.repository?.forks_count // $o.repository?.forks // 0)
      | to_num
    ))
  );

# compute_date($obj) returns ISO 8601 string of the most recent date or null
def compute_date($o):
  (
    [ $o.created_at, $o.created, $o.creation_date, $o.repository?.created_at,
      $o.updated_at, $o.updated, $o.repository?.updated_at,
      $o.pushed_at, $o.pushed, $o.repository?.pushed_at ]
    | map(to_epoch(.))
    | max as $mx
    | if $mx > 0 then ($mx | strftime("%Y-%m-%dT%H:%M:%SZ")) else null end
  );

def keep:
  .
  as $orig
  | {
      title: ($orig.title // $orig.name // $orig.repo // $orig.repository?.name // $orig.full_name),
      description: ($orig.description // $orig.summary // $orig.repo_description // $orig.repository?.description),
      url: ($orig.url // $orig.html_url // $orig.htmlUrl // $orig.repository?.html_url // $orig.repository?.url // $orig.homepage),
      popularity: ( compute_pop($orig) ),
      date: ( compute_date($orig) )
    }
  | with_entries(select(.value != null));

# Support top-level array, GitHub-like { items: [...] }, or a single object
if type == "array" then
  map(keep) | map(select(.popularity >= min_pop))
elif has("items") and (.items | type == "array") then
  .items |= (map(keep) | map(select(.popularity >= min_pop)))
else
  keep | select(.popularity >= min_pop)
end
