// PREVIEW ONLY -- not part of the shipped dashboard.
//
// The real dashboard is three separate HTML pages that share one shell; an
// artifact is a single page. Each view module queries static markup that
// only its own page ships (#overview-grid, #device-table, #detail-panel),
// so before a view mounts, #main must hold that page's markup.
//
// This file changes NO dashboard code. It listens in the CAPTURE phase, so
// it runs before shell.js's own bubble-phase listener on document.body,
// swaps #main's contents, and then lets the real router do the navigation.

(function () {
  var MAIN_MARKUP = {
    // Proposed 11.1/13: Overview IS the topology map. The stats strip and
    // grouped overview that D-24 puts here are replaced by it in this mockup.
    index: '<div id="network-map"></div>',
    devices:
      '<table id="device-table"><thead><tr>' +
      '<th data-key="state">State</th><th data-key="host">Host</th><th data-key="type">Type</th>' +
      '<th data-key="location">Location</th><th data-key="lastUpdate">Last Update</th><th>Flags</th>' +
      "</tr></thead><tbody></tbody></table>" +
      '<div class="empty-state"><h2>Waiting for device data&hellip;</h2>' +
      '<p>No devices have reported yet. Once the poller publishes topology, hosts will appear here automatically.</p></div>',
    details:
      '<div id="detail-panel">' +
      '<div class="detail-panel-header">' +
      '<span class="detail-device-name"></span><span class="detail-hostname"></span>' +
      '<span class="detail-state-badge state-badge"></span>' +
      "</div>" +
      '<div id="history-strip"></div>' +
      '<a id="checkmk-link" href="#">View in Checkmk &rarr; <span class="icon icon-pop-out"></span></a>' +
      "</div>" +
      '<div class="empty-state"><h2>Waiting for device data&hellip;</h2>' +
      '<p>No devices have reported yet. Once the poller publishes topology, hosts will appear here automatically.</p></div>'
  };

  function viewForHref(href) {
    var file = String(href).split("?")[0].split("/").pop();
    if (file === "devices.html") return "devices";
    if (file === "details.html") return "details";
    return "index";
  }

  function swapMain(view) {
    var main = document.getElementById("main");
    if (main) {
      main.innerHTML = MAIN_MARKUP[view] || MAIN_MARKUP.index;
    }
    document.querySelectorAll("#preview-views button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.view === view));
    });
  }

  // Capture phase: runs before shell.js's listener, so the markup the view
  // module is about to query is already in place.
  document.addEventListener(
    "click",
    function (event) {
      if (!event.target.closest) return;
      if (event.target.closest("#preview-bar")) return;
      if (event.target.closest("[data-host]")) {
        swapMain("details");
        return;
      }
      var anchor = event.target.closest("a");
      if (anchor && anchor.getAttribute("href") && anchor.id !== "checkmk-link") {
        swapMain(viewForHref(anchor.getAttribute("href")));
      }
    },
    true
  );

  // shell.js navigates with history.pushState, which deliberately does NOT
  // fire popstate -- that event is for BACK/FORWARD only. Anything in this
  // harness that needs to react to in-app navigation (the centre's event
  // filter) would therefore never re-render on a host click. Wrap pushState
  // once and emit our own event. Preview-only: the shipped dashboard has no
  // such need, because shell.js calls mountView() directly after pushState.
  (function () {
    var nativePushState = history.pushState;
    history.pushState = function () {
      var result = nativePushState.apply(history, arguments);
      window.dispatchEvent(new Event("preview:navigated"));
      return result;
    };
  })();

  window.addEventListener("DOMContentLoaded", function () {
    var poller = document.getElementById("preview-poller");
    if (poller) {
      poller.addEventListener("click", function () {
        var offline = poller.getAttribute("aria-pressed") !== "true";
        poller.setAttribute("aria-pressed", String(offline));
        poller.textContent = offline ? "Poller: offline" : "Poller: online";
        PREVIEW.setPoller(!offline);
      });
    }

    var tag = document.getElementById("preview-tag");
    if (tag) {
      tag.addEventListener("click", function () {
        var missing = tag.getAttribute("aria-pressed") !== "true";
        tag.setAttribute("aria-pressed", String(missing));
        tag.textContent = missing ? "Tag group: missing" : "Tag group: present";
        PREVIEW.setTagGroupMissing(missing);
      });
    }
  });
})();
