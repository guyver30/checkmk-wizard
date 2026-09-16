// PREVIEW ONLY -- proposed Phase 11.1 event panel, relocated to the centre.
//
// Operator requirement: the event history is ALWAYS visible in the centre,
// directly beneath the detail region. With no device selected it shows every
// device's events; with a device selected it shows only that device's.
//
// Today (D-22) events live in the left column beneath the tree and are never
// filtered. This file mocks the proposed behaviour without touching
// render-shell.js, so the layout can be judged before D-22 is revised.
//
// It deliberately reuses the SHIPPED row classes (.event-row, .event-time,
// .event-device-name, .event-arrow, .event-transition, .event-state-chip) so
// it inherits the real stylesheet rather than inventing a parallel look.

(function () {
  function currentHost() {
    try {
      return new URLSearchParams(location.search).get("id") || "";
    } catch (err) {
      return "";
    }
  }

  function chipFor(state) {
    var span = document.createElement("span");
    span.className = "event-state-chip";
    if (state) {
      span.classList.add(stateClass(state));
    }
    var label = document.createElement("span");
    label.className = "state-label";
    label.textContent = state || "—";
    span.appendChild(label);
    return span;
  }

  function eventRow(entry) {
    var row = document.createElement("div");
    row.className = "event-row";

    var icon = document.createElement("span");
    icon.className = "icon " + stateIcon(entry.to || entry.from || "UNKNOWN");
    icon.setAttribute("role", "img");
    icon.setAttribute("aria-label", entry.event || "event");
    icon.setAttribute("title", entry.event || "event");
    row.appendChild(icon);

    var time = document.createElement("span");
    time.className = "event-time";
    time.textContent = formatClock(entry.timestamp);
    row.appendChild(time);

    var name = document.createElement("span");
    name.className = "event-device-name";
    var payload = store.devices.get(entry.device_id);
    name.textContent = payload ? displayName(payload) : entry.device_id;
    // Clicking an event row opens that device -- shell.js's router already
    // intercepts any [data-host] click, so this needs no handler of its own.
    name.dataset.host = entry.device_id;
    row.appendChild(name);

    var transition = document.createElement("span");
    transition.className = "event-transition";
    transition.appendChild(chipFor(entry.from));
    var arrow = document.createElement("span");
    arrow.className = "event-arrow";
    arrow.textContent = "→";
    transition.appendChild(arrow);
    transition.appendChild(chipFor(entry.to));
    row.appendChild(transition);

    return row;
  }

  function render() {
    var body = document.getElementById("events-region-body");
    var scope = document.getElementById("events-region-scope");
    var clear = document.getElementById("events-region-clear");
    if (!body) return;

    var host = currentHost();
    var all = store.events || [];
    var shown = host
      ? all.filter(function (e) {
          return e.device_id === host;
        })
      : all;

    if (scope) {
      if (host) {
        var payload = store.devices.get(host);
        scope.textContent =
          "Filtered to " + (payload ? displayName(payload) : host) +
          " — " + shown.length + " of " + all.length + " events";
      } else {
        scope.textContent = "All devices — " + all.length + " events";
      }
    }
    if (clear) {
      clear.hidden = !host;
    }

    if (!shown.length) {
      var empty = document.createElement("div");
      empty.className = "empty-state";
      var p = document.createElement("p");
      p.textContent = host
        ? "No events recorded for this device yet."
        : "No events yet — state changes will appear here as they happen.";
      empty.appendChild(p);
      body.replaceChildren(empty);
      return;
    }

    // Newest first, matching the shipped event-panel contract.
    var frag = document.createDocumentFragment();
    shown
      .slice()
      .reverse()
      .forEach(function (entry) {
        frag.appendChild(eventRow(entry));
      });
    body.replaceChildren(frag);
  }

  window.PREVIEW_EVENTS = { render: render };

  window.addEventListener("DOMContentLoaded", function () {
    var clear = document.getElementById("events-region-clear");
    if (clear) {
      clear.addEventListener("click", function () {
        // Back to the unfiltered fleet view.
        history.pushState({}, "", "index.html");
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
    }
    store.subscribe("device", render);
    store.subscribe("events", render);
    store.subscribe("topology", render);
    // popstate covers back/forward; preview:navigated (emitted by the
    // pushState wrapper in preview-chrome.js) covers in-app host clicks,
    // which is how a device actually gets selected.
    window.addEventListener("popstate", render);
    window.addEventListener("preview:navigated", render);
    render();
  });
})();
