
// Arrays for storing topic data for display in the table.
let topicData = [];    // All data on a particular topic.
let tableData = null;  // Data (possibly filtered) to be displayed in the table.

// Column name and direction for initial sorting of table data.
let sortString = null;
let defaultSortString = "pushed:desc";
let rankSortString = "rank:asc"; // Best matches (rank 1) on top for ranked files.

// Optional JSON file to load directly (e.g. rank.py output), set from ?file= in
// the URL. This lets ranked files be viewed without an entry in topics.json.
let dataFileOverride = null;

// DataTable object for the table of repo data.
let repoTable = null;

// Base column definitions for repo DataTable.
let baseColumnDefs = [
    { className: 'repo', data: 'repo', title: 'Repo', width: '25%' },
    { className: 'description', data: 'description', title: 'Description', width: '40%' },
    { className: 'owner', data: 'owner', title: 'Owner', width: '10%' },
    { className: 'stars', data: 'stars', title: 'Stars', width: '5%' },
    { className: 'forks', data: 'forks', title: 'Forks', width: '5%' },
    { className: 'size', data: 'size', title: 'Size', width: '5%' },
    { className: 'pushed', data: 'pushed', title: 'Pushed', width: '10%' }
];

// Leading column shown only for semantically-ranked files produced by rank.py,
// whose rows carry a "rank" field (1 = best match). DataTables makes it
// click-sortable automatically.
let rankColumnDef = { className: 'rank', data: 'rank', title: 'Rank', width: '5%' };

// Active columns for the current table; chosen by setColumns() when data loads.
let columnDefs = [...baseColumnDefs];

// Prepend the Rank column when the loaded data has been scored by rank.py.
// Returns true if the data is ranked.
function setColumns(data) {
    let hasRank = data.length > 0 && 'rank' in data[0];
    columnDefs = hasRank ? [rankColumnDef, ...baseColumnDefs] : [...baseColumnDefs];
    return hasRank;
}

// Elements of the web page.
let topicSelector = document.getElementById('topicSelector');
let topicTitle = document.getElementById("topicTitle");
let filterInput = document.getElementById('filterField');
let numRepos = document.getElementById('numRepos');
let waitingIcon = document.getElementById('waiting');
let semanticInput = document.getElementById('semanticField');
let semanticStatus = document.getElementById('semanticStatus');
let semanticDiv = document.getElementById('semanticDiv');
let semanticHost = document.getElementById('semanticHost');
let dataTable = document.getElementById('dataTable');


// Show animated loading icon for long-running operations.
function showWaiting() {
    waitingIcon.style.display = "block";
}

// Hide animated loading icon after long-running operations are complete.
function hideWaiting() {
    waitingIcon.style.display = "none";
}

// Show the number of repos displayed in the table.
function showRepos(data) {
    numRepos.textContent = `(${data.length} Repositories)`;
}

// Find the column index for a possibly partial column name.
function columnNameToIndex(name) {
    name = name.toLowerCase();
    return columnDefs.findIndex((column) => column.className.toLowerCase().startsWith(name));
}

// Find the complete column name for a possibly partial name.
function findColumn(name) {
    let idx = columnNameToIndex(name);
    if (idx == -1) {
        alert(`Unknown table column name: ${name}.`);
        throw `Unknown table column name: ${name}.`;
    }
    return columnDefs[idx].className;
}

// Slide the semantic search controls into the DataTables wrapper, just above the
// table, so they land below the Show-entries and Search controls DataTables
// generates. Called once the wrapper exists, i.e. after the table is built.
function showSemanticSearch() {
    dataTable.parentNode.insertBefore(semanticDiv, dataTable);
    hideWaiting(); // Table is up, so the loading icon can go.
}

// Populate the table in the web page with rows of topic data.
function populateTable(data) {

    // Release any existing DataTable object.
    if (repoTable !== null && repoTable !== undefined) {
        // Park the semantic search controls back in their permanent home before
        // DataTables tears down the wrapper they were moved into.
        semanticHost.appendChild(semanticDiv);
        repoTable.destroy();
        // Throw away the header DataTables generated. The number of columns can
        // change while the page is up (the Rank column comes and goes with
        // semantic search), and DataTables will not rebuild a header that is
        // still sitting in the table.
        dataTable.innerHTML = "";
    }

    // Get column name and direction for initial sorting of table data.
    [sortCol, sortDir] = sortString.split(":", 2);

    repoTable = new DataTable('#dataTable', {
        initComplete: showSemanticSearch, // Reveal the table once it has been generated and displayed.
        scrollX: false, // Table fits within screen width, so no need for X scrolling.
        autoWidth: false, // Necessary to DataTable respects manual column width settings.
        pageLength: 100,
        lengthMenu: [10, 30, 100, 300, 1000],
        order: [[columnNameToIndex(sortCol), sortDir]], // Initial sorting of table data.
        columns: columnDefs,
        data: data
    });
}

