// Elements of the web pageXOffset.
let topicSelector = document.getElementById('topicSelector');
let topicTitle = document.getElementById("topicTitle");
let filterInput = document.getElementById('filterField');
let numRepos = document.getElementById('numRepos');

// Arrays for storing topic data for display in the table.
let topicData = [];
let filteredData = null;

// Column and direction for sorting table data.
let sortString = null;
let sortDirection = {};


// Find the column index for a given column name.
function findColumn(column, data = topicData) {
    col = column.toLowerCase();
    // Search for a column whose label starts with the given column name.
    foundCol = null;
    for (let column of Object.keys(data[0])) {
        if (column.toLowerCase().startsWith(col)) {
            // Found one.
            foundCol = column;
            break;
        }
    }
    return foundCol;
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
    queryParams = new URLSearchParams(window.location.search);

    topic = null;
    if (queryParams.has('topic')) {
        // A topic was specified in the URL query string.
        topic = preprocessParam(queryParams.get('topic'));
    }

    filter = null;
    if (queryParams.has('filter')) {
        // A filter was specified in the URL query string.
        filter = preprocessParam(queryParams.get('filter'));
    }

    sort = null;
    if (queryParams.has('sort')) {
        // A column & direction for sorting was specified in the URL query string.
        sort = preprocessParam(queryParams.get('sort'));
    }

    return [topic, filter, sort];
}

// Preprocess the rows of data.
function preprocessData(data) {
    columns = Object.keys(data[0]);
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
                    date = row[column];
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

// *** Called from index.html. ***
// Load the rows of Github repo data from the JSON file for that topic and display them.
function loadTopic() {

    jsonFile = topicSelector.value;
    if (jsonFile === "") {
        topicTitle.textContent = "";
        return;
    }
    topicTitle.textContent = topicSelector.options[topicSelector.selectedIndex].text;

    // Load the rows of Github repo data from the JSON file.
    fetch(jsonFile + '.json')
        .then(response => response.json())
        .then(data => {
            topicData = data;
            preprocessData(topicData);
            filteredData = filterData(topicData)
            sortData(filteredData, sortString)
            populateTable(filteredData);
        });
}

// When the web page first appears, load the rows of Github repo data from the JSON file and display them.
window.onload = function () {
    [topic, filter, sort] = getQueryParams();
    filterInput.value = filter;
    sortString = sort;
    fetch("topics.json")
        .then(response => response.json())
        .then(data => {
            let option = document.createElement('option');
            option.value = "";
            option.text = "---Select a topic---";
            topicSelector.appendChild(option);
            data.forEach((topic, idx) => {
                // Add a new option to the topic selector.
                option = document.createElement('option');
                option.value = topic.JSON_file;
                option.text = topic.title;
                topicSelector.appendChild(option);
            });
            for (let option of topicSelector.options) {
                if (option.value === topic || option.text.toLowerCase().includes(topic)) {
                    // Found the topic in the selector.
                    topicSelector.selectedIndex = option.index;
                    break;
                }
            }
            loadTopic();
        })
}

// Populate the table in the web page with the rows of data.
function populateTable(data = topicData) {

    // Creat empty table.
    const table = document.getElementById('dataTable');
    table.innerHTML = '';

    // One table column for each field of a row of data.
    let columns = Object.keys(data[0]); // Get column headers from total data set.

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
            div_updwn.innerHTML = '&nbsp;' + (sortDirection[column] === 'asc' ? '&#9660;' : '&#9650;');
            div_updwn.onclick = function () { sortTable(column); }
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
    showRepoCount(); // Show the number of repos in the table.
}

// Filter the data based on the contents of the filter field.
function filterData(data = topicData) {
    filteredData = [...data];
    filterStr = filterInput.value.trim();

    if (filterStr === null || filterStr === undefined || filterStr.length === 0) {
        // Filter string is blank so restore all repo data.
        showAllRepos();  // Clear the filter field and show all repo data.
        return filteredData;
    }

    // Check filter string syntax.
    if (! /^\w+:(\w+\s*)+$/.test(filterStr)) {
        alert(`Malformed filter: ${filterStr}`);
        return filteredData;
    }

    // Get the column to search in.
    [col, vals] = filterStr.split(":", 2);
    foundCol = findColumn(col, data);
    if (foundCol === null) {
        alert(`No column matches ${col}.`);
        return filteredData;
    }

    // Search for rows where the specified column contains all the search values.
    filteredData = [...data]; // Start with all the data rows.
    for (val of vals.split(" ")) {
        // Retain only the remaining rows that match the current value in the array of values.
        filteredData = filteredData.filter(row => row[foundCol].toLowerCase().includes(val.toLowerCase()));
    }
    return filteredData;
}

// *** Called from index.html. ***
// Filter the table based on the contents of the filter field.
function filterTable(data = topicData) {

    // Filter the data based on the contents of the filter field.
    filteredData = filterData(data);

    // Show the rows (if any) that have all the search values.
    populateTable(filteredData);
}

// Initiate filtering if return/enter key is pressed.
filterInput.addEventListener("keypress", function (event) {
    if (event.key === "Enter") {
        event.preventDefault();
        document.getElementById("filterButton").click();
    }
});

// *** Called from index.html. ***
// Clear the filter field and show all rows of the repo data.
function showAllRepos() {
    filterInput.placeholder = "Column:Value";
    filterInput.value = "";
    filteredData = null;
    sortTableDesc(topicData, "pushed"); // Show *ALL* repos sorted by date of last push, newest at top.
}

// Sort a table of data based on the contents of a column as specified by column name:direction.
function sortData(data, sortString) {
    if (sortString === null || sortString === undefined || sortString.length === 0) {
        // No sort string so sort by date of last push, newest at top.
        sortTableDesc(data, "pushed");
        return;
    }

    // Check sort string syntax.
    if (! /^\w+:(asc|desc)$/.test(sortString)) {
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
    if (dir === 'asc')
        data.sort((a, b) => (a[foundCol] > b[foundCol]) ? 1 : -1);
    else
        data.sort((a, b) => (a[foundCol] < b[foundCol]) ? 1 : -1);
}

// Sort the table based on the contents of a column and its sorting button state.
function sortTable(column) {
    // If the data has been filtered, then sort that. Otherwise, sort all the data.
    sortData = (filteredData === null) ? topicData : filteredData;
    if (sortDirection[column] === 'asc')
        sortTableAsc(sortData, column);
    else
        sortTableDesc(sortData, column);
}

// Sort data into ascending values as it goes downward in the table.
function sortTableAsc(data, column) {
    let sortedData = [...data];
    sortedData.sort((a, b) => (a[column] > b[column]) ? 1 : -1);
    sortDirection[column] = 'desc';
    populateTable(sortedData);
}

// Sort data into descending values as it goes downward in the table.
function sortTableDesc(data, column) {
    let sortedData = [...data];
    sortedData.sort((a, b) => (a[column] < b[column]) ? 1 : -1);
    sortDirection[column] = 'asc';
    populateTable(sortedData);
}

// Show the number of repos in the table.
function showRepoCount() {
    if (filteredData === null)
        numRepos.textContent = `(${topicData.length} total repos)`;
    else
        numRepos.textContent = `(${filteredData.length} filtered repos)`;
}

// Hide the number of repos in the table.
function hideRepoCount() {
    numRepos.textContent = "";
}

// Update the progress bar with the progress value between 0..100.
function updateProgressBar(progress) {
    bar = $("#progressbar");
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

// Create an indeterminate progress bar upon page load.
$("#progressbar").progressbar({
    value: false
});
