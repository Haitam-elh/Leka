/**
 * The layout the authentication screens share.
 *
 * Deliberately minimal: a centred card on an empty page. The application
 * shell — sidebar, header, workspace switcher — is LEKA-337 and does not
 * exist yet. Building it here would mean building it twice.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/30 px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">LEKA</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Understand. Decide. Act.
          </p>
        </div>
        {children}
      </div>
    </main>
  );
}
