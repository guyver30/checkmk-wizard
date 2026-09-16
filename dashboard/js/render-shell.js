// Persistent chrome shared by all three pages: the connection indicator, both
// banners, the grouped sidebar tree, the always-mounted event panel, and the
// sidebar-toggle/grouping-toggle controls.
//
// D-22/D-23 make this module's contract load-bearing: `sidebar-events` must
// never be re-created during navigation (shell.js swaps only `#main`), which
// is why the tree/events rendering lives here rather than in a per-page
// render module.
//
// Calls isDeviceStale()/isPollerStale()/pollerOfflineSince() (staleness.js),
// displayName()/effectiveState()/stateClass()/stateIcon()/deviceTypeIcon()/
// isTagGroupMissing()/formatClock() (display.js), and
// buildGroupIndex()/rollUpGroup()/sortedGroupKeys() (grouping.js) as globals
// -- this module does not redefine them (11-UI-SPEC.md Connection Indicator,
// Poller-offline banner, device_type tag-group-missing banner, Copywriting
// Contract, Accessibility, Responsive Behavior; 11-CONTEXT.md D-05, D-06,
// D-07, D-10, D-13, D-14, D-15, D-16, D-22).
//
// Hard rendering rule for this module and every later render module: build
// DOM with document.createElement and set text with textContent -- never
// assign raw markup built from an interpolated string. Every value here
// (alias, folder, device_type, event text) originates from Checkmk where an
// operator may type anything.

