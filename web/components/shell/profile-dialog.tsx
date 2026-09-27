"use client";

import { useState } from "react";

import { useCurrentUser, useUpdateCurrentUser } from "@/components/shell/shell-provider";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api";
import { COMPANY_SIZES, type CompanySize, auth, markSignedOut } from "@/lib/auth";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * Who the signed-in person says they are, changed from the account menu.
 *
 * The same five questions as registration. It is how an account made
 * before registration asked gets a name — until then the overview greets
 * it by the first part of its address — and how anyone corrects theirs.
 * The address itself is not here: changing it needs the new one proven.
 */
export function ProfileDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useDictionary();
  const user = useCurrentUser();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t.shell.profileTitle}</DialogTitle>
          <DialogDescription>{t.shell.profileDescription}</DialogDescription>
        </DialogHeader>
        {/* Mounted with the dialog, so every opening starts from what the
            API last said rather than from an abandoned draft. */}
        {open && user ? <ProfileForm user={user} onDone={() => onOpenChange(false)} /> : null}
        {open && user ? <CloseAccount /> : null}
      </DialogContent>
    </Dialog>
  );
}

function ProfileForm({
  user,
  onDone,
}: {
  user: NonNullable<ReturnType<typeof useCurrentUser>>;
  onDone: () => void;
}) {
  const t = useDictionary();
  const updateUser = useUpdateCurrentUser();
  const [firstName, setFirstName] = useState(user.first_name ?? "");
  const [lastName, setLastName] = useState(user.last_name ?? "");
  const [company, setCompany] = useState(user.company ?? "");
  const [jobTitle, setJobTitle] = useState(user.job_title ?? "");
  const [companySize, setCompanySize] = useState<CompanySize | "">(user.company_size ?? "");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const sizes = COMPANY_SIZES.map((size) => ({ value: size, label: t.auth.companySizes[size] }));

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailed(false);
    try {
      const saved = await auth.updateProfile({
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        company: company.trim(),
        // Cleared with null: the API keeps an empty answer as none.
        job_title: jobTitle.trim() || null,
        company_size: companySize || null,
      });
      updateUser(saved);
      onDone();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {failed ? (
        <Alert variant="destructive">
          <AlertDescription>{t.shell.profileFailed}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor="profile-first-name">{t.auth.firstName}</Label>
          <Input
            id="profile-first-name"
            autoComplete="given-name"
            required
            maxLength={100}
            value={firstName}
            onChange={(event) => setFirstName(event.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="profile-last-name">{t.auth.lastName}</Label>
          <Input
            id="profile-last-name"
            autoComplete="family-name"
            required
            maxLength={100}
            value={lastName}
            onChange={(event) => setLastName(event.target.value)}
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="profile-company">{t.auth.company}</Label>
        <Input
          id="profile-company"
          autoComplete="organization"
          required
          maxLength={200}
          value={company}
          onChange={(event) => setCompany(event.target.value)}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="profile-job-title">
          {t.auth.jobTitle}{" "}
          <span className="font-normal text-muted-foreground">{t.auth.optional}</span>
        </Label>
        <Input
          id="profile-job-title"
          autoComplete="organization-title"
          maxLength={100}
          value={jobTitle}
          onChange={(event) => setJobTitle(event.target.value)}
        />
      </div>

      <div className="space-y-2">
        <Label id="profile-company-size-label">
          {t.auth.companySize}{" "}
          <span className="font-normal text-muted-foreground">{t.auth.optional}</span>
        </Label>
        <Select
          value={companySize}
          onValueChange={(value) => setCompanySize((value as CompanySize | null) ?? "")}
          items={sizes}
        >
          <SelectTrigger className="w-full" aria-labelledby="profile-company-size-label">
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

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          {t.shell.cancel}
        </Button>
        <Button type="submit" disabled={busy}>
          {busy ? t.shell.profileSaving : t.shell.profileSave}
        </Button>
      </DialogFooter>
    </form>
  );
}

/**
 * Closing the account, at the foot of the profile: out of the way, behind
 * a second step, and the password again.
 *
 * What the API does is said before it is asked: a workspace the person is
 * alone in is deleted with them, after the grace period; a workspace others
 * use, of which they are the last owner, refuses — they hand it over first.
 */
function CloseAccount() {
  const t = useDictionary().shell.closeAccount;
  const [asked, setAsked] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth.deleteAccount(password);
      // Gone, and signed out: back to the site they came from.
      markSignedOut();
      window.location.assign("/");
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "last_owner") setError(t.lastOwner);
      else if (caught instanceof ApiError && caught.status === 403) setError(t.wrongPassword);
      else setError(t.failed);
      setBusy(false);
    }
  }

  return (
    <section className="mt-2 border-t border-shell-line pt-4">
      <h2 className="text-sm font-semibold text-state-danger">{t.title}</h2>
      <p className="mt-1 text-xs text-shell-muted">{t.body}</p>
      {asked ? (
        <form onSubmit={onSubmit} className="mt-3 space-y-3">
          {error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          <div className="space-y-2">
            <Label htmlFor="close-account-password">{t.password}</Label>
            <Input
              id="close-account-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setAsked(false)}>
              {t.cancel}
            </Button>
            <Button type="submit" variant="destructive" disabled={busy || password === ""}>
              {busy ? t.deleting : t.confirm}
            </Button>
          </div>
        </form>
      ) : (
        <Button
          type="button"
          variant="outline"
          className="mt-3 text-state-danger"
          onClick={() => setAsked(true)}
        >
          {t.open}
        </Button>
      )}
    </section>
  );
}
