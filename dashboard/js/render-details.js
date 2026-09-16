// Per-device drill-down (DASH-03): header identifying the host and its current state, the
// in_downtime/acknowledged flags, and the deep link out to Checkmk's own per-host page. This is
// where the dashboard deliberately stops -- per-service detail lives in Checkmk's own UI, and
// this page links out to it rather than duplicating it (D-19/D-20/D-23).
//
// Registers itself as ViewModules.details; mount(mainEl, params)/update(changeKind, arg)/
// unmount() only, the same contract render-index.js/render-devices.js implement
// (11-06-SUMMARY.md). Reacts to `store` changes exclusively -- no mqtt.js listeners, no
// re-parsing of payloads.
//
// Calls displayName()/effectiveState()/stateClass()/stateIcon()/deviceTypeIcon()/
// formatRelativeTime() (display.js), isDeviceStale() (staleness.js), and
// renderShell.pollerStale (render-shell.js) as globals -- this module does not redefine them.
//
// Hard rendering rule (same as render-shell.js): build DOM with document.createElement and set
// text with textContent -- never assign raw markup built from an interpolated string. Every
// value here (alias, device_type) originates from Checkmk where an operator may type anything.

var ViewModules = ViewModules || {};

ViewModules.details = (function () {
  var CTA_TEXT = "View in Checkmk →";
  var UNCONFIGURED_MARKER = "<HOST_IP>";
  // Locked copy (UI-SPEC Copywriting Contract) -- reproduced verbatim, the same way
  // render-shell.js reproduces its own locked banner/empty-state strings, so this view
  // renders correct copy even if a page's static markup default ever drifts from it.
  var EMPTY_HEADING = "Waiting for device data…";
  var EMPTY_BODY =
    "No devices have reported yet. Once the poller publishes topology, hosts will appear here automatically.";
  var STATE_CLASSES = [
    "state-ok",
    "state-warn",
    "state-crit",
    "state-down",
    "state-unknown",
    "state-unreach",
    "state-pend",
  ];

  var mountedMainEl = null;
  var mountedHostname = null;

  function iconElement(className, label) {
    var el = document.createElement("span");
    el.classList.add("icon", className);
    el.setAttribute("role", "img");
    el.setAttribute("title", label);
    el.setAttribute("aria-label", label);
    return el;
  }

  // Formats a duration (not a point in time) using the same bucketing as
  // formatRelativeTime() (display.js), since the staleness-window threshold has no "ago"
  // reference point of its own.
  function formatDuration(seconds) {
    var wholeSeconds = Math.max(0, Math.round(seconds));
    if (wholeSeconds < 60) {
      return wholeSeconds + "s";
    }
    var minutes = Math.round(wholeSeconds / 60);
    if (minutes < 60) {
      return minutes + "m";
    }
    var hours = Math.round(minutes / 60);
    return hours + "h";
  }

  function staleTooltip(payload) {
    var age = formatRelativeTime(payload && payload.timestamp).replace(/ ago$/, "");
    var thresholdSeconds = STALENESS_FACTOR * POLL_INTERVAL_SECONDS;
    return (
      "Last update " + age + " ago — exceeds the " +
      formatDuration(thresholdSeconds) + " staleness window."
    );
  }

  // Same {base}/{site}/check_mk/... path-join shape as cmk_rest_base_url()
  // (scripts/mqtt_poller.py) -- collapse a double slash rather than assume the configured
  // base already has, or lacks, a trailing one.
  function buildCheckmkUrl(hostname) {
    var trimmedBase = CHECKMK_BASE_URL.replace(/\/+$/, "");
    return (
      trimmedBase + "/" + CHECKMK_SITE +
      "/check_mk/view.py?view_name=hoststatus&host=" + encodeURIComponent(hostname)
    );
  }

  function showPanel(mainEl) {
    var panel = mainEl.querySelector("#detail-panel");
    var empty = mainEl.querySelector(".empty-state");
    if (panel) {
      panel.hidden = false;
    }
    if (empty) {
      empty.hidden = true;
    }
  }

  function showEmptyState(mainEl) {
    var panel = mainEl.querySelector("#detail-panel");
    var empty = mainEl.querySelector(".empty-state");
    if (panel) {
      panel.hidden = true;
    }
    if (empty) {
      var heading = empty.querySelector("h2");
      var body = empty.querySelector("p");
      if (heading) {
        heading.textContent = EMPTY_HEADING;
      }
      if (body) {
        body.textContent = EMPTY_BODY;
      }
      empty.hidden = false;
    }
  }

  function flagBadge(iconClass, label) {
    var badge = document.createElement("span");
    badge.className = "state-badge detail-flag-badge";
    badge.style.backgroundColor = "var(--color-surface-raised)";
    badge.appendChild(iconElement(iconClass, label));
    var text = document.createElement("span");
    text.textContent = label;
    badge.appendChild(text);
    return badge;
  }

  function renderFlags(panel, payload) {
    var container = panel.querySelector(".detail-panel-flags");
    if (!container) {
      container = document.createElement("div");
      container.className = "detail-panel-flags";
      var header = panel.querySelector(".detail-panel-header");
      if (header) {
        header.appendChild(container);
      } else {
        panel.insertBefore(container, panel.firstChild);
      }
    }
    container.replaceChildren();
    if (payload.in_downtime) {
      container.appendChild(flagBadge("icon-pause-filled", "In downtime"));
    }
    if (payload.acknowledged) {
      container.appendChild(flagBadge("icon-check-circle-filled", "Acknowledged"));
    }
  }

  function renderCheckmkLink(mainEl, hostname) {
    var link = mainEl.querySelector("#checkmk-link");
    if (!link) {
      return;
    }
    link.replaceChildren();
    link.appendChild(document.createTextNode(CTA_TEXT + " "));
    link.appendChild(iconElement("icon-pop-out", "Opens in Checkmk"));

    if (CHECKMK_BASE_URL.indexOf(UNCONFIGURED_MARKER) !== -1) {
      // D-20: the browser cannot derive this URL itself. A dead link that silently 404s
      // would be worse than a visibly unconfigured one.
      link.removeAttribute("href");
      link.classList.add("is-disabled");
      link.setAttribute("aria-disabled", "true");
      link.title =
        "dashboard/js/config.js must be edited with this deployment's Checkmk base URL " +
        "before this link can be used.";
      return;
    }
    link.classList.remove("is-disabled");
    link.removeAttribute("aria-disabled");
    link.removeAttribute("title");
    link.href = buildCheckmkUrl(hostname);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }

  function renderHeader(mainEl, hostname, payload) {
    var panel = mainEl.querySelector("#detail-panel");
    if (!panel) {
      return;
    }

    var nameEl = panel.querySelector(".detail-device-name");
    if (nameEl) {
      nameEl.replaceChildren();
      nameEl.appendChild(
        iconElement(deviceTypeIcon(payload.device_type), payload.device_type || "Unknown type"),
      );
      var nameText = document.createElement("span");
      nameText.textContent = displayName(payload);
      nameEl.appendChild(nameText);
    }

    // D-18: the hostname stays visible beside the alias, but only when the alias differs
    // from it -- showing "web-01" next to "web-01" duplicates the same word twice.
    var hostEl = panel.querySelector(".detail-hostname");
    if (hostEl) {
      var alias = typeof payload.alias === "string" ? payload.alias.trim() : "";
      if (alias && alias !== hostname) {
        hostEl.textContent = hostname;
        hostEl.hidden = false;
      } else {
        hostEl.textContent = "";
        hostEl.hidden = true;
      }
    }

    var state = effectiveState(payload);
    var stale = isDeviceStale(payload) || renderShell.pollerStale;

    var badge = panel.querySelector(".detail-state-badge");
    if (badge) {
      STATE_CLASSES.forEach(function (cls) {
        badge.classList.remove(cls);
      });
      badge.classList.add(stateClass(state));
      badge.replaceChildren();
      // D-10 locks DOWN's non-color marker specifically to `.icon-close-circle-filled`
      // (superseding the pre-KONE Unicode DOWN-marker glyph) -- hardcoded here rather than
      // trusted solely to stateIcon()'s lookup table, since this exact class is the locked
      // value, not an incidental default.
      var badgeIconClass = state === "DOWN" ? "icon-close-circle-filled" : stateIcon(state);
      badge.appendChild(iconElement(badgeIconClass, state));
      var label = document.createElement("span");
      // Accessibility contract: the DOWN/"(stale)" text itself must render in the normal
      // text color, never in --state-down/--state-stale -- the state hue lives on this
      // badge's background-color (via the state-* class above) and on the icon, not on the
      // text node. Neither this label nor .state-badge sets a text `color`, so it inherits
      // --color-text as required.
      label.textContent = state + (stale ? " (stale)" : "");
      badge.appendChild(label);
      if (stale) {
        badge.title = staleTooltip(payload);
      } else {
        badge.removeAttribute("title");
      }
    }

    panel.classList.toggle("is-stale", stale);

    renderFlags(panel, payload);
    renderCheckmkLink(mainEl, hostname);
  }

  function mount(mainEl, params) {
    mountedMainEl = mainEl;
    mountedHostname = params && params.id;

    var payload = mountedHostname ? store.devices.get(mountedHostname) : undefined;
    if (!payload) {
      // No retained status yet -- may simply not have arrived on a freshly opened tab, not
      // an error.
      showEmptyState(mainEl);
      return;
    }
    showPanel(mainEl);
    renderHeader(mainEl, mountedHostname, payload);
  }

  function update(changeKind, arg) {
    if (!mountedMainEl || !mountedHostname) {
      return;
    }
    if (changeKind === "device" && arg === mountedHostname) {
      var payload = store.devices.get(mountedHostname);
      if (!payload) {
        // Tombstoned since mount -- fall back to the empty state rather than rendering a
        // panel for a device that no longer exists.
        showEmptyState(mountedMainEl);
        return;
      }
      showPanel(mountedMainEl);
      renderHeader(mountedMainEl, mountedHostname, payload);
    } else if (changeKind === "poller") {
      // The stale hatch also depends on renderShell.pollerStale, which shell.js has already
      // refreshed (via renderShell.renderBanners()) by the time this runs.
      var current = store.devices.get(mountedHostname);
      if (current) {
        renderHeader(mountedMainEl, mountedHostname, current);
      }
    }
  }

  function unmount() {
    mountedMainEl = null;
    mountedHostname = null;
  }

  return {
    id: "details",
    mount: mount,
    update: update,
    unmount: unmount,
  };
})();
