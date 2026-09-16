// Device list page (DASH-02): the sortable live device table.
//
// Registers ViewModules.devices. Calls store.devices indirectly through shell.js's
// dispatch (never attaches its own mqtt.js listener or parses a payload) and reuses
// displayName()/effectiveState()/stateClass()/deviceTypeIcon()/formatRelativeTime()
// (display.js), isDeviceStale() (staleness.js), SEVERITY_RANK (grouping.js) and
// renderShell.groupingMode()/renderShell.pollerStale (render-shell.js) as globals --
// this module does not redefine them.
//
// Script-order note: see the header comment in render-index.js for the full
// explanation. In short, shell.js's own top-level `var ViewModules = {};` runs
// after this file's script tag and unconditionally re-executes its `{}`
// initializer, which would erase a synchronous `ViewModules.devices = ...`
// assignment made here. This module defers that assignment into its own
// DOMContentLoaded listener, registered while this script runs -- earlier in
// document order than shell.js's own listener that performs the initial mount().
//
// Hard rendering rule (T-11-19): build DOM with document.createElement and set
// text with textContent -- never assign raw markup built from an interpolated
// string. Every value here (alias, folder, device_type) originates from Checkmk
// where an operator may type anything.

(function () {
  var COLUMNS = [
    { key: "state", label: "State" },
    { key: "host", label: "Host" },
    { key: "type", label: "Type" },
    { key: "location", label: "Location" },
    { key: "lastUpdate", label: "Last Update" },
    { key: null, label: "Flags" },
  ];

  var rootEl = null;
  var tableEl = null;
  var emptyStateEl = null;
  var groupingListenerAttached = false;

  // Default sort: state severity worst-first (DOWN at the top), secondary key
  // Host ascending -- problems surface at the top of a live ops table rather
  // than alphabetical noise.
  var currentSort = { key: "state", direction: "desc" };

  function emptyStateContent() {
    var h2 = document.createElement("h2");
    h2.textContent = "Waiting for device data…";
    var p = document.createElement("p");
    p.textContent =
      "No devices have reported yet. Once the poller publishes topology, hosts will appear here automatically.";
    return [h2, p];
  }

  function buildTableSkeleton() {
    var table = document.createElement("table");
    table.id = "device-table";
    var thead = document.createElement("thead");
    var headerRow = document.createElement("tr");
    COLUMNS.forEach(function (column) {
      var th = document.createElement("th");
      if (column.key) {
        th.dataset.key = column.key;
      }
      th.textContent = column.label;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);
    table.appendChild(document.createElement("tbody"));
    return table;
  }

  // Reuses the static #device-table from a cold load of this page when present;
  // builds a fresh one when this view is mounted after an in-app pushState
  // navigation from a different page's markup (D-23), where #main still holds the
  // previous page's DOM.
  function ensureTable(mainEl) {
    var table = document.getElementById("device-table");
    if (!table || !mainEl.contains(table)) {
      table = buildTableSkeleton();
      mainEl.appendChild(table);
    }
    return table;
  }

  function ensureEmptyState(mainEl) {
    var el = mainEl.querySelector(".empty-state");
    if (el) {
      return el;
    }
    el = document.createElement("div");
    el.className = "empty-state";
    emptyStateContent().forEach(function (child) {
      el.appendChild(child);
    });
    mainEl.appendChild(el);
    return el;
  }

  function showEmptyState(show) {
    if (tableEl) {
      tableEl.hidden = show;
    }
    if (emptyStateEl) {
      emptyStateEl.hidden = !show;
    }
  }

  // ---------------------------------------------------------------------
  // Cell builders
  // ---------------------------------------------------------------------

  function stateCell(payload) {
    var td = document.createElement("td");
    var state = effectiveState(payload);
    var badge = document.createElement("span");
    badge.className = "state-badge " + stateClass(state);
    if (state === "DOWN") {
      var icon = document.createElement("span");
      icon.className = "icon icon-close-circle-filled";
      icon.setAttribute("role", "img");
      icon.setAttribute("title", "Down");
      icon.setAttribute("aria-label", "Down");
      badge.appendChild(icon);
    }
    var label = document.createElement("span");
    label.className = "state-label";
    label.textContent = state;
    badge.appendChild(label);
    td.appendChild(badge);
    return td;
  }

  function hostCell(payload) {
    var td = document.createElement("td");
    var span = document.createElement("span");
    span.style.fontFamily = "var(--font-mono)";
    span.textContent = displayName(payload);
    td.appendChild(span);
    return td;
  }

  function typeCell(payload) {
    var td = document.createElement("td");
    var deviceType = payload ? payload.device_type : undefined;
    var icon = document.createElement("span");
    icon.className = "icon " + deviceTypeIcon(deviceType);
    icon.setAttribute("role", "img");
    icon.setAttribute("title", deviceType || "Unknown type");
    icon.setAttribute("aria-label", deviceType || "Unknown type");
    td.appendChild(icon);
    var label = document.createElement("span");
    label.textContent = deviceType || "unknown";
    td.appendChild(label);
    return td;
  }

  function locationCell(payload) {
    var td = document.createElement("td");
    var folder = payload && typeof payload.folder === "string" ? payload.folder.trim() : "";
    td.textContent = folder || "(no folder)";
    return td;
  }

  function staleTooltip(payload) {
    var threshold = STALENESS_FACTOR * POLL_INTERVAL_SECONDS;
    var age = formatRelativeTime(payload && payload.timestamp);
    return "Last update " + age + " — exceeds the " + threshold + "s staleness window.";
  }

  function lastUpdateCell(payload) {
    var td = document.createElement("td");
    var span = document.createElement("span");
    span.style.fontFamily = "var(--font-mono)";
    span.textContent = formatRelativeTime(payload && payload.timestamp);
    td.appendChild(span);
    return td;
  }

  function flagBadge(iconClass, label) {
    var badge = document.createElement("span");
    badge.className = "state-badge";
    var icon = document.createElement("span");
    icon.className = "icon " + iconClass;
    icon.setAttribute("role", "img");
    icon.setAttribute("title", label);
    icon.setAttribute("aria-label", label);
    badge.appendChild(icon);
    return badge;
  }

  function flagsCell(payload) {
    var td = document.createElement("td");
    if (payload && payload.in_downtime) {
      td.appendChild(flagBadge("icon-pause-filled", "In downtime"));
    }
    if (payload && payload.acknowledged) {
      td.appendChild(flagBadge("icon-check-circle-filled", "Acknowledged"));
    }
    return td;
  }

  function rowElement(hostId, mode) {
    var payload = store.devices.get(hostId);
    var tr = document.createElement("tr");
    tr.dataset.id = hostId;
    // Sets the data-host attribute shell.js's router already intercepts clicks
    // on (D-23) -- this module adds no navigation handler of its own.
    tr.dataset.host = hostId;

    var deviceStale = isDeviceStale(payload);
    if (deviceStale || renderShell.pollerStale) {
      tr.classList.add("is-stale");
    }
    if (deviceStale) {
      tr.title = staleTooltip(payload);
    }

    tr.appendChild(stateCell(payload));
    tr.appendChild(hostCell(payload));
    tr.appendChild(typeCell(payload));
    // D-07: Location only carries meaning in folder mode -- device_type mode's
    // group already is the classification that matters, so the column (header
    // and cells alike) is omitted entirely rather than shown empty.
    if (mode === "folder") {
      tr.appendChild(locationCell(payload));
    }
    tr.appendChild(lastUpdateCell(payload));
    tr.appendChild(flagsCell(payload));
    return tr;
  }

  // ---------------------------------------------------------------------
  // Sorting
  // ---------------------------------------------------------------------

  function compareValueFor(payload, key) {
    if (key === "state") {
      var rank = SEVERITY_RANK[effectiveState(payload)];
      return rank === undefined ? SEVERITY_RANK.UNKNOWN : rank;
    }
    if (key === "host") {
      return displayName(payload);
    }
    if (key === "type") {
      return (payload && payload.device_type) || "";
    }
    if (key === "location") {
      return (payload && typeof payload.folder === "string" && payload.folder.trim()) || "";
    }
    if (key === "lastUpdate") {
      var parsed = Date.parse(payload && payload.timestamp);
      return Number.isNaN(parsed) ? 0 : parsed;
    }
    return "";
  }

  function compareIds(aId, bId) {
    var aPayload = store.devices.get(aId);
    var bPayload = store.devices.get(bId);
    var aVal = compareValueFor(aPayload, currentSort.key);
    var bVal = compareValueFor(bPayload, currentSort.key);
    var result = typeof aVal === "string" ? aVal.localeCompare(bVal) : aVal - bVal;
    if (currentSort.direction === "desc") {
      result = -result;
    }
    if (result === 0 && currentSort.key !== "host") {
      result = displayName(aPayload).localeCompare(displayName(bPayload));
    }
    return result;
  }

  function sortedIds() {
    return store.deviceIds().sort(compareIds);
  }

  function updateSortIndicators() {
    var thead = tableEl.querySelector("thead");
    if (!thead) {
      return;
    }
    thead.querySelectorAll("th[data-key]").forEach(function (th) {
      th.removeAttribute("aria-sort");
      var existingCaret = th.querySelector(".icon-caret-up-small, .icon-caret-down-small");
      if (existingCaret) {
        existingCaret.parentNode.removeChild(existingCaret);
      }
      if (th.dataset.key !== currentSort.key) {
        return;
      }
      var ascending = currentSort.direction === "asc";
      th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
      var caret = document.createElement("span");
      caret.className = "icon " + (ascending ? "icon-caret-up-small" : "icon-caret-down-small");
      caret.style.color = "var(--color-accent)";
      caret.setAttribute("role", "img");
      caret.setAttribute("title", ascending ? "Sorted ascending" : "Sorted descending");
      caret.setAttribute("aria-label", ascending ? "Sorted ascending" : "Sorted descending");
      th.appendChild(caret);
    });
  }

  function handleHeaderClick(event) {
    var th = event.target.closest ? event.target.closest("th[data-key]") : null;
    if (!th) {
      return;
    }
    var key = th.dataset.key;
    if (currentSort.key === key) {
      currentSort.direction = currentSort.direction === "asc" ? "desc" : "asc";
    } else {
      currentSort = { key: key, direction: "asc" };
    }
    updateSortIndicators();
    rebuildTbody();
  }

  function attachHeaderClickListener() {
    var thead = tableEl.querySelector("thead");
    if (!thead || thead.dataset.sortableBound === "true") {
      return;
    }
    thead.dataset.sortableBound = "true";
    thead.addEventListener("click", handleHeaderClick);
  }

  function updateLocationColumnVisibility(mode) {
    var th = tableEl.querySelector('th[data-key="location"]');
    if (th) {
      th.hidden = mode !== "folder";
    }
  }

  // A user action (a sort click, a topology change, a grouping-mode flip) is the
  // only thing allowed to rebuild the whole <tbody> -- ~21 rows is cheap to
  // rebuild on those infrequent events, but never on a per-message "device"
  // update (see patchRow below).
  function rebuildTbody() {
    var mode = renderShell.groupingMode();
    updateLocationColumnVisibility(mode);

    var tbody = tableEl.querySelector("tbody");
    if (!tbody) {
      return;
    }
    var ids = sortedIds();
    if (ids.length === 0) {
      tbody.replaceChildren();
      showEmptyState(true);
      return;
    }
    showEmptyState(false);
    var rows = ids.map(function (id) {
      return rowElement(id, mode);
    });
    tbody.replaceChildren.apply(tbody, rows);
  }

  // The update split is the requirement, not an optimization: locate the row by
  // its data-id (escaping the hostname per T-11-20, since a Checkmk host created
  // outside the wizard can carry characters that would otherwise widen the
  // selector) and replaceWith a freshly built single row.
  function patchRow(hostname) {
    var payload = store.devices.get(hostname);
    if (!payload) {
      // Tombstoned -- sort order and row count changed, a full rebuild is
      // required.
      rebuildTbody();
      return;
    }
    var tbody = tableEl.querySelector("tbody");
    if (!tbody) {
      return;
    }
    var existingRow = tbody.querySelector('tr[data-id="' + CSS.escape(hostname) + '"]');
    if (!existingRow) {
      // Not present yet -- the device is new, and a full rebuild plus re-sort is
      // correct.
      rebuildTbody();
      return;
    }
    var mode = renderShell.groupingMode();
    var freshRow = rowElement(hostname, mode);
    existingRow.replaceWith(freshRow);
  }

  // ---------------------------------------------------------------------
  // Grouping-mode toggle
  //
  // shell.js's dispatch only fans out "device"/"topology"/"history"/"events"/
  // "poller" -- render-shell.js's own grouping-toggle click handler (11-06) calls
  // its own renderTree() directly rather than notifying view modules, so there is
  // no changeKind for a grouping-mode flip. This module listens to the same
  // button directly instead.
  // ---------------------------------------------------------------------

  function handleGroupingToggleClick() {
    if (!rootEl) {
      return; // Not currently mounted.
    }
    rebuildTbody();
  }

  function attachGroupingToggleListener() {
    if (groupingListenerAttached) {
      return;
    }
    var toggle = document.getElementById("grouping-toggle");
    if (toggle) {
      toggle.addEventListener("click", handleGroupingToggleClick);
      groupingListenerAttached = true;
    }
  }

  // ---------------------------------------------------------------------
  // ViewModule contract
  // ---------------------------------------------------------------------

  function mount(mainEl, params) {
    rootEl = mainEl;
    tableEl = ensureTable(mainEl);
    emptyStateEl = ensureEmptyState(mainEl);
    currentSort = { key: "state", direction: "desc" };
    attachHeaderClickListener();
    attachGroupingToggleListener();
    updateSortIndicators();
    rebuildTbody();
  }

  function update(changeKind, arg) {
    if (!rootEl) {
      return;
    }
    if (changeKind === "device") {
      patchRow(arg);
    } else if (changeKind === "topology" || changeKind === "poller") {
      // D-14: a poller-stale flip needs every row's hatch recomputed; an
      // infrequent event, correctness over micro-optimization (same tradeoff
      // render-shell.js's own renderPollerBanner() makes for the tree).
      rebuildTbody();
    }
    // "history" and "events" changes have no representation on this page.
  }

  function unmount() {
    rootEl = null;
    tableEl = null;
    emptyStateEl = null;
  }

  document.addEventListener("DOMContentLoaded", function () {
    window.ViewModules = window.ViewModules || {};
    ViewModules.devices = {
      id: "devices",
      mount: mount,
      update: update,
      unmount: unmount,
    };
  });
})();
