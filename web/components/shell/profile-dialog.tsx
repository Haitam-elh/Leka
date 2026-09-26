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
import { COMPANY_SIZES, type CompanySize, auth } from "@/lib/auth";
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
