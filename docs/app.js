// Elements of the web page.
let topicSelector = document.getElementById('topicSelector');
let topicTitle = document.getElementById("topicTitle");
let filterInput = document.getElementById('filterField');
let numRepos = document.getElementById('numRepos');
let hourglass = document.getElementById('waiting');

let repoTable = null;

// Arrays for storing topic data for display in the table.
let topicData = [];
let tableData = null;

// Column and direction for sorting table data.
let sortString = null;
let sortDirection = {};

// Unicode arrows for sorting buttons.
let upArrow = '&#9650;';
let dwnArrow = '&#9660;';
let updwnArrow = '&#11021;';
let sortIndicator = {
    'asc': upArrow,
    'desc': dwnArrow,
    'none': updwnArrow,
    null: updwnArrow,
    undefined: updwnArrow
};
let nextSortDirection = {
    'asc': 'desc',
    'desc': 'asc',
    'none': 'desc',
    null: 'desc',
    undefined: 'desc'
};

let async_flag = true;
function async_run(f) {
    if (async_flag) {
        f();
        flag = false;
        setTimeout(async_run, 0);
    }
    return;
}

function show_waiting() {
    async_flag = true;
    function show() {
        hourglass.style.display = "block";
    }
    async_run(show);
}

function hide_waiting() {
    async_flag = true;
    function hide() {
        hourglass.style.display = "none";
    }
    async_run(hide);
}

// function checkSortString(sortString) {

//     if (sortString === null || sortString === undefined || sortString.length === 0)
//         // No sort string so sort by date of last push, newest at top.
//         sortString = "pushed:desc";

//     // Check sort string syntax.
//     if (! /^\w+:(a|d)\w*\s*$/.test(sortString)) {
//         alert(`Malformed sort: ${sortString}`);
//         return false;
//     }

//     return true;
// }

// function get_sort_column_and_direction(sortString) {
//     // Get the column to sort on.
//     [col, dir] = sortString.split(":", 2);
//     foundCol = findColumn(col, data);
//     if (foundCol === null) {
//         alert(`No column matches ${col}.`);
//         return;
//     }
//     return [foundCol, dir];
// }

// Populate the table in the web page with the rows of topic data.
function populateTable(data) {

    // Show the number of repos in the table.
    numRepos.textContent = `(${data.length} Repositories)`;

    if (repoTable !== null && repoTable !== undefined) {
        repoTable.destroy();
    }

    let columnDefs = [
        { className: 'repo', data: 'repo', title: 'Repo', "width": '25%' },
        { className: 'description', data: 'description', title: 'Description', "width": '40%' },
        { className: 'owner', data: 'owner', title: 'Owner', "width": '10%' },
        { className: 'stars', data: 'stars', title: 'Stars', "width": '5%' },
        { className: 'forks', data: 'forks', title: 'Forks', "width": '5%' },
        { className: 'size', data: 'size', title: 'Size', "width": '5%' },
        { className: 'date', data: 'pushed', title: 'Pushed', "width": '10%' }
    ];

    function columnNameToIndex(name) {
        return columnDefs.findIndex((col) => col.className === name);
    }

    repoTable = new DataTable('#dataTable', {
        scrollX: false,
        data: data,
        columns: columnDefs,
        order: [[columnNameToIndex('date'), 'desc']]
    });

    hide_waiting();

    return;
}

// Find the column index for a given column name.
function findColumn(column, data) {
    let col = column.toLowerCase();
    // Search for a column whose label starts with the given column name.
    let foundCol = null;
    for (let column of Object.keys(data[0])) {
        if (column.toLowerCase().startsWith(col)) {
            // Found one.
            foundCol = column;
            break;
        }
    }
    return foundCol;
}

// Filter the data based on the contents of the filter field.
function filterData(data) {

    tableData = [...data];
    let filterStr = filterInput.value.trim();

    if (filterStr === null || filterStr === undefined || filterStr.length === 0) {
        // Filter string is blank so restore all repo data.
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

filterInput.addEventListener("search", function (event) {
    show_waiting();
    filterString = filterInput.value;
    if (filterString.length === 0) {
        // Clear filtering if the "X" in the filter field is clicked or the field is empty.
        clearFilter();
        tableData = [...topicData]; // Clearing filter causes all topic data to be shown.
        populateTable(tableData);
        // sortTable(sortString);  // Sort the table based on the contents of a column and a direction (ascending/descending).
    }
    else {
        // Filter the table based on the contents of the non-empty filter field.
        tableData = filterData(topicData);
        populateTable(tableData);
        // sortTable(sortString);
    }
});

// Sort a table of data based on the contents of a column as specified by column name:direction.
function sortData(data, sortString) {

    if (data === null || data === undefined || data.length === 0) {
        // No data to sort.
        return;
    }

    clearSortDirections(data);

    if (sortString === null || sortString === undefined || sortString.length === 0)
        // No sort string so sort by date of last push, newest at top.
        sortString = "pushed:desc";

    // Check sort string syntax.
    if (! /^\w+:(a|d)\w*\s*$/.test(sortString)) {
        alert(`Malformed sort: ${sortString}`);
        return;
    }

    // Get the column to sort on.
    [col, dir] = sortString.split(":", 2);
    foundCol = findColumn(col, data);
    if (foundCol === null) {
        alert(`No column matches ${col}.`);
        return;
    }

    // Sort the data on the specified column.
    if (dir.startsWith("a")) {
        // Ascending values as they go downward in the table.
        data.sort((a, b) => (a[foundCol] > b[foundCol]) ? 1 : -1);
        sortDirection[foundCol] = "asc";
    }
    else {
        // Descending values as they go downward in the table.
        data.sort((a, b) => (a[foundCol] < b[foundCol]) ? 1 : -1);
        sortDirection[foundCol] = "desc";
    }
}

// *** Called from column header injected into table in index.html. ***
// Sort the table based on the contents of a column and its sorting button state.
function sortTable(sortString) {
    sortData(tableData, sortString);
    populateTable(tableData);
}

// Clear sort directions for all columns of data.
function clearSortDirections(data) {
    let columns = Object.keys(data[0]);
    for (column of columns) {
        sortDirection[column] = "none";
    }
}

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

// Load the rows of Github repo data from the JSON file for that topic, filter and sort them, and then display the table.
function loadTopic() {

    let jsonFile = topicSelector.value;
    if (jsonFile === "") {
        topicTitle.textContent = "";
        return;
    }

    show_waiting();

    topicTitle.textContent = topicSelector.options[topicSelector.selectedIndex].text;

    // Load the rows of Github repo data from the JSON file.
    fetch(jsonFile + '.json')
        .then(response => response.json())
        .then(data => {
            topicData = [...data];
            clearSortDirections(topicData);
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
    sortString = "pushed:desc"; // New topic so use default sorting by last push date, newest at top.
    loadTopic(); // Load the rows of Github repo data from the JSON file for that topic, filter and sort them, and then display the table.
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

    let sort = null;
    if (queryParams.has('sort')) {
        // A column & direction for sorting was specified in the URL query string.
        sort = preprocessParam(queryParams.get('sort'));
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

            // Load the data for the selected topic.
            loadTopic();
        })
}