// Match the table's columns and sort order to whatever tableData currently looks
// like, then redraw it. Call this after anything that adds or removes the Rank
// column: loading a topic, refiltering, or running a semantic search.
function refreshTable() {

    // Show the Rank column if the rows carry a rank, and default to best-first.
    let hasRank = setColumns(tableData);
    if (hasRank && sortString === defaultSortString) {
        sortString = rankSortString;
    }

    // Fall back to the default sort if the sort column isn't in this table,
    // e.g. a ?sort=rank URL applied to data that was never ranked.
    if (columnNameToIndex(sortString.split(":", 1)[0]) === -1) {
        sortString = defaultSortString;
    }

    showRepos(tableData); // Show the number of repos in the table.

    // For some reason, the loading icon and the # of repos won't update unless the
    // table is generated inside a fetch() call.
    fetch('').then(_ => {
        populateTable(tableData);
    });
}

// Filter the data based on the contents of the filter field.
function filterData(data) {

    // Start off with table data being everything given.
    tableData = [...data];

    // Get column:value from the web page filter imput field.
    let filterStr = filterInput.value.trim();

    if (filterStr === null || filterStr === undefined || filterStr.length === 0) {
        // Filter string is blank so use all the given data.
        return tableData;
    }

    // The following code converts the filter string into an expression that can be evaluated.

    // Replace all full/abbreviated column labels (words followed by ":") with full column labels.
    try {
        const columnNameRegex = /(\W*)(\w+):/g;
        filterStr = filterStr.replace(columnNameRegex, (match, beginChar, col) => {
            const columnName = findColumn(col);
            return beginChar + columnName + ":";
        });
    }
    catch (e) {
        // Unknown column name found, so abort and just use all the data.
        return tableData;
    }

    // Replace column labels followed by a string with expression to find the string within the column in a row of data.
    // const columnValueRegex = /(\w+):\s*(\w+)/g;
    const columnValueRegex = /(\w+):\s*([^()&|!+*/%<=>~]+)/g;
    filterExpr = filterStr.replace(columnValueRegex, (match, col, val) => {
        return `row["${col}"].toLowerCase().includes("${val}".toLowerCase())`;
    });

    // Replace any remaining column labels with an expression to get that column from the row of data.
    const columnNameRegex = /([a-zA-Z]+):/g;
    filterExpr = filterExpr.replace(columnNameRegex, (match, col) => {
        return `row["${col}"]`;
    });

    console.log(filterExpr);

    // Search for rows that trigger the filter expression.
    try {
        tableData = tableData.filter(row => eval(filterExpr))
    }
    catch (e) {
        // Invalid filter expression, so abort and just use all the data.
        alert(e);
        return tableData;
    }

    // Replace the URL in the browser search bar with a URL for the filtered page.
    showFilteredURL();

    // Return the filtered data.
    return tableData;
}

// Replace the URL in the browser search bar with a URL for the current filtered page.
function showFilteredURL() {
    encodedFilter = encodeURIComponent(filterInput.value);
    filteredURL = `${window.location.origin}${window.location.pathname}?topic=${topicSelector.value}&filter=${encodedFilter}&sort=${sortString}`
    window.history.replaceState(null, null, filteredURL)
}

// Clear filter so all data will be shown in the table.
function clearFilter() {
    filterInput.value = "";
    showFilteredURL();
    tableData = [...topicData];
}

// Initiate filtering when the user types <enter> clicks the "X" in the filter field.
filterInput.addEventListener("search", function (event) {

    // Indicate that this may take a while...
    showWaiting();

    // A new filter changes which repos are in the table, so any existing
    // semantic ranking of the old set of repos no longer applies.
    clearSemanticRanking();

    // Get column:value from the web page filter imput field.
    filterString = filterInput.value;

    if (filterString.length === 0) {
        // Clear filtering if the "X" in the filter field is clicked or the field is empty.
        clearFilter();
        // tableData = [...topicData];
    }
    else {
        // Filter the table based on the contents of the non-empty filter field.
        tableData = filterData(topicData);
    }

    refreshTable();
});

