// Elements of the web page.
let topicSelector = document.getElementById('topicSelector');
let topicTitle = document.getElementById("topicTitle");
let filterInput = document.getElementById('filterField');
let numRepos = document.getElementById('numRepos');

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

// Create an indeterminate progress bar upon page load.
$("#progressbar").progressbar({
    value: false
});

// Update the progress bar with the progress value between 0..100.
function updateProgressBar(progress) {
    let bar = $("#progressbar");
    if (progress < 100) {
        // Show the progress bar if the progress is less than 100.
        // This also shows an indeterminate progress bar if progress is Boolean false.
        bar.show();
        bar.progressbar("option", "value", progress);
    }
    else {
        // Hide progress bar once progress reaches or exceeds 100.
        bar.hide();
    }
}

// Populate the table in the web page with the rows of topic data.
function populateTable(data) {

    if(repoTable !== null && repoTable !== undefined) {
        repoTable.destroy();
    }

    repoTable = new DataTable('#dataTable', {
        data: data,
            "language": {
                "processing": "DataTables is currently busy"
            },
            columns: [
                { className: 'repo', data: 'repo', title: 'Repo' },
                { className: 'description', data: 'description', title: 'Description' },
                { className: 'owner', data: 'owner', title: 'Owner' },
                { className: 'stars', data: 'stars', title: 'Stars' },
                { className: 'forks', data: 'forks', title: 'Forks' },
                { className: 'size', data: 'size', title: 'Size' },
                { className: 'date', data: 'pushed', title: 'Pushed' }
            ],
            order: [[6, 'desc']]
    });

    // Show the number of repos in the table.
    showRepoCount(data);

    return;


    // Create empty table.
    const table = document.getElementById('dataTable');
    table.innerHTML = '';

    // Don't display table if it's empty.
    if (data === null || data === undefined || data.length === 0) {
        // Show the number of repos (0) in the table.
        showRepoCount(data);
        return;
    }

    // One table column for each field of a row of data.
    let columns = Object.keys(data[0]); // Get column headers from total data set.

    function makeColumnSortFunction(column, direction) {
        return function () { sortTable(column + ":" + direction); }
    }

    // Create header for the table.
    let headerRow = document.createElement('tr');
    columns.forEach(column => {

        // Create header for a column of the table.
        let th = document.createElement('th');
        th.classList.add(column);

        // Add a div to hold the text of the column header.
        let div_column = document.createElement('div');
        // Capitalize the first letter of the column name.
        div_column.innerHTML = column.charAt(0).toUpperCase() + column.slice(1);
        div_column.className = "column";
        th.appendChild(div_column);

        // Add sorting buttons to every column except the project name and description.
        if (!['repo', 'description'].includes(column)) {
            let div_updwn = document.createElement('div');
            div_updwn.className = "sort-button";
            div_updwn.innerHTML = '&nbsp;' + sortIndicator[sortDirection[column]];
            // div_updwn.innerHTML = '&nbsp;' + (sortDirection[column] === 'asc' ? upArrow : dwnArrow);
            // let direction = sortDirection in ['asc', 'desc'] ? sortDirection : 'desc';
            div_updwn.onclick = makeColumnSortFunction(column, nextSortDirection[sortDirection[column]]);
            th.appendChild(div_updwn);
        }

        headerRow.appendChild(th);
    });

    // Add the header row to the table.
    let thead = document.createElement('thead');
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Create rows of data for the table.
    let tbody = document.createElement('tbody');
    let show_table = true;
    let idx = 0;

    // Function to add table rows in sections and allow progress bar to update.
    function dataRows() {
        while (idx < data.length) {

            // Create a row of data.
            let tr = document.createElement('tr');
            tr.className = idx % 2 === 0 ? 'even-row' : 'odd-row';
            row = data[idx++]; // Get data and inc index to next row.
            columns.forEach(column => {
                let td = document.createElement('td');
                td.innerHTML = row[column];
                td.classList.add(column);
                tr.appendChild(td);
            });
            tbody.appendChild(tr);

            if (idx % 1000 === 0) {
                // This set of data rows is done, so process the next set.
                updateProgressBar((100 * idx) / data.length);
                setTimeout(dataRows, 0); // Set up to process next set of data upon return.
                return; // Leave func so progress bar updates.
            }
        }

        if (show_table) {
            // Display an indeterminate progress bar while body is added to table.
            updateProgressBar(false); // indeterminate progress bar.
            show_table = false; // Don't come back here.
            setTimeout(dataRows, 0); // When we exit, set up to come back to the next phase.
            return; // Leave func so progress bar updates.
        }

        // Add the body to the table. This will take a while (multiple seconds)!
        table.appendChild(tbody);
        updateProgressBar(100);
    }
    dataRows();

    // Show the number of repos in the table.
    showRepoCount(data);
}

// Show the number of repos in the table.
function showRepoCount(data) {
    numRepos.textContent = `(${data.length} repos shown)`;
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

// Initiate filtering if return/enter key is pressed.
filterInput.addEventListener("keypress", function (event) {
    if (event.key === "Enter") {
        event.preventDefault();
        document.getElementById("filterButton").click();
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
    topicTitle.textContent = topicSelector.options[topicSelector.selectedIndex].text;

    // Load the rows of Github repo data from the JSON file.
    fetch(jsonFile + '.json')
        .then(response => response.json())
        .then(data => {
            topicData = [...data];
            clearSortDirections(topicData);
            preprocessData(topicData);
            tableData = filterData(topicData)
            sortTable(sortString)
        });
}

// Clear filter so all data will be shown in table.
function clearFilter(){
    filterInput.placeholder = "Column:Value";
    filterInput.value = "";
    tableData = [];
}

// *** Called from index.html. ***
// The filter button was clicked, so extract any topic data matching the filter string and display it in the table.
function filterCallback(){
    tableData = filterData(topicData);
    sortTable(sortString);  // Sort the table based on the contents of a column and a direction (ascending/descending).
}

// *** Called from index.html. ***
// The clear filter button was clicked.
function clearFilterCallback(){
    clearFilter();
    tableData = [...topicData]; // Clearing filter causes all topic data to be shown.
    sortTable(sortString);  // Sort the table based on the contents of a column and a direction (ascending/descending).
}

// *** Called from index.html. ***
// A topic has been selected from the topic selector, so display that topic's data.
function topicCallback(){
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
