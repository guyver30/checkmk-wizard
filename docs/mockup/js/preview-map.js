// PREVIEW ONLY -- mockup of the Phase 13 topology map (DASH-07).
//
// Phase 13 owns this for real. Two of its decisions are already argued in
// 11-DISCUSSION-LOG.md and are honoured here rather than re-derived:
//   D-08  parentless hosts attach to a synthetic, distinctly-styled group-root
//         node, so the graph is never a scatter of disconnected dots.
//   D-09  physics stabilises once on load and then FREEZES, so later
//         DataSet.update() calls recolor nodes in place without disturbing the
//         operator's pan/zoom mid-incident.
//
// It replaces ViewModules.index for the mockup, so "Overview" shows the map
// instead of the stats strip + grouped overview. That contradicts D-24 and is
// exactly the kind of change Phase 11.1 has to decide properly.
//
// Node colour comes from the REAL state palette by reading the CSS custom
// properties off :root, so the map can never drift from the stylesheet.

(function () {
  var network = null;
  var nodes = null;
  var edges = null;
  var SYNTHETIC_ROOT = "__site__";

  function cssVar(name, fallback) {
    try {
      var v = getComputedStyle(document.documentElement).getPropertyValue(name);
      return (v && v.trim()) || fallback;
    } catch (err) {
      return fallback;
    }
  }

  // --state-* is the SATURATED value in both palettes -- the one meant for
  // marks (dots, arcs, graph nodes). The light palette puts its pale
  // behind-text tint in --state-*-fill instead, so this needs no theme
  // awareness at all.
  function paletteFor(state) {
    var map = {
      OK: "--state-ok",
      WARN: "--state-warn",
      CRIT: "--state-crit",
      DOWN: "--state-down",
      UNKNOWN: "--state-unknown",
      UNREACH: "--state-unreach",
      PEND: "--state-pend"
    };
    return cssVar(map[state] || "--state-unknown", "#999999");
  }

  function nodeFor(id) {
    var payload = store.devices.get(id);
    var state = effectiveState(payload);
    var stale = isDeviceStale(payload) || renderShell.pollerStale;
    var color = paletteFor(state);
    return {
      id: id,
      label: payload ? displayName(payload) : id,
      title: id + " — " + state + (stale ? " (stale)" : ""),
      shape: "dot",
      size: 14,
      color: {
        background: color,
        border: stale ? cssVar("--state-stale", "#727272") : color,
        highlight: { background: color, border: cssVar("--color-accent", "#1450f5") }
      },
      borderWidth: stale ? 4 : 1,
      font: { color: cssVar("--color-text", "#ffffff"), size: 12 }
    };
  }

  function build() {
    var topology = store.topology;
    if (!topology || !Array.isArray(topology.devices)) {
      return { nodeList: [], edgeList: [] };
    }

    var nodeList = [];
    var edgeList = [];
    var known = {};
    topology.devices.forEach(function (d) {
      known[d.id] = true;
    });

    var needsRoot = false;
    topology.devices.forEach(function (d) {
      nodeList.push(nodeFor(d.id));
      var parents = Array.isArray(d.parents) ? d.parents : [];
      var real = parents.filter(function (p) {
        return known[p];
      });
      if (real.length === 0) {
        // D-08: never leave a host floating.
        needsRoot = true;
        edgeList.push({ from: SYNTHETIC_ROOT, to: d.id, dashes: true, width: 1 });
      } else {
        real.forEach(function (p) {
          // A link between two NetworkDevices is backbone; draw it heavier so
          // the spine reads at a glance and leaf links recede, the way a
          // typical NMS map distinguishes uplinks from access ports.
          var parentPayload = store.devices.get(p);
          var childPayload = store.devices.get(d.id);
          var backbone =
            parentPayload && childPayload &&
            parentPayload.device_type === "NetworkDevice" &&
            childPayload.device_type === "NetworkDevice";
          edgeList.push({
            from: p,
            to: d.id,
            width: backbone ? 4 : 2,
            color: backbone ? { color: cssVar("--color-text", "#ffffff") } : undefined
          });
        });
      }
    });

    if (needsRoot) {
      nodeList.push({
        id: SYNTHETIC_ROOT,
        label: "Site",
        shape: "diamond",
        size: 18,
        color: {
          background: cssVar("--color-surface-raised", "#142c6e"),
          border: cssVar("--color-accent", "#1450f5")
        },
        font: { color: cssVar("--color-text-muted", "#a1b9fb"), size: 12 }
      });
    }

    return { nodeList: nodeList, edgeList: edgeList };
  }

  function mount(mainEl) {
    var container = document.getElementById("network-map");
    if (!container) {
      container = document.createElement("div");
      container.id = "network-map";
      mainEl.appendChild(container);
    }

    var built = build();
    nodes = new vis.DataSet(built.nodeList);
    edges = new vis.DataSet(built.edgeList);

    network = new vis.Network(
      container,
      { nodes: nodes, edges: edges },
      {
        interaction: { hover: true, zoomView: true, dragView: true },
        edges: {
          // NOT --color-border: that token is rgba(20,56,155,0.35), a 35%-alpha
          // hairline meant for panel edges against a solid surface. As graph
          // links over the map's background it is effectively invisible.
          // --color-text-muted is the readable structural colour here, and the
          // backbone link between the three network devices is drawn heavier
          // so the spine reads before the leaves.
          color: {
            color: cssVar("--color-text-muted", "#a1b9fb"),
            highlight: cssVar("--color-accent", "#1450f5"),
            hover: cssVar("--color-text", "#ffffff")
          },
          width: 2,
          selectionWidth: 3,
          smooth: { type: "continuous" }
        },
        physics: {
          // D-09: settle once, then stop. Frozen physics is what lets a later
          // recolor happen without the graph re-arranging under the operator.
          solver: "forceAtlas2Based",
          stabilization: { iterations: 250, fit: true }
        },
        layout: { improvedLayout: true }
      }
    );

    network.once("stabilizationIterationsDone", function () {
      network.setOptions({ physics: false });
    });

    // Clicking a node opens that device, through the real router.
    network.on("click", function (params) {
      if (!params.nodes || !params.nodes.length) return;
      var id = params.nodes[0];
      if (id === SYNTHETIC_ROOT) return;
      history.pushState({ view: "details", params: { id: id } }, "", "details.html?id=" + encodeURIComponent(id));
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
  }

  // D-09's payoff: recolor in place, never rebuild, so pan/zoom survives.
  function update() {
    if (!nodes || !store.topology) return;
    var updates = [];
    store.topology.devices.forEach(function (d) {
      updates.push(nodeFor(d.id));
    });
    nodes.update(updates);
  }

  function unmount() {
    if (network) {
      network.destroy();
      network = null;
    }
    nodes = null;
    edges = null;
  }

  // render-index.js registers ViewModules.index inside its own
  // DOMContentLoaded handler (plan 11-07's workaround for the old shell.js
  // defect). This file loads after it, so this listener runs after that one
  // and the override sticks.
  window.addEventListener("DOMContentLoaded", function () {
    ViewModules.index = { mount: mount, update: update, unmount: unmount };
    store.subscribe("device", update);
    store.subscribe("poller", update);
  });
})();
