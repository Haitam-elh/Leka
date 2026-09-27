"use client";

import Link from "next/link";
import { useState } from "react";

import { AuthCard } from "@/components/auth/auth-card";
import { FormMessage, PASSWORD_MIN, authErrorMessage } from "@/components/auth/form-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { COMPANY_SIZES, type CompanySize, auth } from "@/lib/auth";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { useOnlineStatus } from "@/lib/use-online-status";

/**
 * Creating an account.
 *
 * Asks what the site's forms have always asked — first and last name and
 * the company, required; the role and the company's size, if they want to
 * say — so whoever grants access knows who is asking for it.
 */
export default function RegisterPage() {
  const t = useDictionary();
  const online = useOnlineStatus();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [company, setCompany] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [companySize, setCompanySize] = useState<CompanySize | "">("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const tooShort = password.length > 0 && password.length < PASSWORD_MIN;
  const sizes = COMPANY_SIZES.map((size) => ({ value: size, label: t.auth.companySizes[size] }));

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      await auth.register(email, password, {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        company: company.trim(),
        // Left out rather than sent empty: the API keeps what it is given.
        ...(jobTitle.trim() ? { job_title: jobTitle.trim() } : {}),
        ...(companySize ? { company_size: companySize } : {}),
      });
      // Shown whether or not the address was free. The server answers
      // identically in both cases, and so does this screen — otherwise the
      // form becomes a way to ask who already has an account.
      setDone(true);
    } catch (caught) {
      setError(authErrorMessage(t, caught, online));
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <AuthCard
        title={t.auth.checkInbox}
        description={t.auth.registerSent}
        footer={
          <Link href="/login" className="underline underline-offset-4">
            {t.auth.backToSignIn}
          </Link>
        }
      >
        <p className="text-sm text-muted-foreground">{t.auth.registerLinkLife}</p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      wide
      title={t.auth.registerTitle}
      description={t.auth.registerDescription}
      footer={
        <>
          {t.auth.alreadyHaveOne}{" "}
          <Link href="/login" className="underline underline-offset-4">
            {t.auth.signIn}
          </Link>
        </>
      }
    >
      <FormMessage message={error} />

      <form onSubmit={onSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="first-name">{t.auth.firstName}</Label>
            <Input
              id="first-name"
              autoComplete="given-name"
              required
              maxLength={100}
              value={firstName}
              onChange={(event) => setFirstName(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="last-name">{t.auth.lastName}</Label>
            <Input
              id="last-name"
              autoComplete="family-name"
              required
              maxLength={100}
              value={lastName}
              onChange={(event) => setLastName(event.target.value)}
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="company">{t.auth.company}</Label>
          <Input
            id="company"
            autoComplete="organization"
            required
            maxLength={200}
            value={company}
            onChange={(event) => setCompany(event.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="job-title">
            {t.auth.jobTitle}{" "}
            <span className="font-normal text-muted-foreground">{t.auth.optional}</span>
          </Label>
          <Input
            id="job-title"
            autoComplete="organization-title"
            maxLength={100}
            value={jobTitle}
            onChange={(event) => setJobTitle(event.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label id="company-size-label">
            {t.auth.companySize}{" "}
            <span className="font-normal text-muted-foreground">{t.auth.optional}</span>
          </Label>
          <Select
            value={companySize}
            onValueChange={(value) => setCompanySize((value as CompanySize | null) ?? "")}
            // Without the items, the closed select prints "51-200" rather
            // than what the person chose from.
            items={sizes}
          >
            <SelectTrigger className="w-full" aria-labelledby="company-size-label">
              <SelectValue placeholder={t.auth.selectSize} />
            </SelectTrigger>
            <SelectContent>
              {sizes.map((size) => (
                <SelectItem key={size.value} value={size.value}>
                  {size.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="email">{t.auth.workEmail}</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="password">{t.auth.password}</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={PASSWORD_MIN}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-describedby="password-help"
          />
          {/* Length only. No composition rules: demanding an uppercase and
              a digit produces Password1! and nothing stronger. */}
          <p
            id="password-help"
            className={`text-xs ${tooShort ? "text-state-danger" : "text-muted-foreground"}`}
          >
            {fill(t.auth.passwordRule, { min: PASSWORD_MIN })}
          </p>
        </div>

        <Button type="submit" className="w-full" disabled={busy || tooShort}>
          {busy ? t.auth.creating : t.auth.createAccount}
        </Button>
      </form>
    </AuthCard>
  );
}
