import { useState } from "react";
import {
  Accordion,
  AppBar,
  Badge,
  Banner,
  Button,
  ButtonGroup,
  Checkbox,
  CounterBadge,
  DatePicker,
  Divider,
  EmailFooter,
  FilterBar,
  FilterChip,
  Input,
  InputStepper,
  Menu,
  Message,
  MultiSelect,
  NavBar,
  Pagination,
  ProgressBar,
  ProgressCircle,
  Radio,
  Search,
  SegmentedControl,
  Select,
  SelectableCard,
  SelectorChip,
  Snackbar,
  StaticData,
  StatTile,
  StatusBadge,
  Steps,
  Switch,
  Table,
  Textarea,
  Tooltip,
} from "./components";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-10">
      <h2 className="mb-3 text-xl font-semibold text-fg-primary">{title}</h2>
      <div className="rounded-lg border border-neutral-150 bg-bg-surface p-6">{children}</div>
    </section>
  );
}

export default function App() {
  const [page, setPage] = useState(4);
  const [segment, setSegment] = useState("today");
  const [floors, setFloors] = useState(2);
  const [switchOn, setSwitchOn] = useState(true);
  const [chipSelected, setChipSelected] = useState("a");
  const [filters, setFilters] = useState(["Passenger", "Elevator"]);
  const [date, setDate] = useState<Date | undefined>(new Date(2026, 8, 14));
  const [multi, setMulti] = useState<string[]>(["office"]);
  const [card, setCard] = useState("a");
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" }>({ key: "site", dir: "asc" });

  const rows = [
    { id: "1", site: "IKEA Bristol", type: "Entrapment", status: "Technician has arrived" },
    { id: "2", site: "IKEA Glasgow", type: "Repair", status: "Technician on the way" },
    { id: "3", site: "IKEA Bristol", type: "Planned maintenance", status: "Scheduled" },
  ];

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="mb-8 text-2xl font-semibold text-fg-primary">KONE Design System</h1>

      <Section title="Button">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary">Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="tertiary">Tertiary</Button>
          <Button variant="destructive">Destructive</Button>
          <Button variant="neutral">Neutral</Button>
          <Button variant="primary" disabled>
            Disabled
          </Button>
          <Button variant="primary" loading>
            Loading
          </Button>
        </div>
        <div className="mt-4">
          <ButtonGroup>
            <Button variant="secondary">Cancel</Button>
            <Button variant="primary">OK</Button>
          </ButtonGroup>
        </div>
      </Section>

      <Section title="Badge">
        <div className="flex flex-wrap items-center gap-3">
          <Badge color="info">Badge</Badge>
          <Badge color="success" variant="soft">
            Badge
          </Badge>
          <Badge color="warning" variant="solid">
            Badge
          </Badge>
          <Badge color="danger">Badge</Badge>
          <Badge color="purple">Badge</Badge>
          <Badge color="black" variant="solid">
            Badge
          </Badge>
          <CounterBadge count={20} color="danger" />
          <CounterBadge count={20} color="brand" />
          <CounterBadge count={130} color="neutral" />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-4">
          <StatusBadge status="connected">Connected</StatusBadge>
          <StatusBadge status="low-signal">Low signal</StatusBadge>
          <StatusBadge status="entrapment">Entrapment</StatusBadge>
        </div>
      </Section>

      <Section title="Snackbar">
        <div className="flex flex-col gap-3">
          <Snackbar status="info" icon="i" message="An action has been performed by the app as a result of a user input." actionLabel="Undo" />
          <Snackbar status="success" icon="✓" message="An action has been performed by the app as a result of a user input." actionLabel="Undo" />
          <Snackbar status="warning" icon="!" message="An action has been performed by the app as a result of a user input." actionLabel="Undo" />
          <Snackbar status="danger" icon="!" message="An action has been performed by the app as a result of a user input." actionLabel="Undo" />
        </div>
      </Section>

      <Section title="Banner">
        <div className="-mx-6 flex flex-col">
          <Banner status="info" icon="i" message="A banner displays an important message, and provides action for users to address." onDismiss={() => {}} />
          <Banner status="success" icon="✓" message="A banner displays an important message, and provides action for users to address." onDismiss={() => {}} />
          <Banner status="warning" icon="!" message="A banner displays an important message, and provides action for users to address." onDismiss={() => {}} />
          <Banner status="danger" icon="!" message="A banner displays an important message, and provides action for users to address." onDismiss={() => {}} />
        </div>
      </Section>

      <Section title="Message">
        <div className="flex flex-col gap-3">
          <Message status="info" icon="i" title="No internet" description="Please check your internet connection and try again." onCancel={() => {}} onConfirm={() => {}} />
          <Message status="danger" icon="!" title="No internet" description="Please check your internet connection and try again." onCancel={() => {}} onConfirm={() => {}} />
        </div>
      </Section>

      <Section title="Accordion">
        <Accordion
          defaultOpenId="1"
          items={[
            { id: "1", title: "Section", content: "Section content goes here." },
            { id: "2", title: "Section", content: "Section content goes here." },
            { id: "3", title: "Section", content: "Section content goes here." },
          ]}
        />
      </Section>

      <Section title="Input field / Search / Textarea">
        <div className="grid grid-cols-2 gap-4">
          <Input label="Label" placeholder="Input text" />
          <Input label="Label" placeholder="Input text" error="This field is required" />
          <Input label="Label" defaultValue="Disabled" disabled />
          <Search placeholder="Search" onSubmit={() => {}} />
          <Textarea label="Label" placeholder="Multiline input" className="col-span-2" />
        </div>
      </Section>

      <Section title="Select / Input stepper / Static data">
        <div className="grid grid-cols-3 gap-4">
          <Select label="Label" options={[{ value: "a", label: "Option A" }, { value: "b", label: "Option B" }]} />
          <InputStepper label="Floors" value={floors} min={0} max={10} onChange={setFloors} />
          <StaticData label="Label" value="Static value" />
        </div>
      </Section>

      <Section title="Checkbox / Radio / Switch">
        <div className="flex flex-wrap items-center gap-6">
          <Checkbox label="Option" defaultChecked />
          <Checkbox label="Option" />
          <Checkbox label="Option" indeterminate />
          <Checkbox label="Disabled" disabled />
          <Radio name="r" label="Option" defaultChecked />
          <Radio name="r" label="Option" />
          <Switch label="On" checked={switchOn} onChange={(e) => setSwitchOn(e.target.checked)} />
        </div>
      </Section>

      <Section title="Tooltip">
        <div className="flex items-center gap-8 py-4">
          <Tooltip content="Sample text" position="top">
            <Button variant="secondary" size="sm">Hover me</Button>
          </Tooltip>
        </div>
      </Section>

      <Section title="Progress bar / circle">
        <div className="flex flex-col gap-4">
          <ProgressBar label="Uploading" value={65} />
          <div className="flex items-center gap-4">
            <ProgressCircle value={70} showValue />
            <ProgressCircle value={40} color="warning" />
            <ProgressCircle value={90} color="success" />
          </div>
        </div>
      </Section>

      <Section title="Steps">
        <Steps
          currentIndex={2}
          steps={[
            { id: "1", label: "Step 1 finished" },
            { id: "2", label: "Step 2 finished" },
            { id: "3", label: "Step 3" },
            { id: "4", label: "Step 4" },
          ]}
        />
      </Section>

      <Section title="Pagination">
        <Pagination page={page} pageCount={10} onPageChange={setPage} />
      </Section>

      <Section title="Segmented control">
        <SegmentedControl
          value={segment}
          onChange={setSegment}
          options={[
            { value: "today", label: "Today" },
            { value: "planned", label: "Planned" },
            { value: "past", label: "Past" },
            { value: "flagged", label: "Flagged" },
          ]}
        />
      </Section>

      <Section title="Filter chip / Selector chip">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            {filters.map((f) => (
              <FilterChip key={f} label={f} onRemove={() => setFilters(filters.filter((x) => x !== f))} />
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SelectorChip label="Select" selected={chipSelected === "a"} onToggle={() => setChipSelected("a")} />
            <SelectorChip label="Select" selected={chipSelected === "b"} onToggle={() => setChipSelected("b")} />
          </div>
        </div>
      </Section>

      <Section title="Menu">
        <Menu
          items={[
            { id: "1", label: "Edit" },
            { id: "2", label: "Duplicate" },
            { id: "3", label: "Delete", danger: true },
          ]}
        />
      </Section>

      <Section title="Divider">
        <div className="flex flex-col gap-4">
          <p className="text-sm text-fg-secondary">Content above</p>
          <Divider />
          <p className="text-sm text-fg-secondary">Content below</p>
        </div>
      </Section>

      <Section title="Date picker / Multi-select">
        <div className="grid grid-cols-2 gap-4">
          <DatePicker label="Label" value={date} onChange={setDate} />
          <MultiSelect
            label="Type"
            value={multi}
            onChange={setMulti}
            options={[
              { value: "industrial", label: "Industrial" },
              { value: "office", label: "Office" },
              { value: "home", label: "Home" },
              { value: "marine", label: "Marine" },
            ]}
          />
        </div>
      </Section>

      <Section title="Selectable card">
        <div className="grid grid-cols-2 gap-3">
          <SelectableCard selected={card === "a"} onSelect={() => setCard("a")} title="Selected card" description="Sub text is optional" />
          <SelectableCard selected={card === "b"} onSelect={() => setCard("b")} title="Normal card" description="Sub text is optional" />
        </div>
      </Section>

      <Section title="Navigation / App bar">
        <div className="-mx-6 flex flex-col gap-4">
          <NavBar
            appName="App Name"
            items={[
              { id: "1", label: "Navi item", active: true },
              { id: "2", label: "Navi item" },
              { id: "3", label: "Navi item" },
            ]}
            user={{ name: "Sofia Lehto" }}
          />
          <AppBar title="Technician Assistance" onBack={() => {}} />
        </div>
      </Section>

      <Section title="Filter bar / Table">
        <div className="flex flex-col gap-4">
          <FilterBar
            triggers={[{ id: "site", label: "Site" }, { id: "type", label: "Service type" }]}
            applied={filters.map((f) => ({ id: f, label: f }))}
            onRemove={(id) => setFilters(filters.filter((f) => f !== id))}
            onResetAll={() => setFilters([])}
          />
          <div className="flex flex-wrap gap-3">
            <StatTile label="Entrapment" value={2} tone="danger" />
            <StatTile label="Active" value={8} />
            <StatTile label="Resolved" value={128} />
          </div>
          <Table
            rows={rows}
            rowKey={(r) => r.id}
            sortKey={sort.key}
            sortDirection={sort.dir}
            onSort={(key) => setSort((s) => ({ key, dir: s.key === key && s.dir === "asc" ? "desc" : "asc" }))}
            columns={[
              { key: "site", header: "Site", sortable: true, render: (r) => r.site },
              { key: "type", header: "Service type", sortable: true, render: (r) => r.type },
              { key: "status", header: "Status", render: (r) => r.status },
            ]}
          />
          <Pagination page={1} pageCount={3} onPageChange={() => {}} />
        </div>
      </Section>

      <Section title="Email footer">
        <div className="-mx-6 -mb-6 grid grid-cols-2 overflow-hidden rounded-b-lg">
          <EmailFooter tone="brand" />
          <EmailFooter tone="subtle" />
        </div>
      </Section>
    </main>
  );
}
