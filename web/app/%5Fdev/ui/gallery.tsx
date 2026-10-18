"use client";

import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";

const SOURCES = [
  { name: "payment-api", status: "Synchronisé" },
  { name: "auth-service", status: "Synchronisé" },
  { name: "legacy-billing-system-that-nobody-remembers-configuring", status: "Erreur" },
] as const;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4 rounded-xl border border-shell-line bg-white p-5">
      <h2 className="text-sm font-semibold tracking-wide text-shell-muted uppercase">{title}</h2>
      {children}
    </section>
  );
}

export function UiGallery() {
  return (
    <main className="mx-auto max-w-3xl space-y-6 bg-shell-canvas p-8">
      <header>
        <h1 className="text-lg font-semibold text-brand-navy">
          Table, Tabs, Pagination — LEKA-339
        </h1>
        <p className="text-sm text-shell-muted">
          Développement uniquement. Voir /_dev/states et /_dev/forms pour le reste.
        </p>
      </header>

      <Section title="Tabs">
        <Tabs defaultValue="sources">
          <TabsList>
            <TabsTab value="sources">Sources</TabsTab>
            <TabsTab value="history">Historique</TabsTab>
            <TabsTab value="disabled" disabled>
              Indisponible
            </TabsTab>
          </TabsList>
          <TabsPanel value="sources" className="pt-3 text-sm text-shell-nav">
            Contenu de l&apos;onglet Sources.
          </TabsPanel>
          <TabsPanel value="history" className="pt-3 text-sm text-shell-nav">
            Contenu de l&apos;onglet Historique.
          </TabsPanel>
        </Tabs>
      </Section>

      <Section title="Table">
        {/* The long name in the third row is not a typo: it is what proves
            the wrapper scrolls instead of the page, at 1024px in particular. */}
        <Table>
          <TableCaption>Sources connectées de ce workspace</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>Nom</TableHead>
              <TableHead>Statut</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {SOURCES.map((source) => (
              <TableRow key={source.name}>
                <TableCell>{source.name}</TableCell>
                <TableCell>{source.status}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Section>

      <Section title="Pagination — cursor (how every real list in LEKA pages)">
        <Pagination>
          <PaginationContent>
            <PaginationItem>
              <PaginationPrevious label="Précédent" disabled />
            </PaginationItem>
            <PaginationItem>
              <PaginationNext label="Suivant" onClick={() => window.alert("onNext(cursor)")} />
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      </Section>

      <Section title="Pagination — numbered (a fully-known list, the rarer case)">
        <Pagination>
          <PaginationContent>
            <PaginationItem>
              <PaginationLink href="#">1</PaginationLink>
            </PaginationItem>
            <PaginationItem>
              <PaginationLink href="#" isActive>
                2
              </PaginationLink>
            </PaginationItem>
            <PaginationItem>
              <PaginationLink href="#">3</PaginationLink>
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      </Section>
    </main>
  );
}
