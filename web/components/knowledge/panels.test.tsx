/**
 * MetadataPanel and KnowledgeTable: nominal, partial, empty, large.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type KnowledgeColumn, KnowledgeTable } from "@/components/knowledge/knowledge-table";
import { MetadataPanel } from "@/components/knowledge/metadata-panel";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

function mount(node: React.ReactNode) {
  return render(<LocaleProvider>{node}</LocaleProvider>);
}

describe("MetadataPanel", () => {
  it("reads each value with its label, in sections", () => {
    mount(
      <MetadataPanel
        columns={2}
        sections={[
          {
            title: "Informations générales",
            items: [
              { label: "Environnement", value: "Production" },
              { label: "Version", value: "v2.8.4" },
            ],
          },
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "Informations générales" })).toBeVisible();
    const terms = screen.getAllByRole("term").map((term) => term.textContent);
    const values = screen.getAllByRole("definition").map((value) => value.textContent);
    expect(terms).toEqual(["Environnement", "Version"]);
    expect(values).toEqual(["Production", "v2.8.4"]);
  });

  it("shows a dash for a missing value, and nothing for empty sections", () => {
    const { container } = mount(
      <MetadataPanel
        sections={[
          { title: "Vide", items: [] },
          { items: [{ label: "Runbook", value: null }] },
        ]}
      />,
    );

    expect(screen.queryByRole("heading", { name: "Vide" })).toBeNull();
    expect(screen.getByRole("definition")).toHaveTextContent("—");
    expect(container.querySelector("[data-slot=metadata-panel]")).not.toBeNull();
  });

  it("renders nothing at all when there is nothing to say", () => {
    const { container } = mount(<MetadataPanel sections={[]} />);

    expect(container.querySelector("[data-slot=metadata-panel]")).toBeNull();
  });

  function withClipboard(writeText: (text: string) => Promise<void>) {
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  }

  it("copies a value and says so", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    mount(
      <MetadataPanel copyable sections={[{ items: [{ label: "Commit", value: "a1b3c4d" }] }]} />,
    );
    withClipboard(writeText);

    await user.click(screen.getByRole("button", { name: "Copier Commit" }));
    expect(writeText).toHaveBeenCalledWith("a1b3c4d");
    expect(screen.getByRole("status")).toHaveTextContent("Commit copié");
  });

  it("never claims a copy the clipboard refused", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockRejectedValue(new Error("refused"));
    mount(
      <MetadataPanel copyable sections={[{ items: [{ label: "Commit", value: "a1b3c4d" }] }]} />,
    );
    withClipboard(writeText);

    await user.click(screen.getByRole("button", { name: "Copier Commit" }));
    expect(writeText).toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("");
  });
});

interface Row {
  id: string;
  name: string;
  incidents: number | null;
}

const COLUMNS: KnowledgeColumn<Row>[] = [
  { id: "name", header: "Nom", cell: (row) => row.name, sortValue: (row) => row.name },
  {
    id: "incidents",
    header: "Incidents",
    cell: (row) => row.incidents ?? "—",
    sortValue: (row) => row.incidents,
    align: "end",
  },
  { id: "id", header: "Identifiant", cell: (row) => row.id },
];

const rows = (count: number): Row[] =>
  Array.from({ length: count }, (_, index) => ({
    id: `svc-${index}`,
    name: `Service ${String(index).padStart(3, "0")}`,
    incidents: index % 7 === 0 ? null : index % 5,
  }));

const bodyRows = () => within(screen.getAllByRole("rowgroup")[1]).getAllByRole("row");

describe("KnowledgeTable", () => {
  it("has a caption and headers that describe it", () => {
    mount(<KnowledgeTable caption="Services" columns={COLUMNS} rows={rows(3)} rowKey={(r) => r.id} />);

    expect(screen.getByRole("table", { name: "Services" })).toBeVisible();
    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
      "Nom",
      "Incidents",
      "Identifiant",
    ]);
    expect(bodyRows()).toHaveLength(3);
  });

  it("sorts from the header, says how in aria-sort, and keeps missing values last", async () => {
    const user = userEvent.setup();
    mount(<KnowledgeTable caption="Services" columns={COLUMNS} rows={rows(8)} rowKey={(r) => r.id} />);

    const header = screen.getByRole("columnheader", { name: /Incidents/ });
    expect(header).toHaveAttribute("aria-sort", "none");

    await user.click(screen.getByRole("button", { name: "Trier par Incidents" }));
    expect(header).toHaveAttribute("aria-sort", "ascending");
    expect(bodyRows().at(-1)).toHaveTextContent("—");

    await user.click(screen.getByRole("button", { name: "Trier par Incidents" }));
    expect(header).toHaveAttribute("aria-sort", "descending");
    expect(bodyRows()[0]).toHaveTextContent("4");
    expect(bodyRows().at(-1)).toHaveTextContent("—");
    expect(screen.getByRole("columnheader", { name: "Identifiant" })).not.toHaveAttribute("aria-sort");
  });

  it("pages 500 rows, rendering one page at a time", async () => {
    const user = userEvent.setup();
    mount(<KnowledgeTable caption="Services" columns={COLUMNS} rows={rows(500)} rowKey={(r) => r.id} />);

    expect(bodyRows()).toHaveLength(25);
    expect(screen.getByText("Page 1 sur 20")).toBeVisible();
    expect(screen.getByRole("button", { name: /Précédent/ })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /Suivant/ }));
    expect(screen.getByText("Page 2 sur 20")).toBeVisible();
    expect(bodyRows()[0]).toHaveTextContent("Service 025");
  });

  it("opens a row from the mouse or the keyboard", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    mount(
      <KnowledgeTable
        caption="Services"
        columns={COLUMNS}
        rows={rows(2)}
        rowKey={(r) => r.id}
        onRowClick={onRowClick}
      />,
    );

    await user.click(bodyRows()[0]);
    expect(onRowClick).toHaveBeenLastCalledWith(expect.objectContaining({ id: "svc-0" }));

    bodyRows()[1].focus();
    await user.keyboard("{Enter}");
    expect(onRowClick).toHaveBeenLastCalledWith(expect.objectContaining({ id: "svc-1" }));
  });

  it("shows skeleton rows while loading, and says it is loading", () => {
    mount(<KnowledgeTable caption="Services" columns={COLUMNS} rows={[]} rowKey={(r) => r.id} loading />);

    expect(screen.getByRole("table")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Chargement…");
  });

  it("says so when it is empty, with the way forward it is given", () => {
    mount(
      <KnowledgeTable
        caption="Services"
        columns={COLUMNS}
        rows={[]}
        rowKey={(r) => r.id}
        empty={{
          title: "Aucun service",
          description: "Connectez une source pour les découvrir.",
          action: <button type="button">Ajouter une source</button>,
        }}
      />,
    );

    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("heading", { name: "Aucun service" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Ajouter une source" })).toBeVisible();
  });
});
