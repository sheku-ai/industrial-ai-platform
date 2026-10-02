'use client';

import { useState, type FormEvent } from 'react';

import { isSupportedLocale, localeRegistry, supportedLocales } from '../../i18n/config';
import { useI18n } from '../../i18n/I18nProvider';
import { ApiHttpError } from '../../lib/http-client';
import { installationSetupApi, type InstallationStatus } from '../../lib/installation-setup-api';

type WizardStep = 'welcome' | 'organization' | 'administrator' | 'preferences' | 'review';

const stepForEvidence: Record<string, WizardStep> = {
  organization_configured: 'organization',
  administrator_configured: 'administrator',
  preferences_configured: 'preferences',
  complete: 'review',
};

const previousStep: Partial<Record<WizardStep, WizardStep>> = {
  organization: 'welcome',
  administrator: 'organization',
  preferences: 'administrator',
  review: 'preferences',
};

const errorMessageKeys: Record<string, string> = {
  INSTALLATION_ALREADY_COMPLETED: 'setup.errors.alreadyCompleted',
  INSTALLATION_SETUP_NOT_AUTHORIZED: 'setup.errors.invalidToken',
  INSTALLATION_SETUP_NOT_READY: 'setup.errors.notReady',
  INSTALLATION_ORGANIZATION_INVALID: 'setup.errors.organizationFailed',
  INSTALLATION_ADMINISTRATOR_INVALID: 'setup.errors.administratorFailed',
  INSTALLATION_PREFERENCES_INVALID: 'setup.errors.preferencesFailed',
  INSTALLATION_EVIDENCE_INCONSISTENT: 'setup.errors.inconsistentEvidence',
  INSTALLATION_IDENTITY_RECONCILIATION_FAILED: 'setup.errors.administratorFailed',
  INSTALLATION_COMPLETION_FAILED: 'setup.errors.completionFailed',
};

const passwordErrorMessageKeys: Record<string, string> = {
  PASSWORD_TOO_SHORT: 'setup.errors.passwordTooShort',
  PASSWORD_TOO_LONG: 'setup.errors.passwordTooLong',
  PASSWORD_CONTEXT_MATCH: 'setup.errors.passwordContext',
  PASSWORD_COMMON: 'setup.errors.passwordCommon',
};

function setupError(
  cause: unknown,
  fallback: string,
  translate: (
    key: string,
    values?: Record<string, string | number | boolean | null | undefined>,
  ) => string,
  passwordPolicy?: InstallationStatus['password_policy'],
): string {
  if (cause instanceof ApiHttpError && cause.detail && typeof cause.detail === 'object') {
    const detail = cause.detail as { code?: unknown; reason?: unknown };
    const reason = detail.reason;
    if (typeof reason === 'string' && passwordErrorMessageKeys[reason]) {
      if (reason === 'PASSWORD_TOO_SHORT' && passwordPolicy) {
        return translate(passwordErrorMessageKeys[reason], { min: passwordPolicy.min_length });
      }
      if (reason === 'PASSWORD_TOO_LONG' && passwordPolicy) {
        return translate(passwordErrorMessageKeys[reason], { max: passwordPolicy.max_length });
      }
      return translate(passwordErrorMessageKeys[reason]);
    }
    const code = detail.code;
    if (typeof code === 'string' && errorMessageKeys[code]) return translate(errorMessageKeys[code]);
    return fallback;
  }
  return fallback;
}

function passwordCharacterLength(value: string): number {
  return Array.from(value).length;
}

function passwordComparisonValue(value: string): string {
  return value.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
}

function passwordContainsContext(
  passwordValue: string,
  emailValue: string,
  contextValues: string[],
): boolean {
  const comparison = passwordComparisonValue(passwordValue);
  const emailComparison = passwordComparisonValue(emailValue);
  if (emailComparison.length >= 4 && comparison.includes(emailComparison)) return true;
  return contextValues
    .flatMap((value) => [value, ...value.normalize('NFKC').split(/[^\p{L}\p{N}]+/gu)])
    .map(passwordComparisonValue)
    .filter((value) => value.length >= 4)
    .some((value) => comparison.includes(value));
}

