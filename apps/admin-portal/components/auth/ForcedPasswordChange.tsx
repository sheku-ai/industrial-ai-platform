'use client';

import { useState, type FormEvent } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import { localizedApiError } from '../../lib/presentation';
import { useAuth } from './AuthContext';

export function ForcedPasswordChange() {
  const { t } = useI18n();
  const { changePassword, logout } = useAuth();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    if (newPassword !== confirmation) {
      setError(t('auth.passwordConfirmationMismatch'));
      return;
    }
    setPending(true);
    setError(null);
    try {
      await changePassword(currentPassword, newPassword);
    } catch (cause) {
      setError(localizedApiError(cause, t, 'auth.passwordChangeFailed'));
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="login-page" id="main-content">
      <section className="card auth-state-card">
        <h1>{t('auth.passwordChangeRequired')}</h1>
        <p>{t('auth.passwordChangeRequiredHelp')}</p>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <form className="login-form" onSubmit={(event) => void submit(event)}>
          <label><span className="field-label">{t('auth.currentPassword')}</span><input autoComplete="current-password" className="field-control" disabled={pending} onChange={(event) => setCurrentPassword(event.target.value)} required type="password" value={currentPassword} /></label>
          <label><span className="field-label">{t('auth.newPassword')}</span><input autoComplete="new-password" className="field-control" disabled={pending} onChange={(event) => setNewPassword(event.target.value)} required type="password" value={newPassword} /></label>
          <label><span className="field-label">{t('auth.confirmPassword')}</span><input autoComplete="new-password" className="field-control" disabled={pending} onChange={(event) => setConfirmation(event.target.value)} required type="password" value={confirmation} /></label>
          <button className="button primary" disabled={pending} type="submit">{t(pending ? 'auth.changingPassword' : 'auth.changePassword')}</button>
          <button className="button secondary" disabled={pending} onClick={() => void logout()} type="button">{t('auth.signOut')}</button>
        </form>
      </section>
    </main>
  );
}