// Preprocess the rows of data.
function preprocessData(data) {

    // Look at the keys of the first row of data to get the names of the table columns.
    let columns = Object.keys(data[0]);

    // Process each row of data, column by column.
    data.forEach((row, idx) => {
        columns.forEach(column => {

            // Change empty data into an empty string.
            if (row[column] === null) {
                row[column] = "";
            }

            switch (column) {

                case 'repo':
                    // Add hyperlink to repo name.
                    row[column] = `<a href="${row["url"]}" target="_blank">${row[column]}</a>`;
                    break;

                case 'pushed':
                    // Split off the time; only keep the Y/M/D.
                    let date = row[column];
                    row[column] = date.split("T")[0];
                    break;

                default:
                    break;
            }
        })

        // Remove this data so it isn't displayed.
        delete row.url;
        delete row.created;
        delete row.updated;
        delete row.id;
    })
}

// Load the rows of Github repo data from the JSON file for that topic, filter them, and then display the table.
function loadTopic() {

    let url, title;
    if (dataFileOverride) {
        // A specific JSON file (e.g. rank.py output) was requested via ?file=.
        url = dataFileOverride;
        title = dataFileOverride;
    } else {
        let jsonFile = topicSelector.value;
        if (jsonFile === "") {
            topicTitle.textContent = "";
            return;
        }
        url = jsonFile + '.json';
        title = topicSelector.options[topicSelector.selectedIndex].text;
    }

    // Indicate that loading and displaying data on a topic may take a while...
    showWaiting();

    // Display the topic title.
    topicTitle.textContent = title;

    // Load the rows of Github repo data from the JSON file for this topic.
    fetch(url)
        .then(response => response.json())
        .then(data => {
            topicData = [...data]; // Save the data for this topic.
            preprocessData(topicData); // Preprocess the rows of data in place.
            saveFileRanks(topicData); // Remember any ranks that came with the file.
            tableData = filterData(topicData) // Filter the topic data.
            // Displays the Rank column and sorts best-first for ranked files.
            refreshTable();
        });
}

// *** Called from index.html. ***
// A topic has been selected from the topic selector, so display that topic's data.
function topicCallback() {
    dataFileOverride = null; // Selecting a topic overrides any ?file= request.
    clearFilter();  // New topic, so clear any existing filter.
    semanticInput.value = ""; // New topic, so the old semantic query no longer applies.
    semanticRanked = false;   // Rows are reloaded below, so nothing carries a semantic rank.
    sortString = defaultSortString; // New topic so use default sorting by last push date, newest at top.
    loadTopic(); // Load the rows of Github repo data from the JSON file for that topic, filter them, and then display the table.
}

// ============================================================================
// Semantic search.
//
// A repo description and the user's query are each turned into a vector by a
// small sentence-embedding model that runs inside the browser (Transformers.js
// on WebAssembly -- no server, no API key). The cosine similarity between a
// repo's vector and the query vector says how closely the two mean the same
// thing, and sorting on that similarity gives each repo its rank.
//
// Embedding is by far the expensive step, so vectors are cached twice:
//   * in memory, so repeated searches during a visit are instant, and
//   * in IndexedDB, so they survive a reload.
// Both caches are keyed by (model, hash of the embedded text), which makes them
// self-invalidating: an edited description hashes differently and is embedded
// again, while identical descriptions are computed once and shared across
// topics. Neither cache is required -- if IndexedDB is unavailable the search
// still works, just without the speedup on the next visit.
// ============================================================================

// Transformers.js is pulled in on demand rather than with a <script> tag, so
// visitors who never use semantic search never download it.
const TRANSFORMERS_URL = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.2.0/dist/transformers.min.js";

// Sentence-embedding model. Small (~25MB quantized), 384-dimensional output,
// and cached by the browser after the first download.
const EMBED_MODEL = "Xenova/all-MiniLM-L6-v2";

// Number of texts handed to the model per call.
const EMBED_BATCH_SIZE = 64;

// Repo field that gets embedded. Kept the same as rank.py's default so the
// browser and the command-line ranker compare the same text.
const EMBED_FIELD = "description";

// IndexedDB database holding the cached vectors.
const VEC_DB_NAME = "reporecon-embeddings";
const VEC_STORE = "vectors";

// True while the Rank column is showing the result of a semantic search, as
// opposed to ranks that arrived in a rank.py output file.
let semanticRanked = false;

