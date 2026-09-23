"use client";

import { CircleCheck, Inbox, TriangleAlert } from "lucide-react";

import { RouteState, type RouteStateVariant } from "@/components/shell/route-state";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";
import { OfflineBanner } from "@/components/states/offline-banner";
import { StatePanel } from "@/components/states/state-panel";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/toast";
import { ApiError } from "@/lib/api";
import { notify } from "@/lib/notify";

const ROUTE_STATES: readonly RouteStateVariant[] = [
  "empty",
  "unavailable",
  "plan-gated",
  "forbidden",
  "not-found",
];

// One error per kind lib/errors.ts tells apart. "offline" is not here: it
// is decided by the browser, not the error — cut the network in DevTools
// and every panel below turns into it, and the banner at the top appears.
const ERRORS: readonly [label: string, error: unknown][] = [
  ["API injoignable", new ApiError(0, "/auth/me", "Cannot reach the API")],
  ["Erreur serveur, avec référence", new ApiError(500, "/x", "boom", undefined, undefined, "req-4f2a9c")],
  ["Refus (403)", new ApiError(403, "/x", "forbidden")],
  ["Introuvable (404)", new ApiError(404, "/x", "not found")],
  ["Plantage du rendu", new TypeError("Cannot read properties of undefined")],
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4 rounded-xl border border-shell-line bg-white p-5">
      <h2 className="text-sm font-semibold tracking-wide text-shell-muted uppercase">{title}</h2>
      {children}
    </section>
  );
}

function Labelled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-shell-line">
      <p className="border-b border-dashed border-shell-line px-3 py-1.5 text-xs text-shell-muted">
        {label}
      </p>
      {children}
    </div>
  );
}

export function StatesGallery() {
  return (
    <>
      <Toaster closeLabel="Fermer" />
      <OfflineBanner />
      <main className="mx-auto max-w-3xl space-y-6 bg-shell-canvas p-8">
        <header>
          <h1 className="text-xl font-semibold text-brand-navy">États du système</h1>
          <p className="mt-1 text-sm text-shell-muted">
            LEKA-343 · développement uniquement. Coupez le réseau dans les DevTools pour voir
            l&apos;état hors ligne : le bandeau apparaît en haut et chaque erreur ci-dessous
            change de nature.
          </p>
        </header>

        <Section title="Chargement">
          <Labelled label="Page">
            <LoadingState delayMs={0} />
          </Labelled>
          <Labelled label="Section">
            <div className="px-4">
              <LoadingState size="section" delayMs={0} />
            </div>
          </Labelled>
        </Section>

        <Section title="Vide, indisponible, permission">
          {ROUTE_STATES.map((variant) => (
            <Labelled key={variant} label={variant}>
              <RouteState variant={variant} headingLevel={3} />
            </Labelled>
          ))}
        </Section>

        <Section title="Erreur">
          {ERRORS.map(([label, error]) => (
            <Labelled key={label} label={label}>
              <ErrorState error={error} onRetry={() => undefined} headingLevel={3} />
            </Labelled>
          ))}
          <Labelled label="Dans une section (sans lien de retour)">
            <ErrorState
              error={new ApiError(0, "/x", "unreachable")}
              onRetry={() => undefined}
              size="section"
              headingLevel={3}
            />
          </Labelled>
        </Section>

        <Section title="Tons du socle commun">
          <Labelled label="neutral">
            <StatePanel icon={Inbox} title="Aucune intention" description="Lancez-en une." headingLevel={3} size="section" />
          </Labelled>
          <Labelled label="success">
            <StatePanel icon={CircleCheck} tone="success" title="Source connectée" description="La première synchronisation commence." headingLevel={3} size="section" />
          </Labelled>
          <Labelled label="warning / danger">
            <StatePanel icon={TriangleAlert} tone="warning" title="Synchronisation partielle" description="Trois dépôts n'ont pas pu être lus." headingLevel={3} size="section" />
            <StatePanel icon={TriangleAlert} tone="danger" title="Synchronisation en échec" description="Reconnectez la source." headingLevel={3} size="section" />
          </Labelled>
        </Section>

        <Section title="Succès et retour d'action">
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => notify.success({ title: "Paramètres enregistrés." })}
            >
              Succès
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                notify.error({
                  title: "Impossible d'enregistrer.",
                  description: "Vérifiez votre connexion puis réessayez.",
                })
              }
            >
              Erreur (reste affichée)
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                notify.info({
                  title: "Analyse lancée.",
                  action: { label: "Voir l'intention", onClick: () => undefined },
                })
              }
            >
              Info avec action
            </Button>
          </div>
        </Section>
      </main>
    </>
  );
}
