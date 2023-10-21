# RepoRecon

This project consists of two tools:
1. A shell script that queries Github for groups of repositories mentioning various topics and
   stores information about them in a set of JSON files.
2. A single-page Javascript app that displays the collections of repos as a set of BATs (big-ass tables)
   that allow searching, filtering, and sorting.

## Usage

You can explore some tables of collected repositories [here](https://devbisme.github.io/RepoRecon/).
If you want to run it locally, do this:
1. Clone this repository to your machine;
2. Go into the `docs` directory.
3. Run an http server: `python -m http.server`.
4. Use your web browser to open `0.0.0.0:8000`.

If you want to update the tables with the latest repository information, do this:
1. Install this Python dependency: `pip install PyGithub`
1. Go into the `docs` directory.
2. Run the `scan_repos` script.
3. Refresh your web browser page.

If you want to modify the list of topics for collecting repositories, do this:
1. Edit the contents of the `docs/topics.json` file.
2. Run the `recon_repos` script. (This will take some time if you add a new topic.)
3. Refresh your web browser page.

If you want to create a link that displays a table of collected repositories on a specific topic,
you can attach *query parameters* to the RepoRecon link like so:
```
devbisme.github.io/RepoRecon?topic=kicad&filter=desc:raspberry&sort=stars:desc
```
The link above will display a table of KiCad repositories that have the string `raspberry` in their
descriptions starting with the most starred repositories.
The `topic` parameter must specify a string that matches a substring within the list of topics.
The `filter` and `sort` parameters each start with a label that matches the beginning of
one of the following table column names: `description`, `owner`, `stars`, `forks`, `size`, `pushed`.
For the `filter` parameter, the column label is followed with a colon and a string to search for.
For the `sort` parameter, the column label is followed by `asc` or `desc` to sort the table entries
by the contents of the specified column in ascending or descending order going downwards.

## Contributing

Pull requests are welcome. For major changes, please open an issue first
to discuss what you would like to change.

## License

[MIT](https://choosealicense.com/licenses/mit/)