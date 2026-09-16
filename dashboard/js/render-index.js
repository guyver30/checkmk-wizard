// Overview page (DASH-01): the stats-by-state strip plus the grouped fleet overview.
//
// Registers ViewModules.index. Calls store.devices/store.subscribe() indirectly
// through shell.js's dispatch (never attaches its own mqtt.js listener or parses a
// payload) and reuses displayName()/effectiveState()/stateClass()/deviceTypeIcon()/
// isDeviceStale() (display.js/staleness.js), SEVERITY_RANK/buildGroupIndex()/
// rollUpGroup()/sortedGroupKeys() (grouping.js) and renderShell.groupingMode()/
// renderShell.pollerStale (render-shell.js) as globals -- this module does not
// redefine them.
//
// Script-order note: in index.html/devices.html this file's <script> tag loads
// BEFORE shell.js's, and shell.js's own top-level `var ViewModules = {};` runs
// unconditionally the moment its script executes -- which, because `var`'s
// initializer always runs regardless of any prior value, would silently wipe out a
// synchronous `ViewModules.index = ...` assignment made here before shell.js ever
// reads it (verified: a `var x = {}` statement always re-executes its assignment,
// hoisting only creates the binding, not a guard). Rather than edit shell.js (out of
// this plan's `files_modified`), this module defers the actual assignment into its
// own DOMContentLoaded listener. All script tags run synchronously in document
// order before DOMContentLoaded ever fires, so by the time any DOMContentLoaded
// listener runs, shell.js's `var ViewModules = {}` has already executed; and because
// listeners fire in registration order, this file's listener (registered while this
// script executes, earlier in document order) fires before shell.js's own listener
// (which performs the initial mount()), so ViewModules.index is always populated in
// time.
//
// Hard rendering rule (T-11-19): build DOM with document.createElement and set text
// with textContent -- never assign raw markup built from an interpolated string.
// Every value here (alias, folder, device_type) originates from Checkmk where an
// operator may type anything.

