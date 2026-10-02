'use client';

import { useEffect, useReducer, type FormEvent } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import type { GlobalManagedUser } from '../../lib/global-user-contract';
import {
  changedProfileFields,
  createGlobalUserEditorState,
  reduceGlobalUserEditor,
  validProfileDraft,
} from '../../lib/global-user-editor';

type ProfileChanges = { username?: string; display_name?: string; email?: string };

export function GlobalUserProfileEditor({
  pending,
  selected,
  save,
}: {
  pending: boolean;
  selected: GlobalManagedUser;
  save: (userId: string, changes: ProfileChanges) => Promise<GlobalManagedUser | null>;
}) {
  const { t } = useI18n();
  const [editor, dispatch] = useReducer(
    reduceGlobalUserEditor,
    selected,
    createGlobalUserEditorState,
  );

  useEffect(() => {
    dispatch({ type: 'authoritative', selectedUserId: selected.user_id, user: selected });
  }, [selected]);

  const draft = editor.draft;
  const changes = draft ? changedProfileFields(editor.authoritative, draft) : {};
  const changed = Object.keys(changes).length > 0;
  const valid = validProfileDraft(draft);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (editor.mode !== 'edit' || !draft || !changed || !valid) return;
    const selectedUserId = editor.selectedUserId;
    const saved = await save(selectedUserId, changes);
    if (saved) dispatch({ type: 'saved', selectedUserId, user: saved });
  };

  if (editor.mode === 'view') {
    return (
      <div data-global-user-profile-mode="view">
        <dl className="definition-list">
          <div><dt>{t('globalUsers.username')}</dt><dd>{editor.authoritative.username}</dd></div>
          <div><dt>{t('globalUsers.displayName')}</dt><dd>{editor.authoritative.display_name}</dd></div>
          <div><dt>{t('globalUsers.email')}</dt><dd>{editor.authoritative.email}</dd></div>
        </dl>
        <button className="button secondary" disabled={pending} onClick={() => dispatch({ type: 'begin_edit' })} type="button">{t('globalUsers.editProfile')}</button>
      </div>
    );
  }

  if (!draft) return null;
  return (
    <form className="access-form-grid" data-global-user-profile-mode="edit" onSubmit={(event) => void submit(event)}>
      <label className="access-form-field" htmlFor="global-user-editor-username"><span className="field-label">{t('globalUsers.username')}</span><input autoComplete="username" className="field-control" disabled={pending} id="global-user-editor-username" name="profile_username" onChange={(event) => dispatch({ type: 'edit', field: 'username', value: event.target.value })} required value={draft.username} /></label>
      <label className="access-form-field" htmlFor="global-user-editor-display-name"><span className="field-label">{t('globalUsers.displayName')}</span><input className="field-control" disabled={pending} id="global-user-editor-display-name" name="profile_display_name" onChange={(event) => dispatch({ type: 'edit', field: 'display_name', value: event.target.value })} required value={draft.display_name} /></label>
      <label className="access-form-field" htmlFor="global-user-editor-email"><span className="field-label">{t('globalUsers.email')}</span><input autoComplete="email" className="field-control" disabled={pending} id="global-user-editor-email" name="profile_email" onChange={(event) => dispatch({ type: 'edit', field: 'email', value: event.target.value })} required type="email" value={draft.email} /></label>
      <div className="access-form-actions">
        <button className="button secondary" disabled={pending} onClick={() => dispatch({ type: 'cancel' })} type="button">{t('common.actions.cancel')}</button>
        <button className="button secondary" disabled={pending || !changed || !valid} type="submit">{t('globalUsers.saveProfile')}</button>
      </div>
    </form>
  );
}
