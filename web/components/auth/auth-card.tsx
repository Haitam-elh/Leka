import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

/**
 * The card every authentication screen sits in.
 *
 * The title is a real <h2>, not shadcn's CardTitle. CardTitle renders a
 * <div>, which means a screen reader gets no heading for the page — the
 * layout's "LEKA" is the h1, and this is the h2 under it. It is also what
 * makes the browser tests able to assert on a heading, which is how the
 * omission was noticed.
 */
export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{title}</h2>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
      {footer ? (
        <div className="border-t px-6 py-4 text-center text-sm text-muted-foreground">
          {footer}
        </div>
      ) : null}
    </Card>
  );
}
