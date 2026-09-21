export interface EmailFooterProps {
  year?: number;
  tone?: "brand" | "subtle" | "plain";
}

/** Static transactional-email footer block: legal links, address, tagline. */
export function EmailFooter({ year = new Date().getFullYear(), tone = "brand" }: EmailFooterProps) {
  const isBrand = tone === "brand";
  const bg = tone === "brand" ? "bg-brand" : tone === "subtle" ? "bg-bg-subtle" : "bg-transparent";
  const text = isBrand ? "text-fg-oncolor" : "text-fg-primary";
  const link = isBrand ? "text-fg-oncolor underline" : "text-fg-link";

  return (
    <footer className={["flex flex-col gap-4 p-6", bg].join(" ")}>
      <span className={["text-lg font-bold tracking-wide", text].join(" ")}>KONE</span>
      <div className={["flex flex-wrap gap-1 text-sm", link].join(" ")}>
        <a href="#">Support</a>
        <span className={text}>|</span>
        <a href="#">Terms and conditions</a>
        <span className={text}>|</span>
        <a href="#">Privacy statement</a>
      </div>
      <p className={["text-sm", text].join(" ")}>
        Copyright &copy; {year} KONE Oyj, Keilasatama 3, 02150 Espoo, Finland
      </p>
      <a href="#" className={["text-sm", link].join(" ")}>
        KONE.be
      </a>
      <p className={["mt-4 text-xl font-semibold", text].join(" ")}>
        Dedicated to
        <br />
        People Flow&trade;
      </p>
    </footer>
  );
}