// Ranks that came with the loaded file, keyed by row, so a semantic search can
// temporarily replace them without destroying them.
let fileRanks = new WeakMap();

// Cached promises for the one-time setup of the model and the vector database.
let embedderPromise = null;
let vecDbPromise = null;

// Vectors computed or loaded so far this visit, keyed as described above.
let vectorCache = new Map();

// Show progress next to the semantic search field.
function setSemanticStatus(msg) {
    semanticStatus.textContent = msg;
}

// Text that represents a repo in the semantic space.
function embedField(row) {
    return (row[EMBED_FIELD] || "").trim();
}

// Cache key for a piece of text. cyrb53 is a fast non-cryptographic 53-bit
// string hash; at the scale of a topic file a collision is vanishingly unlikely,
// and the only consequence would be one mis-ranked repo.
function vectorKey(text) {
    let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (let i = 0; i < text.length; i++) {
        const ch = text.charCodeAt(i);
        h1 = Math.imul(h1 ^ ch, 2654435761);
        h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    const hash = (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
    return `${EMBED_MODEL}:${hash}`;
}

// Cosine similarity of two unit-length vectors, which is just their dot product.
function similarity(a, b) {
    let sum = 0;
    for (let i = 0; i < a.length; i++) {
        sum += a[i] * b[i];
    }
    return sum;
}

// Let the browser repaint. Model inference runs on the main thread, so without
// a yield between batches the progress message would never update.
function yieldToBrowser() {
    return new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 0)));
}

// Load Transformers.js and build the embedding pipeline (first call only).
function getEmbedder() {
    if (embedderPromise === null) {
        embedderPromise = import(TRANSFORMERS_URL)
            .then(({ pipeline }) => pipeline('feature-extraction', EMBED_MODEL))
            .catch(err => {
                embedderPromise = null; // Let the next search try again.
                throw err;
            });
    }
    return embedderPromise;
}

// Open the vector database, resolving to null if the browser won't give us one
// (private browsing, storage disabled, ...). A null database just means every
// search starts from an empty on-disk cache.
function openVecDB() {
    if (vecDbPromise === null) {
        vecDbPromise = new Promise(resolve => {
            let request;
            try {
                request = indexedDB.open(VEC_DB_NAME, 1);
            }
            catch (e) {
                console.warn(`Vector cache unavailable: ${e}`);
                resolve(null);
                return;
            }
            request.onupgradeneeded = () => request.result.createObjectStore(VEC_STORE);
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => {
                console.warn(`Vector cache unavailable: ${request.error}`);
                resolve(null);
            };
        });
    }
    return vecDbPromise;
}

// Read the given keys from the vector database, returning a key -> vector Map
// holding whichever of them were found.
function vecDbGet(db, keys) {
    return new Promise(resolve => {
        const found = new Map();
        if (db === null || keys.length === 0) {
            resolve(found);
            return;
        }
        const store = db.transaction(VEC_STORE, 'readonly').objectStore(VEC_STORE);
        keys.forEach(key => {
            const request = store.get(key);
            request.onsuccess = () => {
                if (request.result !== undefined) {
                    found.set(key, request.result);
                }
            };
        });
        // However the transaction ends, hand back whatever was retrieved: a
        // failed cache read only costs time, never correctness.
        store.transaction.oncomplete = () => resolve(found);
        store.transaction.onerror = () => resolve(found);
        store.transaction.onabort = () => resolve(found);
    });
}

// Write [key, vector] pairs to the vector database. Failures (out of quota, for
// instance) are logged and ignored, since the vectors are still in memory.
function vecDbPut(db, entries) {
    return new Promise(resolve => {
        if (db === null || entries.length === 0) {
            resolve();
            return;
        }
        const store = db.transaction(VEC_STORE, 'readwrite').objectStore(VEC_STORE);
        entries.forEach(([key, vector]) => store.put(vector, key));
        store.transaction.oncomplete = () => resolve();
        store.transaction.onerror = () => {
            console.warn(`Could not cache vectors: ${store.transaction.error}`);
            resolve();
        };
        store.transaction.onabort = () => resolve();
    });
}

