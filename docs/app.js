
// Arrays for storing topic data for display in the table.
let topicData = [];    // All data on a particular topic.
let tableData = null;  // Data (possibly filtered) to be displayed in the table.

// Column name and direction for initial sorting of table data.
let sortString = null;
let defaultSortString = "pushed:desc";

// DataTable object for the table of repo data.
let repoTable = null;

// Column definitions for repo DataTable.
let columnDefs = [
    { className: 'repo', data: 'repo', title: 'Repo', width: '25%' },
    { className: 'description', data: 'description', title: 'Description', width: '40%' },
    { className: 'owner', data: 'owner', title: 'Owner', width: '10%' },
    { className: 'stars', data: 'stars', title: 'Stars', width: '5%' },
    { className: 'forks', data: 'forks', title: 'Forks', width: '5%' },
    { className: 'size', data: 'size', title: 'Size', width: '5%' },
    { className: 'pushed', data: 'pushed', title: 'Pushed', width: '10%' }
];

// Elements of the web page.
let topicSelector = document.getElementById('topicSelector');
let topicTitle = document.getElementById("topicTitle");
let filterInput = document.getElementById('filterField');
let numRepos = document.getElementById('numRepos');
let waitingIcon = document.getElementById('waiting');


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

// Populate the table in the web page with rows of topic data.
function populateTable(data) {

    // Release any existing DataTable object.
    if (repoTable !== null && repoTable !== undefined) {
        repoTable.destroy();
    }

    // Get column name and direction for initial sorting of table data.
    [sortCol, sortDir] = sortString.split(":", 2);

    repoTable = new DataTable('#dataTable', {
        initComplete: hideWaiting, // Remove loading icon after table has been generated and displayed.
        scrollX: false,
        data: data,
        columns: columnDefs,
        autoWidth: false,
        order: [[columnNameToIndex(sortCol), sortDir]]
    });
}

// Filter the data based on the contents of the filter field.
function filterData(data) {

    // Start off with table data being everything on a topic.
    tableData = [...data];

    // Get column:value from the web page filter imput field.
    let filterStr = filterInput.value.trim();

    if (filterStr === null || filterStr === undefined || filterStr.length === 0) {
        // Filter string is blank so use all repo data.
        return tableData;
    }

    // Look for strings immediately followed by colons and convert strings into full column labels.
    // Convert strings or comma-delimited strings following a colon into .toLowerCase().includes(string.toLowerCase()).
    // Convert 
    
    // Replace all matched substrings with their corresponding dictionary values.
    try {
        const columnNameRegex = /([^a-zA-Z]*)([a-zA-Z]+):/g;
        filterStr = filterStr.replace(columnNameRegex, (match, beginChar, col) => {
            const columnName = findColumn(col);
            return beginChar + columnName + ":";
        });
    }
    catch (e) {
        return tableData;
    }

    const columnValueRegex = /([a-zA-Z]+):\s*([a-zA-Z]+)/g;
    filterExpr = filterStr.replace(columnValueRegex, (match, col, val) => {
        return `row["${col}"].toLowerCase().includes("${val}".toLowerCase())`;
    });
    // console.log(`filterExpr = ${filterExpr}`);

    // Search for rows where the specified column contains the search value.
    tableData = [...data]; // Start with all the data rows.
    tableData = tableData.filter(row => eval(filterExpr))
    return tableData;
}

// Clear filter so all data will be shown in the table.
function clearFilter() {
    filterInput.value = "";
    tableData = [...topicData];
}

// Initiate filtering when the user types <enter> clicks the "X" in the filter field.
filterInput.addEventListener("search", function (event) {

    // Indicate that this may take a while...
    showWaiting();

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

    // Show the number of repos in the table.
    showRepos(tableData);

    // For some reason, the loading icon and the # of repos won't update unless the
    // table is generated inside a fetch() call.
    fetch('').then(_ => {
        populateTable(tableData);
    });
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

    let jsonFile = topicSelector.value;
    if (jsonFile === "") {
        topicTitle.textContent = "";
        return;
    }

    // Indicate that loading and displaying data on a topic may take a while...
    showWaiting();

    // Display the topic title.
    topicTitle.textContent = topicSelector.options[topicSelector.selectedIndex].text;

    // Load the rows of Github repo data from the JSON file for this topic.
    fetch(jsonFile + '.json')
        .then(response => response.json())
        .then(data => {
            topicData = [...data]; // Save the data for this topic.
            preprocessData(topicData); // Preprocess the rows of data in place.
            tableData = filterData(topicData) // Filter the topic data.
            showRepos(tableData); // Show the number of repos in the table.
            // For some reason, the loading icon and the # of repos won't update unless the
            // table is generated inside a fetch() call.
            fetch('').then(_ => {
                populateTable(tableData);
            });
        });
}

// *** Called from index.html. ***
// A topic has been selected from the topic selector, so display that topic's data.
function topicCallback() {
    clearFilter();  // New topic, so clear any existing filter.
    sortString = defaultSortString; // New topic so use default sorting by last push date, newest at top.
    loadTopic(); // Load the rows of Github repo data from the JSON file for that topic, filter them, and then display the table.
}

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
    try {
        foundCol = findColumn(col);
    }
    catch (e) {
        return defaultSortString;
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

    return [topic, filter, sort];
}

// When the web page first appears, load & display the Github repos for the topic in the URL.
window.onload = function () {

    // Get the topic, filter, and sort parameters from the URL query string.
    let [topic, filter, sort] = getQueryParams();
    filterInput.value = filter;
    sortString = sort;

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
