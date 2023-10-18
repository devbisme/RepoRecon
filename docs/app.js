
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
    { className: 'repo', data: 'repo', title: 'Repo', "width": '25%' },
    { className: 'description', data: 'description', title: 'Description', "width": '40%' },
    { className: 'owner', data: 'owner', title: 'Owner', "width": '10%' },
    { className: 'stars', data: 'stars', title: 'Stars', "width": '5%' },
    { className: 'forks', data: 'forks', title: 'Forks', "width": '5%' },
    { className: 'size', data: 'size', title: 'Size', "width": '5%' },
    { className: 'pushed', data: 'pushed', title: 'Pushed', "width": '10%' }
];

// Elements of the web page.
let topicSelector = document.getElementById('topicSelector');
let topicTitle = document.getElementById("topicTitle");
let filterInput = document.getElementById('filterField');
let numRepos = document.getElementById('numRepos');
let waitingIcon = document.getElementById('waiting');



topicTitle.addEventListener("click", function (event) {
    show_waiting();
    sortString = "owner:asc";
    filterInput.value = "owner:devbisme"
    tableData = filterData(topicData);
    populateTable(tableData);
});

function async_run(f) {
    setTimeout(f, 0);
}

function show() {
    waitingIcon.style.display = "block";
}
function show_waiting() {
    console.log("show_waiting");
    async_run(show);
}

function hide() {
    waitingIcon.style.display = "none";
}
function hide_waiting() {
    console.log("hide_waiting");
    async_run(hide);
}



// Populate the table in the web page with rows of topic data.
function populateTable(data) {

    // Show the number of repos in the table.
    numRepos.textContent = `(${data.length} Repositories)`;

    if (repoTable !== null && repoTable !== undefined) {
        repoTable.destroy();
    }

    // Function to convert column name to column index.
    function columnNameToIndex(name) {
        return columnDefs.findIndex((col) => col.className === name);
    }

    // Get column name and direction for initial sorting of table data.
    [sortCol, sortDir] = sortString.split(":", 2);

    repoTable = new DataTable('#dataTable', {
        scrollX: false,
        data: data,
        columns: columnDefs,
        order: [[columnNameToIndex(sortCol), sortDir]]
    });

    // Remove the waiting icon after the repo table has been generated and displayed.
    hide_waiting();
}

// Find the column index for a given column name.
function findColumn(column) {

    let col = column.toLowerCase();

    // Search for a column whose label starts with the given column name.
    for (let column of columnDefs) {
        if (column['className'].toLowerCase().startsWith(col)) {
            // Found one.
            return column['className'];
        }
    }
    return null;
}

// Filter the data based on the contents of the filter field.
function filterData(data) {

    // Indicate that this may take a while...
    show_waiting();

    // Start off with table data being everything on a topic.
    tableData = [...data];

    // Get column:value from the web page filter imput field.
    let filterStr = filterInput.value.trim();

    if (filterStr === null || filterStr === undefined || filterStr.length === 0) {
        // Filter string is blank so use all repo data.
        return tableData;
    }

    // Check filter string syntax.
    if (! /^\w+:(\w+\s*)+$/.test(filterStr)) {
        alert(`Malformed filter: ${filterStr}`);
        return tableData;
    }

    // Get the column to search in.
    [col, vals] = filterStr.split(":", 2);
    foundCol = findColumn(col, data);
    if (foundCol === null) {
        alert(`No column matches ${col}.`);
        return tableData;
    }

    // Search for rows where the specified column contains all the search values.
    tableData = [...data]; // Start with all the data rows.
    for (val of vals.split(" ")) {
        // Retain only the remaining rows that match the current value in the array of values.
        tableData = tableData.filter(row => row[foundCol].toLowerCase().includes(val.toLowerCase()));
    }

    return tableData;
}

// Initiate filtering when the user types <enter> clicks the "X" in the filter field.
filterInput.addEventListener("search", function (event) {

    // Indicate that this may take a while...
    show_waiting();

    // Get column:value from the web page filter imput field.
    filterString = filterInput.value;

    if (filterString.length === 0) {
        // Clear filtering if the "X" in the filter field is clicked or the field is empty.
        clearFilter();
        tableData = [...topicData]; // Clearing filter causes all topic data to be shown.
        populateTable(tableData);
    }
    else {
        // Filter the table based on the contents of the non-empty filter field.
        tableData = filterData(topicData);
        populateTable(tableData);
    }
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
    show_waiting();

    // Display the topic title.
    topicTitle.textContent = topicSelector.options[topicSelector.selectedIndex].text;

    // Load the rows of Github repo data from the JSON file.
    fetch(jsonFile + '.json')
        .then(response => response.json())
        .then(data => {
            topicData = [...data];
            preprocessData(topicData);
            tableData = filterData(topicData)
            populateTable(tableData);
        });
}

// Clear filter so all data will be shown in table.
function clearFilter() {
    filterInput.value = "";
    tableData = [];
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
    foundCol = findColumn(col);
    if (foundCol === null) {
        alert(`No column matches ${col}.`);
        return defaultSortString;
    }

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

    let topic = null;
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

// When the web page first appears, load the rows of Github repo data from the JSON file and display them.
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
            for (let option of topicSelector.options) {
                if (option.value === topic || option.text.toLowerCase().includes(topic)) {
                    // Found the topic in the selector.
                    topicSelector.selectedIndex = option.index;
                    break;
                }
            }

            // Load and display the data for the selected topic.
            loadTopic();
        })
}