// Return a vector for each of the given texts, computing only the ones that
// aren't already cached. onProgress(done, total) reports embedding progress.
async function embedTexts(texts, onProgress) {

    const keys = texts.map(vectorKey);

    // Map each key back to its text, and note that duplicate texts collapse to
    // a single key: identical descriptions get embedded only once.
    const textForKey = new Map();
    keys.forEach((key, idx) => textForKey.set(key, texts[idx]));

    // Pull anything already on disk into the in-memory cache.
    const db = await openVecDB();
    const onDisk = await vecDbGet(db, [...textForKey.keys()].filter(key => !vectorCache.has(key)));
    onDisk.forEach((vector, key) => vectorCache.set(key, vector));

    // Whatever is still missing has to be computed.
    const todo = [...textForKey.keys()].filter(key => !vectorCache.has(key));
    onProgress(0, todo.length);

    if (todo.length > 0) {
        const embedder = await getEmbedder();

        for (let start = 0; start < todo.length; start += EMBED_BATCH_SIZE) {
            const batch = todo.slice(start, start + EMBED_BATCH_SIZE);

            // Mean-pooled, unit-length sentence vectors, packed one after
            // another into a single (batch size x dimension) tensor.
            const output = await embedder(batch.map(key => textForKey.get(key)),
                { pooling: 'mean', normalize: true });
            const dim = output.dims[1];

            const computed = batch.map((key, j) => {
                const vector = Float32Array.from(output.data.subarray(j * dim, (j + 1) * dim));
                vectorCache.set(key, vector);
                return [key, vector];
            });

            await vecDbPut(db, computed); // Keep them for the next visit.
            onProgress(Math.min(start + EMBED_BATCH_SIZE, todo.length), todo.length);
            await yieldToBrowser();
        }
    }

    return keys.map(key => vectorCache.get(key));
}

// Rank the repos currently in the table by how closely they match the text in
// the semantic search field, and redisplay the table with a Rank column.
async function semanticRank() {

    const query = semanticInput.value.trim();

    if (query.length === 0) {
        // An empty query means "go back to the unranked table".
        if (clearSemanticRanking()) {
            refreshTable();
        }
        return;
    }

    if (tableData === null || tableData.length === 0) {
        alert("Select a topic before searching.");
        return;
    }

    // The search runs for a while, so lock the field to keep a second <enter>
    // from starting another search on top of this one.
    semanticInput.disabled = true;
    showWaiting();

    try {
        // Only rank the repos in the table, and only those with something to
        // embed. Repos with no description are dealt with further down.
        const rows = tableData.filter(row => embedField(row).length > 0);

        setSemanticStatus("Loading the embedding model...");
        await getEmbedder();

        const vectors = await embedTexts(rows.map(embedField), (done, total) => {
            setSemanticStatus(total === 0 ? "Ranking repos..."
                : `Embedding repo descriptions: ${done}/${total}...`);
        });
        const [queryVector] = await embedTexts([query], () => { });

        setSemanticStatus("Ranking repos...");

        // Sort by descending similarity and number the results from 1.
        const scored = rows.map((row, idx) => [row, similarity(vectors[idx], queryVector)]);
        scored.sort((a, b) => b[1] - a[1]);
        scored.forEach(([row, score], idx) => {
            row.rank = idx + 1;
            row.score = Math.round(score * 10000) / 10000;
        });

        // A repo with no description can't be compared to anything, so park it
        // below every repo that could be scored instead of dropping it.
        let rank = scored.length;
        tableData.forEach(row => {
            if (embedField(row).length === 0) {
                row.rank = ++rank;
                row.score = null;
            }
        });

        semanticRanked = true;
        sortString = rankSortString; // Best matches on top.
        showFilteredURL();
        refreshTable();
    }
    catch (e) {
        // Leave the table as it was and tell the user why nothing happened.
        console.error(e);
        alert(`Semantic search failed: ${e.message || e}`);
        hideWaiting();
    }
    finally {
        semanticInput.disabled = false;
        setSemanticStatus("");
    }
}

// Set aside the ranks of a file that arrived already ranked (rank.py output
// loaded through ?file=). A semantic search overwrites the rank of every row, so
// this is what lets the file's own ranking come back when the search is cleared.
function saveFileRanks(data) {
    fileRanks = new WeakMap();
    data.forEach(row => {
        if ('rank' in row) {
            fileRanks.set(row, { rank: row.rank, score: row.score });
        }
    });
}

// Undo a semantic ranking, returning true if there was one to undo. Rows get
// their file-supplied rank back, or lose the rank field entirely if they never
// had one.
function clearSemanticRanking() {
    if (!semanticRanked) {
        return false;
    }
    topicData.forEach(row => {
        const original = fileRanks.get(row);
        if (original === undefined) {
            delete row.rank;
            delete row.score;
        }
        else {
            row.rank = original.rank;
            row.score = original.score;
        }
    });
    semanticRanked = false;
    // Let refreshTable() pick the sort: back to Rank if the file was ranked,
    // otherwise back to the last-pushed date.
    sortString = defaultSortString;
    return true;
}

