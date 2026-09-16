// Entry point every page loads last. Wires the store, the MQTT connection,
// the persistent shell chrome, and the current page's ViewModule together,
// and owns the pushState router that keeps the event history mounted across
// navigation (D-19/D-21/D-23).
//
// Contains no rendering and no business logic of its own -- the same
// "entry point composes everything" value wizard.py's run() already
// embodies in this repo (11-RESEARCH.md Recommended Project Structure).

// Populated by each render-*.js module as it loads: ViewModules.index,
// ViewModules.devices, ViewModules.details. Script order in
// index.html/devices.html/details.html runs every render-*.js BEFORE this
// file (11-03's script block), so the registry is already populated when
// this line is reached.
//
// Bug fixed 2026-09-16: this read `var ViewModules = {};`, which wiped every
// registration the render modules had just made. Hoisting only creates the
// binding -- the `= {}` initializer still re-executes when the line runs, and
// because this file loads LAST it replaced the populated object moments before
// the DOMContentLoaded handler below called mountView(). Net effect in a real
// browser: ViewModules[view] was undefined on first load of all three pages,
// so no view ever mounted and every page rendered its chrome around an empty
// main area. Static verification could not see it -- each file is individually
// valid and `node --check` passes; only the composition was broken. Found
// independently by plans 11-07 and 11-08, each proving it with a two-script
// vm.runInContext simulation. The guarded form below is what every render-*.js
// module already uses; keep all four in agreement.
var ViewModules = ViewModules || {};

(function () {
  var connectionStarted = false;
  var currentModule = null;

  function viewForPathname(pathname) {
    var filename = pathname.split("/").pop();
    if (filename === "devices.html") {
      return "devices";
    }
    if (filename === "details.html") {
      return "details";
    }
    return "index";
  }

  // Strips the characters is_publishable_device_id() already rejects at
  // publish time (scripts/mqtt_poller.py) before the id is used for a store
  // lookup. A URL is a more attacker-reachable input than a
  // Livestatus-sourced hostname (T-11-17): a crafted value can only ever
  // miss the store, but it must never be handed onward unfiltered.
  function sanitizeHostId(raw) {
    if (typeof raw !== "string") {
      return "";
    }
    return raw.replace(/[+#/]/g, "");
  }

  function paramsForView(view, search) {
    if (view !== "details") {
      return {};
    }
    var query = new URLSearchParams(search);
    return { id: sanitizeHostId(query.get("id") || "") };
  }

  function resolveView(pathname, search) {
    var view = viewForPathname(pathname);
    return { view: view, params: paramsForView(view, search) };
  }

  function mountView(view, params) {
    if (currentModule && currentModule.unmount) {
      currentModule.unmount();
    }
    var module = ViewModules[view];
    if (!module) {
      // A script failed to load -- degrade rather than throw, leaving the
      // page's own static markup in place.
      console.error("shell.js: no ViewModule registered for view:", view);
      currentModule = null;
      return;
    }
    module.mount(document.getElementById("main"), params);
    currentModule = module;
  }

  function urlForHost(hostname) {
    return "details.html?id=" + encodeURIComponent(hostname);
  }

  function resolveSameOriginUrl(href) {
    var url;
    try {
      url = new URL(href, location.href);
    } catch (err) {
      return null;
    }
    return url.origin === location.origin ? url : null;
  }

  function navigateTo(view, params, url) {
    history.pushState({ view: view, params: params }, "", url);
    mountView(view, params);
  }

  function handleClick(event) {
    var hostEl = event.target.closest ? event.target.closest("[data-host]") : null;
    if (hostEl) {
      event.preventDefault();
      var hostname = hostEl.dataset.host;
      navigateTo("details", { id: hostname }, urlForHost(hostname));
      return;
    }

    var anchor = event.target.closest ? event.target.closest("a") : null;
    if (!anchor) {
      return;
    }
    var sameOriginUrl = resolveSameOriginUrl(anchor.href);
    if (!sameOriginUrl) {
      return; // external link (e.g. the "View in Checkmk" CTA) -- let it navigate normally
    }
    event.preventDefault();
    var resolved = resolveView(sameOriginUrl.pathname, sameOriginUrl.search);
    navigateTo(resolved.view, resolved.params, sameOriginUrl.pathname + sameOriginUrl.search);
  }

  function handlePopState() {
    var resolved = resolveView(location.pathname, location.search);
    mountView(resolved.view, resolved.params);
  }

  // Fans one store change out to the shell chrome (which owns the tree,
  // banners and event panel) and to the active view module's own
  // update(changeKind, arg). "history" has no shell-level rendering -- only
  // the details view module consumes it.
  function dispatchStoreChange(changeKind, arg) {
    if (changeKind === "device") {
      renderShell.renderTreeDevice(arg);
      renderShell.renderBanners();
    } else if (changeKind === "topology") {
      renderShell.renderTree();
    } else if (changeKind === "events") {
      renderShell.renderEvents();
    } else if (changeKind === "poller") {
      renderShell.renderBanners();
    }
    if (currentModule && currentModule.update) {
      currentModule.update(changeKind, arg);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    renderShell.init();

    store.subscribe("device", function (id) {
      dispatchStoreChange("device", id);
    });
    store.subscribe("topology", function () {
      dispatchStoreChange("topology");
    });
    store.subscribe("history", function (id) {
      dispatchStoreChange("history", id);
    });
    store.subscribe("events", function () {
      dispatchStoreChange("events");
    });
    store.subscribe("poller", function () {
      dispatchStoreChange("poller");
    });

    connection.onStatus(renderShell.renderConnection);

    document.body.addEventListener("click", handleClick);
    window.addEventListener("popstate", handlePopState);

    var initial = resolveView(location.pathname, location.search);
    mountView(initial.view, initial.params);

    if (!connectionStarted) {
      connectionStarted = true;
      connection.connect();
    }
  });
})();