function suggestedSlug(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export function InstallationWizard() {
  const { locale, setLocale, t } = useI18n();
  const [token, setToken] = useState('');
  const [authorized, setAuthorized] = useState(false);
  const [status, setStatus] = useState<InstallationStatus | null>(null);
  const [step, setStep] = useState<WizardStep>('welcome');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [organizationName, setOrganizationName] = useState('');
  const [organizationSlug, setOrganizationSlug] = useState('');
  const [slugEdited, setSlugEdited] = useState(false);
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirmation, setPasswordConfirmation] = useState('');
  const [language, setLanguage] = useState(locale);
  const [timezone, setTimezone] = useState(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  );

  function updateLanguage(value: unknown) {
    setLanguage(isSupportedLocale(value) ? value : locale);
  }

  const completedSteps = status?.steps ?? {};
  const passwordPolicy = status?.password_policy;
  const passwordMinLength = passwordPolicy?.min_length;
  const passwordMaxLength = passwordPolicy?.max_length;
  const progress: Array<{ id: WizardStep; complete: boolean }> = [
    { id: 'welcome', complete: authorized },
    { id: 'organization', complete: Boolean(completedSteps.organization_configured) },
    { id: 'administrator', complete: Boolean(completedSteps.administrator_configured) },
    { id: 'preferences', complete: Boolean(completedSteps.preferences_configured) },
    { id: 'review', complete: status?.state === 'COMPLETED' },
  ];

  function goBack() {
    const destination = previousStep[step];
    if (!destination) return;
    setError(null);
    setStep(destination);
  }

  function applyStatus(nextStatus: InstallationStatus) {
    setStatus(nextStatus);
    const organization = nextStatus.details.organization_configured;
    const administrator = nextStatus.details.administrator_configured;
    const preferences = nextStatus.details.preferences_configured;
    if (organization) {
      setOrganizationName(String(organization.name ?? ''));
      setOrganizationSlug(String(organization.slug ?? ''));
      setSlugEdited(true);
    }
    if (administrator) {
      setEmail(String(administrator.email ?? ''));
      setDisplayName(String(administrator.display_name ?? ''));
    }
    if (preferences) {
      updateLanguage(preferences.language);
      setTimezone(String(preferences.timezone ?? 'UTC'));
    }
    setStep(stepForEvidence[nextStatus.next_step ?? 'complete'] ?? 'review');
  }

  async function authorize(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const nextStatus = await installationSetupApi.status(token);
      if (!nextStatus.token_authorized) {
        setError(t('setup.errors.invalidToken'));
        return;
      }
      setAuthorized(true);
      applyStatus(nextStatus);
    } catch (cause) {
      setError(setupError(cause, t('setup.errors.loadFailed'), t));
    } finally {
      setBusy(false);
    }
  }

  async function saveOrganization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      applyStatus(await installationSetupApi.organization(token, {
        name: organizationName,
        slug: organizationSlug,
      }));
    } catch (cause) {
      setError(setupError(cause, t('setup.errors.organizationFailed'), t));
    } finally {
      setBusy(false);
    }
  }

  async function saveAdministrator(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!password) {
      setError(t('setup.errors.passwordRequired'));
      return;
    }
    if (passwordMinLength !== undefined && passwordCharacterLength(password) < passwordMinLength) {
      setError(t('setup.errors.passwordTooShort', { min: passwordMinLength }));
      return;
    }
    if (passwordMaxLength !== undefined && passwordCharacterLength(password) > passwordMaxLength) {
      setError(t('setup.errors.passwordTooLong', { max: passwordMaxLength }));
      return;
    }
    if (password !== passwordConfirmation) {
      setError(t('setup.errors.passwordMismatch'));
      return;
    }
    if (passwordPolicy?.block_context && passwordContainsContext(password, email, [
      email.split('@')[0] ?? '',
      displayName,
      organizationName,
      organizationSlug,
      t('setup.product'),
    ])) {
      setError(t('setup.errors.passwordContext'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      applyStatus(await installationSetupApi.administrator(token, {
        email,
        display_name: displayName.trim() || null,
        password,
      }));
      setPassword('');
      setPasswordConfirmation('');
    } catch (cause) {
      setError(setupError(cause, t('setup.errors.administratorFailed'), t, passwordPolicy));
    } finally {
      setBusy(false);
    }
  }

  async function savePreferences(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const nextStatus = await installationSetupApi.preferences(token, { language, timezone });
      if (language === 'en' || language === 'es') setLocale(language);
      applyStatus(nextStatus);
    } catch (cause) {
      setError(setupError(cause, t('setup.errors.preferencesFailed'), t));
    } finally {
      setBusy(false);
    }
  }

  async function complete() {
    setBusy(true);
    setError(null);
    try {
      const nextStatus = await installationSetupApi.complete(token);
      setStatus(nextStatus);
      if (nextStatus.state === 'COMPLETED') window.location.assign('/login');
    } catch (cause) {
      setError(setupError(cause, t('setup.errors.completionFailed'), t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="installation-page">
      <section className="installation-wizard" aria-labelledby="setup-title">
        <header className="installation-heading">
          <span className="installation-brand">{t('setup.product')}</span>
          <h1 id="setup-title">{t('setup.title')}</h1>
          <p>{t('setup.description')}</p>
        </header>

        <section className="card installation-shell">
          <ol className="installation-progress" aria-label={t('setup.progressLabel')}>
            {progress.map((item, index) => {
              const progressState = step === item.id ? 'current' : item.complete ? 'complete' : 'pending';
              return (
                <li
                  aria-current={progressState === 'current' ? 'step' : undefined}
                  className={`is-${progressState}`}
                  key={item.id}
                >
                  <span className="installation-progress-marker" aria-hidden="true">
                    {progressState === 'complete' ? '✓' : index + 1}
                  </span>
                  <span className="installation-progress-label">{t(`setup.steps.${item.id}`)}</span>
                </li>
              );
            })}
          </ol>

          <div className="installation-step">
            {step === 'welcome' ? (
              <form className="installation-form" onSubmit={authorize}>
                <header className="installation-step-heading">
                  <h2>{t('setup.welcome.title')}</h2>
                  <p>{t('setup.welcome.description')}</p>
                </header>
                {error ? <p className="installation-alert" role="alert">{error}</p> : null}
                <div className="installation-form-fields">
                  <label className="installation-field" htmlFor="setup-token">
                    <span>{t('setup.welcome.tokenLabel')}</span>
                    <input
                      aria-describedby="setup-token-help"
                      autoComplete="one-time-code"
                      id="setup-token"
                      onChange={(event) => setToken(event.target.value)}
                      required
                      type="password"
                      value={token}
                    />
                    <small id="setup-token-help">{t('setup.welcome.tokenHelp')}</small>
                  </label>
                </div>
                <div className="installation-actions is-single">
                  <button className="button" disabled={busy || !token.trim()} type="submit">
                    {busy ? t('setup.actions.checking') : t('setup.actions.begin')}
                  </button>
                </div>
              </form>
            ) : null}

            {step === 'organization' ? (
              <form className="installation-form" onSubmit={saveOrganization}>
                <header className="installation-step-heading">
                  <h2>{t('setup.organization.title')}</h2>
                  <p>{t('setup.organization.description')}</p>
                </header>
                {error ? <p className="installation-alert" role="alert">{error}</p> : null}
                <div className="installation-form-fields">
                  <label className="installation-field" htmlFor="organization-name">
                    <span>{t('setup.organization.nameLabel')}</span>
                    <input
                      aria-describedby="organization-name-help"
                      id="organization-name"
                      maxLength={255}
                      onChange={(event) => {
                        setOrganizationName(event.target.value);
                        if (!slugEdited) setOrganizationSlug(suggestedSlug(event.target.value));
                      }}
                      required
                      value={organizationName}
                    />
                    <small id="organization-name-help">{t('setup.organization.nameHelp')}</small>
                  </label>
                  <label className="installation-field" htmlFor="organization-slug">
                    <span>{t('setup.organization.slugLabel')}</span>
                    <input
                      aria-describedby="organization-slug-help"
                      id="organization-slug"
                      maxLength={128}
                      onChange={(event) => {
                        setOrganizationSlug(event.target.value);
                        setSlugEdited(true);
                      }}
                      pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                      required
                      value={organizationSlug}
                    />
                    <small id="organization-slug-help">{t('setup.organization.slugHelp')}</small>
                  </label>
                </div>
                <div className="installation-actions">
                  <button className="button secondary" disabled={busy} onClick={goBack} type="button">
                    {t('setup.actions.back')}
                  </button>
                  <button className="button" disabled={busy} type="submit">
                    {busy ? t('setup.actions.saving') : t('setup.actions.continue')}
                  </button>
                </div>
              </form>
            ) : null}

            {step === 'administrator' ? (
              <form className="installation-form" onSubmit={saveAdministrator}>
                <header className="installation-step-heading">
                  <h2>{t('setup.administrator.title')}</h2>
                  <p>{t('setup.administrator.description')}</p>
                </header>
                {error ? <p className="installation-alert" role="alert">{error}</p> : null}
                <div className="installation-password-policy" aria-labelledby="administrator-password-policy-title">
                  <strong id="administrator-password-policy-title">
                    {t('setup.administrator.passwordPolicyTitle')}
                  </strong>
                  <ul>
                    {passwordMinLength !== undefined ? (
                      <li>{t('setup.administrator.passwordPolicyMinLength', { min: passwordMinLength })}</li>
                    ) : null}
                    <li>{t('setup.administrator.passwordPolicyPassphrase')}</li>
                    {passwordPolicy?.block_context ? (
                      <li>{t('setup.administrator.passwordPolicyContext')}</li>
                    ) : null}
                    {passwordPolicy?.block_common ? (
                      <li>{t('setup.administrator.passwordPolicyCommon')}</li>
                    ) : null}
                  </ul>
                </div>
                <div className="installation-form-fields">
                  <label className="installation-field" htmlFor="administrator-email">
                    <span>{t('setup.administrator.emailLabel')}</span>
                    <input
                      autoComplete="username"
                      id="administrator-email"
                      maxLength={320}
                      onChange={(event) => setEmail(event.target.value)}
                      required
                      type="email"
                      value={email}
                    />
                  </label>
                  <label className="installation-field" htmlFor="administrator-name">
                    <span>{t('setup.administrator.nameLabel')}</span>
                    <input
                      autoComplete="name"
                      id="administrator-name"
                      maxLength={255}
                      onChange={(event) => setDisplayName(event.target.value)}
                      value={displayName}
                    />
                  </label>
                  <label className="installation-field" htmlFor="administrator-password">
                    <span>{t('setup.administrator.passwordLabel')}</span>
                    <input
                      autoComplete="new-password"
                      id="administrator-password"
                      onChange={(event) => setPassword(event.target.value)}
                      required
                      type="password"
                      value={password}
                    />
                  </label>
                  <label className="installation-field" htmlFor="administrator-password-confirmation">
                    <span>{t('setup.administrator.confirmPasswordLabel')}</span>
                    <input
                      autoComplete="new-password"
                      id="administrator-password-confirmation"
                      onChange={(event) => setPasswordConfirmation(event.target.value)}
                      required
                      type="password"
                      value={passwordConfirmation}
                    />
                  </label>
                </div>
                <div className="installation-actions">
                  <button className="button secondary" disabled={busy} onClick={goBack} type="button">
                    {t('setup.actions.back')}
                  </button>
                  <button className="button" disabled={busy} type="submit">
                    {busy ? t('setup.actions.saving') : t('setup.actions.continue')}
                  </button>
                </div>
              </form>
            ) : null}

            {step === 'preferences' ? (
              <form className="installation-form" onSubmit={savePreferences}>
                <header className="installation-step-heading">
                  <h2>{t('setup.preferences.title')}</h2>
                  <p>{t('setup.preferences.description')}</p>
                </header>
                {error ? <p className="installation-alert" role="alert">{error}</p> : null}
                <div className="installation-form-fields">
                  <label className="installation-field" htmlFor="setup-language">
                    <span>{t('setup.preferences.languageLabel')}</span>
                    <select
                      id="setup-language"
                      onChange={(event) => updateLanguage(event.target.value)}
                      value={language}
                    >
                      {supportedLocales
                        .filter((candidate) => localeRegistry[candidate].status === 'available')
                        .map((candidate) => (
                          <option key={candidate} value={candidate}>{localeRegistry[candidate].name}</option>
                        ))}
                    </select>
                  </label>
                  <label className="installation-field" htmlFor="setup-timezone">
                    <span>{t('setup.preferences.timezoneLabel')}</span>
                    <input
                      aria-describedby="setup-timezone-help"
                      id="setup-timezone"
                      maxLength={128}
                      onChange={(event) => setTimezone(event.target.value)}
                      required
                      value={timezone}
                    />
                    <small id="setup-timezone-help">{t('setup.preferences.timezoneHelp')}</small>
                  </label>
                </div>
                <div className="installation-actions">
                  <button className="button secondary" disabled={busy} onClick={goBack} type="button">
                    {t('setup.actions.back')}
                  </button>
                  <button className="button" disabled={busy} type="submit">
                    {busy ? t('setup.actions.saving') : t('setup.actions.review')}
                  </button>
                </div>
              </form>
            ) : null}

            {step === 'review' ? (
              <div className="installation-form">
                <header className="installation-step-heading">
                  <h2>{t('setup.review.title')}</h2>
                  <p>{t('setup.review.description')}</p>
                </header>
                {error ? <p className="installation-alert" role="alert">{error}</p> : null}
                <dl className="installation-review">
                  <div>
                    <dt>{t('setup.review.organization')}</dt>
                    <dd>{organizationName} <small>{organizationSlug}</small></dd>
                  </div>
                  <div>
                    <dt>{t('setup.review.administrator')}</dt>
                    <dd>{displayName || email} <small>{email}</small></dd>
                  </div>
                  <div>
                    <dt>{t('setup.review.preferences')}</dt>
                    <dd>{localeRegistry[language].name} <small>{timezone}</small></dd>
                  </div>
                </dl>
                <p className="installation-final-note">{t('setup.review.finalNote')}</p>
                <div className="installation-actions">
                  <button className="button secondary" disabled={busy} onClick={goBack} type="button">
                    {t('setup.actions.back')}
                  </button>
                  <button
                    className="button"
                    disabled={busy || !status?.ready_to_complete}
                    onClick={() => void complete()}
                    type="button"
                  >
                    {busy ? t('setup.actions.completing') : t('setup.actions.complete')}
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </section>
      </section>
    </main>
  );
}
