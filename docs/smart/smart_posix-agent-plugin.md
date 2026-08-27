> From: https://www.google.com/search?smstk=Chh1U0hxcklaUWk2bjV1am5rQVlDa0lFND0QARgA&smstidx=1&q=smart_posix+agent+plugin&udm=50&csuir=1&aep=34&kgs=de4a20655c1eac23&shem=agpl%2Caiolsbe%2Casdpe%2Cepsd1%2Crimspwouoe&shndl=37&shmd=H4sIAAAAAAAA_3WOSwrCMBRF6USkE8GROCoOBRPrbyDuJbw24eVBfiQp7bDLcg3uwb1YQUfi9HLPubd8FuXswE7heF7fdM4hXTnv-55hypCpZa23PCmIrd6F6K3nQFYkDVGJrDvbOCDDgsPN8kuj92gUA-LbVbIQswg-0VABKperYDokN4yLsbjPH4X4t0l26ifeRHCSHH6sKDCCpEnE6-EnExPvJEQp6stehvetFxjsYevgAAAA&shmds=v1_ARwrE22ZyuK7yU-E7INtkPWai51jbqjubsQS08jdWBf5PnLKnQ&source=sh%2Fx%2Faim%2Fm1%2F1&atvm=2&mtid=ErOPapn6NomG4-EP-N-AYQ

# you asked

message time: 11:45 am

smart_posix agent plugin

---

# googlesearch response

The `smart_posix` agent plugin is a POSIX-compatible replacement for the legacy `smart` monitoring plug-in in Checkmk. It tracks hard disk health, temperatures, and error counters using S.M.A.R.T. data over ATA and NVMe protocols.

Overview and Requirements

-   **Purpose:** Rewritten to support POSIX shell compatibility and replace the deprecated legacy S.M.A.R.T. plugin.
-   **Compatibility:** Requires Checkmk version 2.3 or newer (becoming the default standard in version 2.4).
-   **Protocols:** Supports ATA and NVMe disk health statistics, including vendor-specific error counters and temperature metrics.

Installation & Configuration

-   **Placement:** Manually install the plugin script into the standard agent plugin directory, such as `/usr/local/check_mk_agent/plugins/` or `/usr/lib/check_mk_agent/plugins/`.
-   **Execution:** Ensure the script file has execute permissions enabled on the target host.
-   **Management:** For automated deployments, use the Checkmk Agent Bakery to bake and push the plugin configuration directly to your hosts.

If you'd like, let me know:

-   Your current **Checkmk version**
-   Your **operating system or platform** (e.g., Linux, OPNsense)

I can provide specific setup steps or configuration rules.

More

---

# you asked

message time: 11:46 am

2.4p35

---

# googlesearch response

Running **Checkmk version 2.4p35** means you are on a mature, highly updated patch release of the 2.4 generation. In this specific version, **`smart_posix` is completely native**, stable, and serves as the primary replacement for the deprecated legacy `smart` plugin.

What this means for your 2.4p35 environment

-   **Item Format Change:** Your version uses the newer, more robust discovery logic. SMART service items are classified directly by combining the hardware **\[Model + Serial Number\]** to ensure items don't shift or break during a device re-index.
-   **Separated Check Services:** Instead of a single monolithic chunk of output, your 2.4 environment splits execution into distinct, performant monitoring tracks:
    -   `smart_ata_temp` / `smart_nvme_temp` (Temperature tracks)
    -   `smart_ata_stats` / `smart_nvme_stats` (Error counters and life endurance tracking)
    -   `smart_scsi_temp` (Legacy and corporate SAN arrays)
-   **Stability Fixes:** Because you are running a late 2.4 patch release, you inherit crucial stability fixes baked directly into the core, including resolution of the `ValidationError` bug for ATA attributes and tracking issues with Power-On Hours.

Requirements & Deployment

1.  **Prerequisite:** Ensure that `smartctl` (from the `smartmontools` package) is updated to **version 7.0 or newer** on your target host. The POSIX plugin relies strictly on structural JSON/modern outputs that old binaries do not provide.
2.  **Using Agent Bakery (Enterprise/Cloud):**
    -   Go to **Setup > Agents > Windows, Linux, Solaris, AIX > Agent rules**.
    -   Search for **SMART harddisk monitoring (Linux/POSIX)**.
    -   Enable the POSIX rule, bake your agent, and update your hosts.
3.  **Manual Installation (Raw Edition):**
    -   Locate the script on your Checkmk server site at: `$OMD_ROOT/share/check_mk/agents/plugins/smart_posix`
    -   Copy it to your target host's plugin directory (usually `/usr/lib/check_mk_agent/plugins/`).
    -   Make sure it is executable: `chmod +x /usr/lib/check_mk_agent/plugins/smart_posix`

Would you like help looking at **specific smart\_posix discovery issues**, or do you need assistance configuring **custom thresholds** for your drive temperatures in the 2.4 GUI?

More