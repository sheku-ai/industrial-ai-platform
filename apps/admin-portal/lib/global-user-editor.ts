import type { GlobalManagedUser } from './global-user-contract';

export type GlobalUserProfileDraft = {
  user_id: string;
  username: string;
  display_name: string;
  email: string;
};

export type GlobalUserEditorState = {
  mode: 'view' | 'edit';
  selectedUserId: string;
  authoritative: GlobalManagedUser & { display_name: string };
  draft: GlobalUserProfileDraft | null;
  dirty: boolean;
};

type CandidateUser = Partial<GlobalManagedUser> & { user_id: string };
type CompleteEditorUser = GlobalManagedUser & { display_name: string };

export type GlobalUserEditorAction =
  | { type: 'select'; user: CandidateUser }
  | { type: 'authoritative'; selectedUserId: string; user: CandidateUser }
  | { type: 'saved'; selectedUserId: string; user: CandidateUser }
  | { type: 'begin_edit' }
  | { type: 'cancel' }
  | { type: 'edit'; field: 'username' | 'display_name' | 'email'; value: string };

function completeIdentity(user: CandidateUser): user is CompleteEditorUser {
  return Boolean(
    typeof user.username === 'string'
    && user.username.trim()
    && typeof user.display_name === 'string'
    && user.display_name.trim()
    && typeof user.email === 'string'
    && user.email.trim(),
  );
}

export function createGlobalUserDraft(user: CandidateUser): GlobalUserProfileDraft {
  if (!completeIdentity(user)) throw new Error('global_identity_editor_requires_complete_user');
  return {
    user_id: user.user_id,
    username: user.username,
    display_name: user.display_name,
    email: user.email,
  };
}

export function createGlobalUserEditorState(user: CandidateUser): GlobalUserEditorState {
  if (!completeIdentity(user)) throw new Error('global_identity_editor_requires_complete_user');
  return {
    mode: 'view',
    selectedUserId: user.user_id,
    authoritative: user,
    draft: null,
    dirty: false,
  };
}

export function reduceGlobalUserEditor(
  state: GlobalUserEditorState,
  action: GlobalUserEditorAction,
): GlobalUserEditorState {
  if (action.type === 'edit') {
    if (state.mode !== 'edit' || !state.draft) return state;
    return { ...state, draft: { ...state.draft, [action.field]: action.value }, dirty: true };
  }
  if (action.type === 'select') {
    if (!completeIdentity(action.user)) return state;
    return createGlobalUserEditorState(action.user);
  }
  if (action.type === 'begin_edit') {
    return { ...state, mode: 'edit', draft: createGlobalUserDraft(state.authoritative), dirty: false };
  }
  if (action.type === 'cancel') {
    return { ...state, mode: 'view', draft: null, dirty: false };
  }
  if (
    action.selectedUserId !== state.selectedUserId
    || action.user.user_id !== state.selectedUserId
    || !completeIdentity(action.user)
  ) return state;
  if (action.type === 'saved') return createGlobalUserEditorState(action.user);
  return {
    ...state,
    authoritative: action.user,
    draft: state.mode === 'view' ? null : state.draft,
  };
}

export function globalUserFormMountState(creationOpen: boolean, editorMode: 'view' | 'edit') {
  return {
    creationForm: creationOpen,
    profileEditForm: !creationOpen && editorMode === 'edit',
  };
}

export function validProfileDraft(draft: GlobalUserProfileDraft | null): boolean {
  if (!draft) return false;
  const email = draft.email.trim();
  return Boolean(draft.username.trim() && draft.display_name.trim() && email.includes('@'));
}

export function changedProfileFields(
  user: GlobalManagedUser,
  draft: GlobalUserProfileDraft,
): { username?: string; display_name?: string; email?: string } {
  const changes: { username?: string; display_name?: string; email?: string } = {};
  const username = draft.username.trim();
  const displayName = draft.display_name.trim();
  const email = draft.email.trim();
  if (username !== user.username) changes.username = username;
  if (displayName !== (user.display_name ?? '')) changes.display_name = displayName;
  if (email !== user.email) changes.email = email;
  return changes;
}
