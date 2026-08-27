> From: https://www.google.com/search?smstk=ChhxQmgwTldYWVJBVWJJeFFmWTNUd3NqVT0QBBgA&smstidx=0&q=checkmk+linux+agent+ssd+smart+disk&udm=50&csuir=1&aep=34&kgs=2dec6e645a1ef56c&shem=epsd1%2Crimspwouoe&shndl=37&shmd=H4sIAAAAAAAA_3WOvQrCMBRG7SZdBEen0FEwsYuD-C7hNgnJpc0PuSnt2MfyGXwL38QKOonrB-c7p35WdaOcUb3v2YBhnBlYEwoj0ow85MI0Un-4uVISXYWYpolbKlBQcRW9IANZuVPK0UcB6CU5yEYWN_ouAA48Bdvsv7SN0Q6GA4rjZl52S3XfPir57xv92kKiyxA0BvuhrbQZNK6Rop1_NrnyQUPWsr2cdXrrX-zGFnTkAAAA&shmds=v1_ARwrE23qd1_Lpnn2N7I6961I4JSjI-WMgXtJnpuiDR2-edjpLQ&source=sh%2Fx%2Faio%2Fm1%2F1&atvm=2&mtid=Bq6PasiTLZfa4-EPq-qkyAc

# you asked

message time: 11:12 am

checkmk linux agent ssd smart disk

---

# googlesearch response

You can monitor SSD and NVMe S.M.A.R.T. health statistics in Checkmk by installing the `smartmontools` package on the target Linux host and enabling the `smart_posix` agent plugin.

Prerequisites

-   Install `smartmontools` on the target Linux machine (e.g., via `apt install smartmontools` or `yum install smartmontools`).
-   Ensure the Checkmk Linux agent is installed and running with permissions to execute `smartctl`.

Configuration Steps

1.  **Enable the Plugin:** Deploy the `smart_posix` agent plugin to the agent’s plugin directory (typically `/usr/lib/check_mk_agent/plugins/`).
2.  **Configure via GUI:** In the Checkmk Web interface, go to **Setup** and search for **SMART harddisk monitoring (Linux)** (or configure via the Agent Bakery).
3.  **Add Rule:** Create a new rule, assign it to your host or folder, and save/activate changes.
4.  **Service Discovery:** Perform a service discovery on the host to let Checkmk detect the SSD/NVMe temperatures, wear levels, and S.M.A.R.T. error statistics (`smart_temp`, `smart_nvme_stats`, etc.).

_Note:_ Most users on the Checkmk Forum note that if your SSDs are behind a hardware RAID controller (like LSI/MegaRAID), you may need to pass explicit device type arguments (such as `-d megaraid,N`) inside the plugin configuration so `smartctl` can query the underlying drives.

If you'd like, let me know:

-   Are the drives connected **directly** or via a **RAID controller**?
-   Are they **SATA/SAS SSDs** or **NVMe drives**?

I can provide the exact configuration parameters or troubleshooting commands.

More