var renderShell = (function () {
  var GROUPING_MODE_KEY = "dashboard.groupingMode";

  // Locked copy strings (UI-SPEC Copywriting Contract) -- reproduced verbatim.
  var TAG_GROUP_BANNER_TEXT =
    "No device_type tag group on this site — run the wizard's tagging phase.";
  var NO_EVENTS_TEXT = "No events yet — state changes will appear here as they happen.";
  var NO_DEVICES_TEXT = "No devices have reported yet.";

  var pollerStale = false;
  var tagGroupBannerDismissed = false;
  var reconnectIconEl = null;
  var reconnectCountdownTimer = null;

  // Bug fixed 2026-09-16: every time-derived value in the UI (staleness, the `.is-stale`
  // hatch, relative "Nm ago" timestamps, the banner's age text) was computed only at render
  // time, and rendering was driven solely by `store.subscribe(...)` -- i.e. by incoming MQTT
  // messages (grep -n 'setInterval' dashboard/js/*.js found exactly one hit before this fix:
  // the reconnect countdown below). When the poller itself stops publishing, messages stop,
  // so nothing re-renders -- the one moment staleness matters most is also the one moment
  // guaranteed not to produce a new message. One page-wide clock, owned here because this
  // module already owns the cross-cutting chrome (banners, tree) shared by all three pages,
  // fixes the whole class rather than patching each frozen surface individually.
  //
  // POLL_INTERVAL_SECONDS (60s, config.js) would leave up to a minute of visibly wrong "ago"
  // text between ticks. These renders (a banner, ~20 tree rows) are small and purely local, so
  // a much shorter interval costs little; 12s keeps every time-derived surface within 12s of
  // correct without noticeably increasing CPU/DOM churn on a long-lived kiosk tab.
  var CLOCK_TICK_MS = 12000;
  var clockTimer = null;
  // Listeners registered by shell.js so the active per-page ViewModule (overview cards,
  // device table, detail panel) also re-renders its own time-derived surfaces on every tick,
  // without this module needing to know ViewModules exists (11-06's script-order contract
  // keeps this module ignorant of the per-page modules, on purpose).
  var tickListeners = [];

  // Which tree groups are collapsed, keyed by group key (folder path or
  // device_type value). renderTree() rebuilds the whole tree on every store
  // change (device state, topology, poller status, grouping-mode toggle) --
  // if collapse state lived only in the DOM it would be destroyed and reset
  // to "expanded" on the very next poll cycle. This Set is the durable
  // source of truth that groupElement() reads on every rebuild; renderTree()
  // itself never touches it.
  var collapsedGroupKeys = new Set();

  // Set whenever the operator toggles grouping, and the source of truth for
  // the rest of the session; storage is only how the choice SURVIVES a reload.
  // Without this, a browser that refuses the write would leave groupingMode()
  // re-reading the old stored value on the very next renderTree(), so the
  // toggle would flip its aria-pressed state and then silently not regroup.
  var groupingModeOverride = null;

  // Storage access is wrapped because reading it can THROW, not just return
  // null: a browser with site data blocked, a private window, or an embedded
  // frame with restricted storage all raise on access. groupingMode() runs
  // during init() and again on every renderTree(), so an unguarded throw here
  // took down the whole shell -- the sidebar, banners and event panel never
  // rendered -- over a remembered toggle position. D-07's device_type default
  // is the correct fallback when the preference cannot be read.
  function groupingMode() {
    if (groupingModeOverride !== null) {
      return groupingModeOverride;
    }
    var stored = null;
    try {
      stored = localStorage.getItem(GROUPING_MODE_KEY);
    } catch (err) {
      stored = null;
    }
    return stored === "folder" ? "folder" : "device_type";
  }

  function emptyState(text) {
    var wrap = document.createElement("div");
    wrap.className = "empty-state";
    var p = document.createElement("p");
    p.textContent = text;
    wrap.appendChild(p);
    return wrap;
  }

  // Adds the given icon class plus its accessible-name attributes to an
  // existing icon element, without disturbing any other class already on
  // it -- used both to build new icon-only elements and to defensively
  // enforce the iconography contract on icons that already exist in the
  // page's static markup (UI-SPEC Accessibility: "icons need text
  // alternatives").
  function ensureIcon(el, className, label) {
    if (!el) {
      return;
    }
    el.classList.add("icon", className);
    el.setAttribute("role", "img");
    el.setAttribute("title", label);
    el.setAttribute("aria-label", label);
  }

  function iconElement(className, label) {
    var el = document.createElement("span");
    ensureIcon(el, className, label);
    return el;
  }

  // ---------------------------------------------------------------------
  // Connection indicator (DASH-05)
  // ---------------------------------------------------------------------

  function clearReconnectCountdown() {
    if (reconnectCountdownTimer) {
      clearInterval(reconnectCountdownTimer);
      reconnectCountdownTimer = null;
    }
  }

  function removeReconnectIcon() {
    if (reconnectIconEl && reconnectIconEl.parentNode) {
      reconnectIconEl.parentNode.removeChild(reconnectIconEl);
    }
  }

  function ensureReconnectIcon(container, beforeEl) {
    if (!reconnectIconEl) {
      reconnectIconEl = iconElement("icon-refresh", "Reconnecting");
      reconnectIconEl.classList.add("is-spinning");
    }
    if (reconnectIconEl.parentNode !== container) {
      container.insertBefore(reconnectIconEl, beforeEl);
    }
  }

  function startReconnectCountdown(textEl, delayMs) {
    var remaining = Math.max(0, Math.ceil(delayMs / 1000));
    textEl.textContent = "Reconnecting in " + remaining + "s…";
    reconnectCountdownTimer = setInterval(function () {
      remaining -= 1;
      if (remaining < 0) {
        clearReconnectCountdown();
        return;
      }
      textEl.textContent = "Reconnecting in " + remaining + "s…";
    }, 1000);
  }

  // status is { phase: "connecting"|"connected"|"reconnecting"|"disconnected",
  // delayMs } from connection.onStatus() (mqtt-connection.js). Dot color is
  // set as an inline style rather than a `.state-*` class: `.connection-dot`
  // already sets its own `background-color` in dashboard.css, and a sibling
  // single-class `.state-ok`-style rule would lose to it on source order
  // (both selectors have equal specificity), not win on specificity the way
  // the compound `.icon.state-ok` rules elsewhere in the stylesheet do.
  function renderConnection(status) {
    var container = document.getElementById("connection-indicator");
    if (!container || !status) {
      return;
    }
    var dot = container.querySelector(".connection-dot");
    var text = container.querySelector(".connection-text");
    if (!dot || !text) {
      return;
    }

    clearReconnectCountdown();

    if (status.phase === "connecting") {
      dot.style.backgroundColor = "";
      removeReconnectIcon();
      text.textContent = "Connecting…";
    } else if (status.phase === "connected") {
      dot.style.backgroundColor = "var(--state-ok)";
      removeReconnectIcon();
      text.textContent = "Connected";
    } else if (status.phase === "reconnecting") {
      dot.style.backgroundColor = "var(--state-warn)";
      ensureReconnectIcon(container, text);
      startReconnectCountdown(text, status.delayMs || 0);
    } else if (status.phase === "disconnected") {
      dot.style.backgroundColor = "var(--state-crit)";
      removeReconnectIcon();
      text.textContent = "Disconnected — retrying";
    }
  }

  // ---------------------------------------------------------------------
  // Banners (D-13/D-14 poller-offline, D-16 tag-group-missing)
  // ---------------------------------------------------------------------

  function pollerBannerText(pollerStatus) {
    // store.lastKnownPollerTimestamp (state-store.js) covers the bare `{"status":"offline"}`
    // will payload, which carries neither `last_poll` nor `since` of its own (Bug fixed
    // 2026-09-16 -- see state-store.js and staleness.js for the full reasoning).
    var offlineSince = pollerOfflineSince(pollerStatus, store.lastKnownPollerTimestamp);
    var clock = offlineSince ? formatClock(offlineSince.toISOString()) : "unknown";
    var minutes = offlineSince
      ? Math.max(0, Math.floor((Date.now() - offlineSince.getTime()) / 60000))
      : 0;
    return "Poller offline since " + clock + " — data is " + minutes + " minutes old";
  }

  function renderPollerBanner() {
    var banner = document.getElementById("poller-banner");
    var stale = isPollerStale(store.pollerStatus);
    var changed = stale !== pollerStale;
    pollerStale = stale;

    if (banner) {
      ensureIcon(banner.querySelector(".icon"), "icon-warning-circle-filled", "Poller offline");
      banner.hidden = !stale;
      if (stale) {
        var textEl = banner.querySelector(".poller-banner-text");
        if (textEl) {
          textEl.textContent = pollerBannerText(store.pollerStatus);
        }
      }
    }

    // The hatch is derived per-row/per-group from this flag (D-14: "every
    // row and tile gains the stale hatch"), so a change here requires
    // recomputing the whole tree, not just the banner.
    if (changed) {
      renderTree();
    }
  }

  function anyDeviceMissingTagGroup() {
    var missing = false;
    store.devices.forEach(function (payload) {
      if (isTagGroupMissing(payload)) {
        missing = true;
      }
    });
    return missing;
  }

  function renderTagGroupBanner() {
    var banner = document.getElementById("tag-group-banner");
    if (!banner) {
      return;
    }
    ensureIcon(banner.querySelector(".icon"), "icon-info-filled", "Configuration notice");
    ensureIcon(banner.querySelector(".dismiss-button .icon"), "icon-close-cross", "Dismiss");

    var shouldShow = anyDeviceMissingTagGroup() && !tagGroupBannerDismissed;
    if (!shouldShow) {
      banner.hidden = true;
      return;
    }
    var textEl = banner.querySelector(".tag-group-banner-text");
    if (textEl) {
      textEl.textContent = TAG_GROUP_BANNER_TEXT;
    }
    banner.hidden = false;
  }

  function renderBanners() {
    renderPollerBanner();
    renderTagGroupBanner();
  }

  // ---------------------------------------------------------------------
  // Grouped sidebar tree (D-05/D-06/D-07/D-15)
  // ---------------------------------------------------------------------

  function stateChip(stateValue) {
    var span = document.createElement("span");
    span.className = "event-state-chip";
    if (!stateValue) {
      span.textContent = "—";
      return span;
    }
    var cls = stateClass(stateValue);
    span.classList.add(cls);
    span.appendChild(iconElement(stateIcon(stateValue), stateValue));
    var label = document.createElement("span");
    label.className = "state-label";
    label.textContent = stateValue;
    span.appendChild(label);
    return span;
  }

  function hostRowElement(id, mode) {
    var payload = store.devices.get(id);
    var row = document.createElement("div");
    row.className = "tree-host-row";
    row.dataset.host = id;
    row.tabIndex = 0;

    var state = effectiveState(payload);
    var cls = stateClass(state);
    row.classList.add(cls);
    if (isDeviceStale(payload) || pollerStale) {
      row.classList.add("is-stale");
    }

    if (state === "DOWN") {
      row.appendChild(iconElement("icon-close-circle-filled", "Down"));
    }

    if (mode === "folder") {
      var deviceType = payload ? payload.device_type : undefined;
      row.appendChild(iconElement(deviceTypeIcon(deviceType), deviceType || "Unknown type"));
    }

    var label = document.createElement("span");
    label.className = "tree-host-name";
    label.textContent = displayName(payload);
    row.appendChild(label);

    row.setAttribute("aria-label", displayName(payload) + " — " + state);
    return row;
  }

  function updateGroupHeader(header, rollup) {
    if (!header) {
      return;
    }
    header.classList.remove(
      "state-ok",
      "state-warn",
      "state-crit",
      "state-down",
      "state-unknown",
      "state-unreach",
      "state-pend",
      "is-stale",
    );
    header.classList.add(stateClass(rollup.worst));
    if (rollup.hatched || pollerStale) {
      header.classList.add("is-stale");
    }
    var badge = header.querySelector(".count-badge");
    if (badge) {
      badge.textContent = rollup.nonOkCount + " / " + rollup.total;
    }
    header.setAttribute(
      "aria-label",
      header.dataset.groupName + ": " + rollup.nonOkCount + " of " + rollup.total + " non-OK",
    );
  }

  // Toggles collapse state in module state (see collapsedGroupKeys above),
  // then rebuilds the tree so groupElement() picks up the new state --
  // the same "mutate module state, then renderTree()" pattern the grouping
  // toggle already uses in init() below.
  function toggleGroupCollapsed(key) {
    if (collapsedGroupKeys.has(key)) {
      collapsedGroupKeys.delete(key);
    } else {
      collapsedGroupKeys.add(key);
    }
    renderTree();
  }

  // Purely decorative: the group header itself (role="button", aria-expanded)
  // is what assistive tech announces, so this icon carries no independent
  // text alternative. Its direction is flipped in CSS via .is-collapsed.
  function groupToggleIcon() {
    var el = document.createElement("span");
    el.className = "icon icon-caret-down-small tree-group-toggle-icon";
    el.setAttribute("aria-hidden", "true");
    return el;
  }

  // A <div> (unlike a native <button>) never synthesizes a click from
  // Enter/Space -- same reasoning as shell.js's handleKeydown for
  // .tree-host-row, kept local to this module since it toggles a group
  // rather than navigating. The header is never inside a [data-host] row
  // (groups and rows are siblings under .tree-group), so this can never
  // fire host navigation, and shell.js's own [data-host] keydown handler
  // can never fire from here either.
  function handleGroupHeaderKeydown(event) {
    if (event.key !== "Enter" && event.key !== " " && event.key !== "Spacebar") {
      return;
    }
    event.preventDefault();
    toggleGroupCollapsed(event.currentTarget.dataset.groupName);
  }

  function groupElement(key, idsSet, mode) {
    var ids = Array.from(idsSet).sort(function (a, b) {
      return displayName(store.devices.get(a)).localeCompare(displayName(store.devices.get(b)));
    });
    var rollup = rollUpGroup(ids, store.devices);
    var collapsed = collapsedGroupKeys.has(key);

    var groupEl = document.createElement("div");
    groupEl.className = "tree-group" + (collapsed ? " is-collapsed" : "");
    groupEl.dataset.groupKey = key;

    var header = document.createElement("div");
    header.className = "tree-group-header";
    header.dataset.groupName = key;
    header.tabIndex = 0;
    header.setAttribute("role", "button");
    header.setAttribute("aria-expanded", collapsed ? "false" : "true");
    header.addEventListener("click", function () {
      toggleGroupCollapsed(key);
    });
    header.addEventListener("keydown", handleGroupHeaderKeydown);
    header.appendChild(groupToggleIcon());

    var nameEl = document.createElement("span");
    nameEl.className = "tree-group-name";
    nameEl.textContent = key;
    header.appendChild(nameEl);

    var badge = document.createElement("span");
    badge.className = "count-badge";
    header.appendChild(badge);

    // updateGroupHeader() below only touches the state/stale classes, the
    // badge text and the aria-label -- it never touches aria-expanded or
    // .is-collapsed, so renderTreeDevice()'s patch-in-place call to it
    // (a single device changing state) can never re-expand a collapsed
    // group or collapse an expanded one.
    updateGroupHeader(header, rollup);
    groupEl.appendChild(header);

    var list = document.createElement("div");
    list.className = "tree-group-list";
    ids.forEach(function (id) {
      list.appendChild(hostRowElement(id, mode));
    });
    groupEl.appendChild(list);

    return groupEl;
  }

  function renderTree() {
    var container = document.getElementById("sidebar-tree");
    if (!container) {
      return;
    }
    var header = container.querySelector(".sidebar-tree-header");
    var mode = groupingMode();
    var index = buildGroupIndex(store.devices, mode);
    var keys = sortedGroupKeys(index);

    var body = document.createElement("div");
    body.className = "sidebar-tree-body";
    if (keys.length === 0) {
      body.appendChild(emptyState(NO_DEVICES_TEXT));
    } else {
      keys.forEach(function (key) {
        body.appendChild(groupElement(key, index.get(key), mode));
      });
    }

    container.replaceChildren();
    if (header) {
      container.appendChild(header);
    }
    container.appendChild(body);
  }

  // A per-device status change patches only that host's row plus its
  // group's badge/color -- never a full tree rebuild (DASH-01/DASH-02
  // "merge in place").
  function renderTreeDevice(hostname) {
    var container = document.getElementById("sidebar-tree");
    if (!container) {
      return;
    }
    var payload = store.devices.get(hostname);
    if (!payload) {
      // Tombstoned -- group membership changed, a full rebuild is required.
      renderTree();
      return;
    }

    var existingRow = container.querySelector('[data-host="' + CSS.escape(hostname) + '"]');
    if (!existingRow) {
      // Not present yet (e.g. topology has not caught up) -- full rebuild.
      renderTree();
      return;
    }

    var mode = groupingMode();
    var freshRow = hostRowElement(hostname, mode);
    existingRow.replaceWith(freshRow);

    var groupEl = freshRow.closest(".tree-group");
    if (!groupEl) {
      return;
    }
    var key = groupEl.dataset.groupKey;
    var index = buildGroupIndex(store.devices, mode);
    var ids = index.get(key);
    if (ids) {
      var rollup = rollUpGroup(ids, store.devices);
      updateGroupHeader(groupEl.querySelector(".tree-group-header"), rollup);
    }
  }

  // ---------------------------------------------------------------------
  // Event panel (always mounted -- D-22/D-23)
  // ---------------------------------------------------------------------

  function eventRowElement(entry) {
    var row = document.createElement("div");
    row.className = "event-row";

    var time = document.createElement("span");
    time.className = "event-time";
    time.style.fontFamily = "var(--font-mono)";
    time.textContent = formatClock(entry && entry.timestamp);
    row.appendChild(time);

    var name = document.createElement("span");
    name.className = "event-device-name";
    var deviceId = entry && entry.device_id;
    var device = store.devices.get(deviceId);
    name.textContent = device ? displayName(device) : deviceId || "";
    row.appendChild(name);

    var transition = document.createElement("span");
    transition.className = "event-transition";
    transition.appendChild(stateChip(entry && entry.from));
    var arrow = document.createElement("span");
    arrow.className = "event-arrow";
    arrow.textContent = "→";
    transition.appendChild(arrow);
    transition.appendChild(stateChip(entry && entry.to));
    row.appendChild(transition);

    return row;
  }

  function renderEvents() {
    var container = document.getElementById("sidebar-events");
    if (!container) {
      return;
    }
    var events = store.events || [];
    if (events.length === 0) {
      container.replaceChildren(emptyState(NO_EVENTS_TEXT));
      return;
    }
    // Newest-first: the poller appends chronologically (mqtt_poller.py's
    // events_this_cycle is concatenated onto the bounded array in order).
    var rows = events
      .slice()
      .reverse()
      .map(eventRowElement);
    container.replaceChildren.apply(container, rows);
  }

  // ---------------------------------------------------------------------
  // Clock -- the single periodic re-render for time-derived rendering
  // ---------------------------------------------------------------------

  function onTick(fn) {
    tickListeners.push(fn);
  }

  // renderBanners() always recomputes the banner's age text and the stale flag when called
  // (see renderPollerBanner above); it only rebuilds the tree itself when pollerStale flips.
  // A device's OWN staleness (D-12's timestamp-age fallback) can cross the threshold purely
  // from elapsed time while the poller stays healthy, so the tree needs an unconditional
  // rebuild here too, not just the conditional one renderPollerBanner already does on change.
  function tick() {
    renderBanners();
    renderTree();
    tickListeners.forEach(function (fn) {
      fn();
    });
  }

  // Started once, from init(), never per view-mount -- the shell (and this clock) persists
  // across the pushState navigation between pages (D-21/D-23), so there is exactly one timer
  // for the lifetime of the page and nothing for mountView()/unmountView() to leak on
  // navigation. The clockTimer guard makes a second call a no-op even if init() ever ran
  // twice.
  function startClock() {
    if (clockTimer) {
      return;
    }
    clockTimer = setInterval(tick, CLOCK_TICK_MS);
  }

  // ---------------------------------------------------------------------
  // Init -- wires the controls this module owns
  // ---------------------------------------------------------------------

  function init() {
    var groupingToggle = document.getElementById("grouping-toggle");
    if (groupingToggle) {
      groupingToggle.setAttribute("aria-pressed", groupingMode() === "folder" ? "true" : "false");
      groupingToggle.addEventListener("click", function () {
        var next = groupingMode() === "device_type" ? "folder" : "device_type";
        // In-memory first, so the regroup below happens whether or not the
        // write lands. The preference is a convenience; losing it across a
        // reload is acceptable, losing the interaction is not.
        groupingModeOverride = next;
        try {
          localStorage.setItem(GROUPING_MODE_KEY, next);
        } catch (err) {
          /* preference not persisted -- the toggle still applies this session */
        }
        groupingToggle.setAttribute("aria-pressed", next === "folder" ? "true" : "false");
        renderTree();
      });
    }

    var sidebarToggle = document.getElementById("sidebar-toggle");
    var sidebarEl = document.querySelector(".sidebar");
    if (sidebarToggle && sidebarEl) {
      sidebarToggle.addEventListener("click", function () {
        sidebarEl.classList.toggle("is-open");
      });
    }

    // Dismissal is deliberately in-memory only, for the lifetime of the
    // page -- a reload must re-surface a still-broken site config (D-16).
    var dismissButton = document.querySelector("#tag-group-banner .dismiss-button");
    if (dismissButton) {
      dismissButton.addEventListener("click", function () {
        tagGroupBannerDismissed = true;
        renderTagGroupBanner();
      });
    }

    renderConnection({ phase: "connecting" });
    renderBanners();
    renderTree();
    renderEvents();
    // Must not start before the rest of init() above has run at least once -- tick() calls
    // renderBanners()/renderTree(), which assume the DOM they touch already reflects an
    // initial render, not a still-uninitialised page.
    startClock();
  }

  return {
    init: init,
    renderConnection: renderConnection,
    renderBanners: renderBanners,
    renderTree: renderTree,
    renderTreeDevice: renderTreeDevice,
    renderEvents: renderEvents,
    groupingMode: groupingMode,
    tick: tick,
    onTick: onTick,
    get pollerStale() {
      return pollerStale;
    },
  };
})();