// Search when the user types <enter> in the semantic field. The same event also
// fires when the "X" in the field is clicked, which empties it and so clears the
// ranking.
semanticInput.addEventListener("search", semanticRank);

// Convert the URL sort parameter into a valid column:direction string.
function convertSortParam(s) {

    if (s === null || s === undefined || s === 0)
        // No sort string so sort by date of last push, newest at top.
        s = defaultSortString;

    // Check sort string syntax.
    else if (! /^\w+:(a|d)\w*\s*$/.test(s)) {
        alert(`Malformed sort: ${s}`);
        return defaultSortString;
    }

    // Get the column to sort on.
    [col, dir] = s.split(":", 2);
    if (col === "rank" || col === "score") {
        // Ranking columns exist only for ranked files, so accept them without
        // checking against the base topic columns.
        foundCol = col;
    }
    else {
        try {
            foundCol = findColumn(col);
        }
        catch (e) {
            return defaultSortString;
        }
    }

    // Set the sort direction.
    if (dir.startsWith("a"))
        dir = "asc";
    else
        dir = "desc";

    return `${foundCol}:${dir}`;
}

// Preprocess a parameter from the URL query string.
function preprocessParam(param) {
    function rmvQuotes(str) {
        if (typeof str === 'string' && str.length >= 2 && str[0] === str[str.length - 1] && "\"'".includes(str[0])) {
            return str.slice(1, -1);
        }
        return str;
    }

    return rmvQuotes(decodeURIComponent(param.toLowerCase()));
}

// Get the topic, filter, and sort parameters from the URL query string.
function getQueryParams() {
    let queryParams = new URLSearchParams(window.location.search);

    let topic = "";
    if (queryParams.has('topic')) {
        // A topic was specified in the URL query string.
        topic = preprocessParam(queryParams.get('topic'));
    }

    let filter = null;
    if (queryParams.has('filter')) {
        // A filter was specified in the URL query string.
        filter = preprocessParam(queryParams.get('filter'));
    }

    let sort = defaultSortString;
    if (queryParams.has('sort')) {
        // A column & direction for sorting was specified in the URL query string.
        sort = preprocessParam(queryParams.get('sort'));
        sort = convertSortParam(sort);
    }

    let file = null;
    if (queryParams.has('file')) {
        // Load a JSON file directly (e.g. rank.py output) without needing an
        // entry in topics.json. Not lowercased: filenames are case-sensitive.
        file = decodeURIComponent(queryParams.get('file')).trim();
    }

    return [topic, filter, sort, file];
}

// When the web page first appears, load & display the Github repos for the topic in the URL.
window.onload = function () {

    // Get the topic, filter, sort, and file parameters from the URL query string.
    let [topic, filter, sort, file] = getQueryParams();
    filterInput.value = filter;
    sortString = sort;
    dataFileOverride = file;

    // Fetch the available topics, add them to the topic selector, and then load data for the selected topic.
    fetch("topics.json")
        .then(response => response.json())
        .then(data => {

            // Add a blank option to the topic selector.
            let option = document.createElement('option');
            option.value = "";
            option.text = "---Select a topic---";
            topicSelector.appendChild(option);

            // Add each topic to the topic selector.
            data.forEach((topic, idx) => {
                // Add a new option to the topic selector.
                option = document.createElement('option');
                option.value = topic.JSON_file;
                option.text = topic.title;
                topicSelector.appendChild(option);
            });

            // If a specific file was requested via ?file=, load it directly and
            // skip topic-selector matching (it need not be listed in topics.json).
            if (dataFileOverride) {
                topicSelector.selectedIndex = 0;
                loadTopic();
                return;
            }

            // Select the topic specified in the URL query string.
            let found = false;
            for (let option of topicSelector.options) {
                if (option.value === topic || option.text.toLowerCase().includes(topic)) {
                    // Found the topic in the selector.
                    found = true;
                    topicSelector.selectedIndex = option.index;
                    break;
                }
            }
            if (!found) {
                // Didn't find the topic in the selector.
                alert(`Unknown topic: ${topic}`);
                topicSelector.selectedIndex = 0;
            }

            // Load and display the data for the selected topic.
            loadTopic();
        })
}
