let jsonData = [];
let sortDirection = {};

let topicSelector = document.getElementById('topicSelector');
let topicTitle = document.getElementById("topicTitle");

window.onload = function () {
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
        });
    loadTopic();
}

function loadTopic() {
    jsonFile = topicSelector.value;
    if (jsonFile === "")
        return;
    topicTitle.textContent = topicSelector.options[topicSelector.selectedIndex].text;
    // Load the rows of Github repo data from the JSON file.
    // fetch('https://devbisme.github.io/RepoRecon/freecad_repos.json')
    fetch(jsonFile + '.json')
        .then(response => response.json())
        .then(data => {
            preprocessData(data);
            jsonData = data;
            showAllRepos(); // New topic so clear repo filter and show all repos.
        });
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

                case 'updated':
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
        delete row.pushed;
        delete row.id;
    })
}

function populateTable(data) {

    // Creat empty table.
    const table = document.getElementById('dataTable');
    table.innerHTML = '';

    // One table column for each field of a row of data.
    let columns = Object.keys(jsonData[0]); // Get column headers from total data set.

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

let filteredData = null;
let filterInput = document.getElementById('filterField');

function filterTable() {
    filterStr = filterInput.value.trim();

    if (filterStr === null || filterStr === undefined || filterStr.length === 0) {
        // Filter string is blank so restore all repo data.
        showAllRepos();  // Clear the filter field and show all repo data.
        return;
    }

    // Check filter string syntax.
    if (! /^\w+:(\w+\s*)+$/.test(filterStr)) {
        alert(`Malformed filter: ${filterStr}`);
        return;
    }

    // Get the column to search in for a space-delimited list of values.
    [col, vals] = filterStr.split(":", 2);
    col = col.toLowerCase();
    // Search for a column whose label starts with the given column name.
    foundCol = null;
    for (let column of Object.keys(jsonData[0])) {
        if (column.toLowerCase().startsWith(col)) {
            // Found one.
            foundCol = column;
            break;
        }
    }
    if (foundCol === null) {
        alert(`No column matches ${col}.`);
        return;
    }

    // Search for rows containing all the search values.
    filteredData = [...jsonData]; // Start with all the data rows.
    for (val of vals.split(" ")) {
        // Retain only the remaining rows that match the current value in the array of values.
        filteredData = filteredData.filter(row => row[foundCol].toLowerCase().includes(val.toLowerCase()));
    }

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

// Clear the filter field and show all rows of the repo data.
function showAllRepos() {
    filterInput.placeholder = "Column:Value";
    filterInput.value = "";
    filteredData = null;
    sortTableDesc(jsonData, "updated"); // Show *ALL* repos sorted by date of last update, newest at top.
}

// Sort the table based on the contents of a column and its sorting button state.
function sortTable(column) {
    // If the data has been filtered, then sort that. Otherwise, sort all the data.
    sortData = (filteredData === null) ? jsonData : filteredData;
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

numReposField = document.getElementById('numRepos');

// Show the number of repos in the table.
function showRepoCount() {
    if (filteredData === null)
        numReposField.textContent = `(${jsonData.length} total repos)`;
    else
        numReposField.textContent = `(${filteredData.length} filtered repos)`;
}

function hideRepoCount() {
    numReposField.textContent = "";
}