(function () {
  var STATE_ORDER = ["OK", "WARN", "CRIT", "UNKNOWN", "UNREACH", "DOWN"];
  var ALL_STAT_KEYS = STATE_ORDER.concat(["STALE"]);

  var rootEl = null;
  var statsStripEl = null;
  var overviewGridEl = null;
  var groupingListenerAttached = false;

  function emptyState() {
    var wrap = document.createElement("div");
    wrap.className = "empty-state";
    var h2 = document.createElement("h2");
    h2.textContent = "Waiting for device data…";
    var p = document.createElement("p");
    p.textContent =
      "No devices have reported yet. Once the poller publishes topology, hosts will appear here automatically.";
    wrap.appendChild(h2);
    wrap.appendChild(p);
    return wrap;
  }

  // Reuses the static container from a cold load of this page when present;
  // builds a fresh one when this view is mounted after an in-app pushState
  // navigation from a different page's markup (D-23), where #main still holds the
  // previous page's DOM.
  function ensureContainer(mainEl, id) {
    var el = document.getElementById(id);
    if (!el || !mainEl.contains(el)) {
      el = document.createElement("div");
      el.id = id;
      mainEl.appendChild(el);
    }
    return el;
  }

  // ---------------------------------------------------------------------
  // Stats strip (DASH-01)
  // ---------------------------------------------------------------------

  function countsByState() {
    var counts = {};
    STATE_ORDER.forEach(function (state) {
      counts[state] = 0;
    });
    var staleCount = 0;
    store.devices.forEach(function (payload) {
      // Read the derived state, never the raw `state` key, so UNREACH is counted
      // separately from DOWN (Pitfall 6, 11-RESEARCH.md) instead of double-counting
      // toward DOWN.
      var state = effectiveState(payload);
      if (!(state in counts)) {
        counts[state] = 0;
      }
      counts[state] += 1;
      if (isDeviceStale(payload)) {
        staleCount += 1;
      }
    });
    counts.STALE = staleCount;
    return counts;
  }

  function statElement(key) {
    var stat = document.createElement("div");
    stat.className = "stat";
    stat.dataset.statKey = key;
    var value = document.createElement("span");
    value.className = "stat-value";
    value.textContent = "0";
    var label = document.createElement("span");
    label.className = "stat-label";
    label.textContent = key;
    stat.appendChild(value);
    stat.appendChild(label);
    return stat;
  }

  function buildStatsStrip() {
    statsStripEl.replaceChildren.apply(statsStripEl, ALL_STAT_KEYS.map(statElement));
    updateStatsStrip();
  }

  // Recomputes the counts and writes only the changed numerals via textContent --
  // never rebuilds the strip's own DOM, because a rebuild would reflow the overview
  // grid beneath it on every single-device message.
  function updateStatsStrip() {
    var counts = countsByState();
    ALL_STAT_KEYS.forEach(function (key) {
      var stat = statsStripEl.querySelector('[data-stat-key="' + key + '"]');
      if (!stat) {
        return;
      }
      var valueEl = stat.querySelector(".stat-value");
      if (!valueEl) {
        return;
      }
      var next = String(counts[key] || 0);
      if (valueEl.textContent !== next) {
        valueEl.textContent = next;
      }
    });
  }

  // ---------------------------------------------------------------------
  // Grouped fleet overview (D-05/D-06/D-07/D-15/D-24)
  //
  // This container is the slot Phase 13's live topology map replaces wholesale
  // (D-24) -- it is written self-contained on purpose, a drop-in replacement
  // rather than something later code needs to unpick.
  // ---------------------------------------------------------------------

  // Mirrors render-shell.js's hostRowElement() exactly so the tree and the
  // overview render a host identically: the device-type icon only appears in
  // folder mode (device_type mode's own group name already carries that
  // classification, D-07), the DOWN marker is unconditional, and the label is
  // always displayName().
  function chipElement(hostId, mode) {
    var payload = store.devices.get(hostId);
    var chip = document.createElement("div");
    chip.className = "overview-chip";
    chip.dataset.host = hostId;

    var state = effectiveState(payload);
    chip.classList.add(stateClass(state));
    if (isDeviceStale(payload) || renderShell.pollerStale) {
      chip.classList.add("is-stale");
    }

    if (state === "DOWN") {
      var downIcon = document.createElement("span");
      downIcon.className = "icon icon-close-circle-filled";
      downIcon.setAttribute("role", "img");
      downIcon.setAttribute("title", "Down");
      downIcon.setAttribute("aria-label", "Down");
      chip.appendChild(downIcon);
    }

    if (mode === "folder") {
      var deviceType = payload ? payload.device_type : undefined;
      var typeIcon = document.createElement("span");
      typeIcon.className = "icon " + deviceTypeIcon(deviceType);
      typeIcon.setAttribute("role", "img");
      typeIcon.setAttribute("title", deviceType || "Unknown type");
      typeIcon.setAttribute("aria-label", deviceType || "Unknown type");
      chip.appendChild(typeIcon);
    }

    var name = document.createElement("span");
    name.className = "overview-chip-name";
    name.textContent = displayName(payload);
    chip.appendChild(name);

    return chip;
  }

  function cardHeaderElement(key) {
    var header = document.createElement("div");
    header.className = "overview-card-header";

    var name = document.createElement("span");
    name.className = "overview-card-name";
    name.textContent = key;
    header.appendChild(name);

    var badge = document.createElement("span");
    badge.className = "count-badge";
    header.appendChild(badge);

    return header;
  }

  // Applies the worst-of state color (as the `data-state` attribute
  // dashboard.css's `.overview-card[data-state="..."]` rule already keys its 4px
  // left border on), the D-15 stale hatch, and the D-06 count badge -- shared by
  // both the full build and the per-device patch path so the two can never drift.
  function applyCardState(card, rollup) {
    card.dataset.state = rollup.worst.toLowerCase();
    card.classList.toggle("is-stale", rollup.hatched || renderShell.pollerStale);
    var badge = card.querySelector(".count-badge");
    if (badge) {
      badge.textContent = rollup.nonOkCount + " / " + rollup.total;
    }
  }

  function cardElement(key, idsSet, mode) {
    var ids = Array.from(idsSet).sort(function (a, b) {
      return displayName(store.devices.get(a)).localeCompare(displayName(store.devices.get(b)));
    });
    var rollup = rollUpGroup(ids, store.devices);

    var card = document.createElement("div");
    card.className = "overview-card";
    card.dataset.groupKey = key;
    card.appendChild(cardHeaderElement(key));
    applyCardState(card, rollup);

    var body = document.createElement("div");
    body.className = "overview-card-body";
    ids.forEach(function (id) {
      body.appendChild(chipElement(id, mode));
    });
    card.appendChild(body);

    return card;
  }

  function buildOverview() {
    var mode = renderShell.groupingMode();
    var index = buildGroupIndex(store.devices, mode);
    var keys = sortedGroupKeys(index);
    var cards = keys.map(function (key) {
      return cardElement(key, index.get(key), mode);
    });
    overviewGridEl.replaceChildren.apply(overviewGridEl, cards);
  }

  function renderOverview() {
    if (store.devices.size === 0) {
      overviewGridEl.replaceChildren(emptyState());
      return;
    }
    buildOverview();
  }

  // A per-device status change patches only that host's chip plus its own group's
  // badge/color/hatch -- never a full grid rebuild (DASH-01 "merge in place").
  function patchOverviewDevice(hostname) {
    var payload = store.devices.get(hostname);
    if (!payload) {
      // Tombstoned -- group membership changed, a full rebuild is required.
      renderOverview();
      return;
    }
    var existingChip = overviewGridEl.querySelector('[data-host="' + CSS.escape(hostname) + '"]');
    if (!existingChip) {
      // Not present in the current grouping yet (e.g. topology has not caught up)
      // -- full rebuild.
      renderOverview();
      return;
    }

    var mode = renderShell.groupingMode();
    var freshChip = chipElement(hostname, mode);
    existingChip.replaceWith(freshChip);

    var card = freshChip.closest(".overview-card");
    if (!card) {
      return;
    }
    var key = card.dataset.groupKey;
    var index = buildGroupIndex(store.devices, mode);
    var ids = index.get(key);
    if (ids) {
      applyCardState(card, rollUpGroup(ids, store.devices));
    }
  }

  // ---------------------------------------------------------------------
  // Grouping-mode toggle
  //
  // shell.js's dispatch only fans out "device"/"topology"/"history"/"events"/
  // "poller" -- render-shell.js's own grouping-toggle click handler (11-06) calls
  // its own renderTree() directly rather than notifying view modules, so there is
  // no changeKind for a grouping-mode flip. This module listens to the same
  // button directly instead, which the tree's own listener also does, so both
  // react to one click without either needing to know about the other.
  // ---------------------------------------------------------------------

  function handleGroupingToggleClick() {
    if (!rootEl) {
      return; // Not currently mounted.
    }
    renderOverview();
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
    statsStripEl = ensureContainer(mainEl, "stats-strip");
    overviewGridEl = ensureContainer(mainEl, "overview-grid");
    attachGroupingToggleListener();
    buildStatsStrip();
    renderOverview();
  }

  function update(changeKind, arg) {
    if (!rootEl) {
      return;
    }
    if (changeKind === "device") {
      updateStatsStrip();
      if (store.devices.size === 0) {
        overviewGridEl.replaceChildren(emptyState());
      } else {
        patchOverviewDevice(arg);
      }
    } else if (changeKind === "topology") {
      updateStatsStrip();
      renderOverview();
    } else if (changeKind === "poller") {
      // D-14: every card and chip gains the stale hatch while its last known
      // values stay legible -- a full re-render is the same infrequent-event
      // tradeoff render-shell.js's own renderPollerBanner() makes for the tree.
      renderOverview();
    }
    // "history" and "events" changes have no representation on this page.
  }

  function unmount() {
    rootEl = null;
    statsStripEl = null;
    overviewGridEl = null;
  }

  document.addEventListener("DOMContentLoaded", function () {
    window.ViewModules = window.ViewModules || {};
    ViewModules.index = {
      id: "index",
      mount: mount,
      update: update,
      unmount: unmount,
    };
  });
})();
