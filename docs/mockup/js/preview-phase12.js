// PREVIEW ONLY -- PHASE 12 PLACEHOLDER. Not shipped, not in the repo.
//
// Phase 11 deliberately does NOT render per-service detail: DASH-03 links out
// to Checkmk for that, and the poller issues only `GET hosts`. Phase 12 (Agent
// Metrics and Service Status) adds a `GET services` Livestatus query and a new
// retained per-device services topic. This file fakes that future payload so
// the shape can be judged now, against docs/DMC-server.png.
//
// It follows Phase 12's already-locked decisions rather than inventing:
//   D-01  `Filesystem /` is the HEADLINE disk gauge (fs_used_percent, warn 80 /
//         crit 90 read from perf_data), PLUS a badge carrying the worst
//         fs_used_percent across every OTHER mount -- because Checkmk emits one
//         `Filesystem <mount>` service per mount, so a /-only gauge reads green
//         while /var sits at 98%.
//   D-02  ONLY the individual `Systemd Service <name>` services the operator
//         picked in the wizard's Phase 5 prompt. The `Systemd Service Summary`
//         roll-up is explicitly NOT wanted and is filtered out below.
//         Per-service fields available: state, cpu_time, mem_used,
//         active_since, number_of_tasks.

(function () {
  // Deterministic pseudo-metrics per host, so a given device looks the same
  // every time you open it rather than jittering on each render.
  function seeded(hostname, salt) {
    var h = 0;
    var s = hostname + "|" + salt;
    for (var i = 0; i < s.length; i++) {
      h = (h * 31 + s.charCodeAt(i)) >>> 0;
    }
    return (h % 1000) / 1000;
  }

  function pct(hostname, salt, lo, hi) {
    return Math.round(lo + seeded(hostname, salt) * (hi - lo));
  }

  // Checkmk's own Nagios-style levels: OK < warn <= WARN < crit <= CRIT.
  function levelFor(value, warn, crit) {
    if (value >= crit) return "CRIT";
    if (value >= warn) return "WARN";
    return "OK";
  }

  var SERVICE_POOL = [
    { name: "cron", tasks: 1 },
    { name: "ModemManager", tasks: 3 },
    { name: "open-vm-tools", tasks: 6 },
    { name: "ssh", tasks: 2 },
    { name: "systemd-resolved", tasks: 4 }
  ];

  function servicesFor(hostname, hostState) {
    var count = 2 + Math.floor(seeded(hostname, "svccount") * 3);
    var list = SERVICE_POOL.slice(0, count).map(function (svc, i) {
      var cpu = (seeded(hostname, "cpu" + i) * 240).toFixed(1);
      var mem = Math.round(4 + seeded(hostname, "mem" + i) * 120);
      var days = Math.floor(seeded(hostname, "up" + i) * 40) + 1;
      // The failing service is what explains a red host -- Phase 12 scope
      // item 4: "render a per-host service status list that explains WHY a
      // host is red".
      var state = hostState === "CRIT" && i === 1 ? "CRIT" : "OK";
      return {
        description: "Systemd Service " + svc.name,
        state: state,
        cpu_time: cpu + "s",
        mem_used: mem + " MB",
        active_since: days + "d ago",
        number_of_tasks: svc.tasks
      };
    });
    // D-02: the roll-up is deliberately excluded. Shown here as a filter so the
    // reason is visible in the preview, not silently omitted.
    return list.filter(function (s) {
      return s.description !== "Systemd Service Summary";
    });
  }

  function metricsFor(hostname, hostState) {
    var cpu = hostState === "CRIT" ? 94 : pct(hostname, "cpu", 8, 72);
    var ram = hostState === "CRIT" ? 91 : pct(hostname, "ram", 22, 78);
    var rootDisk = pct(hostname, "disk", 18, 66);
    // D-01: every OTHER mount, so the blind spot is visible.
    var mounts = [
      { mount: "/boot", used: pct(hostname, "boot", 30, 62) },
      { mount: "/var", used: pct(hostname, "var", 40, 97) },
      { mount: "/data", used: pct(hostname, "data", 12, 88) }
    ];
    var worstOther = mounts.reduce(function (a, b) {
      return b.used > a.used ? b : a;
    });
    return {
      cpu: cpu,
      ram: ram,
      rootDisk: rootDisk,
      mounts: mounts,
      worstOther: worstOther,
      smart: seeded(hostname, "smart") > 0.82 ? "Pre-fail attribute raised" : "Healthy",
      smartState: seeded(hostname, "smart") > 0.82 ? "WARN" : "OK"
    };
  }

  // --- rendering -----------------------------------------------------------

  var NS = "http://www.w3.org/2000/svg";

  function gauge(label, value, warn, crit) {
    var level = levelFor(value, warn, crit);
    var wrap = document.createElement("div");
    wrap.className = "p12-gauge";

    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 120 78");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", label + " " + value + " percent, " + level);

    // 180-degree arc, radius 48, centred at (60,62).
    var d = "M 12 62 A 48 48 0 0 1 108 62";
    var track = document.createElementNS(NS, "path");
    track.setAttribute("d", d);
    track.setAttribute("class", "p12-arc-track");
    svg.appendChild(track);

    var len = Math.PI * 48;
    var fill = document.createElementNS(NS, "path");
    fill.setAttribute("d", d);
    fill.setAttribute("class", "p12-arc-fill p12-" + level);
    fill.setAttribute("stroke-dasharray", (len * value) / 100 + " " + len);
    svg.appendChild(fill);

    wrap.appendChild(svg);

    var num = document.createElement("div");
    num.className = "p12-gauge-value";
    num.textContent = value + "%";
    wrap.appendChild(num);

    var cap = document.createElement("div");
    cap.className = "p12-gauge-label";
    cap.textContent = label;
    wrap.appendChild(cap);

    return wrap;
  }

  function chip(text, level) {
    var el = document.createElement("span");
    el.className = "p12-chip p12-" + level;
    el.textContent = text;
    return el;
  }

  function section(title, note) {
    var s = document.createElement("section");
    s.className = "p12-section";
    var h = document.createElement("div");
    h.className = "p12-section-head";
    var t = document.createElement("h3");
    t.textContent = title;
    h.appendChild(t);
    if (note) {
      var n = document.createElement("span");
      n.className = "p12-section-note";
      n.textContent = note;
      h.appendChild(n);
    }
    s.appendChild(h);
    return s;
  }

  function build(hostname) {
    var payload = store.devices.get(hostname);
    var hostState = payload ? payload.state : "UNKNOWN";
    var m = metricsFor(hostname, hostState);

    var root = document.createElement("div");
    root.className = "p12-root";

    var banner = document.createElement("div");
    banner.className = "p12-banner";
    banner.textContent =
      "Phase 12 placeholder — agent metrics and per-service status. Synthetic data, not yet implemented.";
    root.appendChild(banner);

    // Gauges
    var gaugeSec = section("Agent metrics");
    var row = document.createElement("div");
    row.className = "p12-gauge-row";
    row.appendChild(gauge("CPU", m.cpu, 80, 90));
    row.appendChild(gauge("RAM", m.ram, 80, 90));
    row.appendChild(gauge("Filesystem /", m.rootDisk, 80, 90));
    gaugeSec.appendChild(row);

    // D-01's badge: the whole point is that / can read green while another
    // mount is nearly full.
    var other = document.createElement("div");
    other.className = "p12-other-mounts";
    other.appendChild(document.createTextNode("Worst other mount: "));
    other.appendChild(
      chip(
        m.worstOther.mount + " " + m.worstOther.used + "%",
        levelFor(m.worstOther.used, 80, 90)
      )
    );
    var allMounts = document.createElement("span");
    allMounts.className = "p12-mount-list";
    allMounts.textContent =
      m.mounts
        .map(function (x) {
          return x.mount + " " + x.used + "%";
        })
        .join("   ");
    other.appendChild(allMounts);
    gaugeSec.appendChild(other);

    var smart = document.createElement("div");
    smart.className = "p12-smart";
    smart.appendChild(document.createTextNode("Disk health (SMART): "));
    smart.appendChild(chip(m.smart, m.smartState));
    gaugeSec.appendChild(smart);
    root.appendChild(gaugeSec);

    // Services
    var svcs = servicesFor(hostname, hostState);
    var svcSec = section(
      "Services",
      svcs.length + " monitored — the roll-up summary is excluded (D-02)"
    );
    var table = document.createElement("table");
    table.className = "p12-table";
    var thead = document.createElement("thead");
    var htr = document.createElement("tr");
    ["State", "Service", "CPU time", "Memory", "Tasks", "Active since"].forEach(function (h) {
      var th = document.createElement("th");
      th.textContent = h;
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);

    var tbody = document.createElement("tbody");
    svcs.forEach(function (s) {
      var tr = document.createElement("tr");
      var tdState = document.createElement("td");
      tdState.appendChild(chip(s.state, s.state));
      tr.appendChild(tdState);
      [
        s.description.replace(/^Systemd Service /, ""),
        s.cpu_time,
        s.mem_used,
        String(s.number_of_tasks),
        s.active_since
      ].forEach(function (v) {
        var td = document.createElement("td");
        td.textContent = v;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    svcSec.appendChild(table);
    root.appendChild(svcSec);

    return root;
  }

  function currentHost() {
    try {
      return new URLSearchParams(location.search).get("id") || "";
    } catch (err) {
      return "";
    }
  }

  // The real render-details.js owns #detail-panel and rebuilds it on mount and
  // on store updates. Rather than patch that code, watch #main and re-append
  // the placeholder whenever the panel is (re)built.
  function sync() {
    var panel = document.getElementById("detail-panel");
    if (!panel) return;
    var host = currentHost();
    if (!host) return;
    var existing = panel.querySelector(".p12-root");
    if (existing && existing.dataset.host === host) return;
    if (existing) existing.remove();
    var block = build(host);
    block.dataset.host = host;
    panel.appendChild(block);
  }

  window.addEventListener("DOMContentLoaded", function () {
    var main = document.getElementById("main");
    if (!main) return;
    new MutationObserver(function () {
      sync();
    }).observe(main, { childList: true, subtree: true });
    sync();
  });
})();
