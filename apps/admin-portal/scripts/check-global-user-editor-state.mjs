import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import ts from 'typescript';

async function importTypeScriptModule(relativePath) {
  const sourceUrl = new URL(relativePath, import.meta.url);
  const source = await readFile(sourceUrl, 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: sourceUrl.pathname,
  }).outputText;
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`;
  return import(moduleUrl);
}

const {
  changedProfileFields,
  createGlobalUserEditorState,
  globalUserFormMountState,
  reduceGlobalUserEditor,
  validProfileDraft,
} = await importTypeScriptModule('../lib/global-user-editor.ts');
const {
  normalizeGlobalManagedUser,
  normalizeGlobalUserMutation,
} = await importTypeScriptModule('../lib/global-user-contract.ts');

const user = (values) => ({
  status: 'active',
  must_change_password: false,
  active_sessions: 1,
  global_roles: [],
  memberships: [],
  ...values,
});
const primaryUser = user({
  user_id: 'primary-user-id',
  username: 'primary.operator',
  display_name: 'Primary Operator',
  email: 'primary.operator@example.test',
});
const usertest = user({
  user_id: 'usertest-id',
  username: 'test0101',
  display_name: 'usertest',
  email: 'test0101@example.test',
});

let state = createGlobalUserEditorState(primaryUser);
assert.equal(state.mode, 'view');
assert.equal(state.draft, null);
assert.equal(state.dirty, false);

const viewState = state;
state = reduceGlobalUserEditor(state, { type: 'edit', field: 'username', value: '' });
assert.strictEqual(state, viewState);

state = reduceGlobalUserEditor(state, { type: 'begin_edit' });
assert.equal(state.mode, 'edit');
assert.deepEqual(state.draft, {
  user_id: 'primary-user-id',
  username: 'primary.operator',
  display_name: 'Primary Operator',
  email: 'primary.operator@example.test',
});
assert.equal(state.dirty, false);
assert.deepEqual(changedProfileFields(primaryUser, state.draft), {});

state = reduceGlobalUserEditor(state, { type: 'edit', field: 'username', value: 'changed' });
state = reduceGlobalUserEditor(state, { type: 'edit', field: 'display_name', value: 'changed' });
state = reduceGlobalUserEditor(state, { type: 'edit', field: 'email', value: 'changed@example.test' });
state = reduceGlobalUserEditor(state, { type: 'cancel' });
assert.equal(state.mode, 'view');
assert.equal(state.draft, null);
state = reduceGlobalUserEditor(state, { type: 'begin_edit' });
assert.equal(state.draft.username, 'primary.operator');
assert.equal(state.draft.display_name, 'Primary Operator');
assert.equal(state.draft.email, 'primary.operator@example.test');

state = reduceGlobalUserEditor(state, { type: 'select', user: usertest });
assert.equal(state.mode, 'view');
assert.equal(state.draft, null);
state = reduceGlobalUserEditor(state, { type: 'begin_edit' });
assert.deepEqual(state.draft, {
  user_id: 'usertest-id',
  username: 'test0101',
  display_name: 'usertest',
  email: 'test0101@example.test',
});

state = reduceGlobalUserEditor(state, { type: 'select', user: primaryUser });
state = reduceGlobalUserEditor(state, { type: 'begin_edit' });
assert.equal(state.draft.username, 'primary.operator');
assert.equal(state.draft.display_name, 'Primary Operator');
assert.equal(state.draft.email, 'primary.operator@example.test');

const completeState = state;
state = reduceGlobalUserEditor(state, {
  type: 'authoritative',
  selectedUserId: 'primary-user-id',
  user: { user_id: 'primary-user-id', display_name: 'Primary Operator' },
});
assert.strictEqual(state, completeState);

state = reduceGlobalUserEditor(state, {
  type: 'authoritative',
  selectedUserId: 'usertest-id',
  user: usertest,
});
assert.strictEqual(state, completeState);

state = reduceGlobalUserEditor(state, {
  type: 'saved',
  selectedUserId: 'usertest-id',
  user: usertest,
});
assert.strictEqual(state, completeState);

const savedPrimaryUser = { ...primaryUser, display_name: 'Primary Operator Updated' };
state = reduceGlobalUserEditor(state, {
  type: 'saved',
  selectedUserId: 'primary-user-id',
  user: savedPrimaryUser,
});
assert.equal(state.mode, 'view');
assert.equal(state.draft, null);
assert.equal(state.authoritative.display_name, 'Primary Operator Updated');

state = reduceGlobalUserEditor(state, { type: 'begin_edit' });
state = reduceGlobalUserEditor(state, { type: 'edit', field: 'username', value: '' });
assert.equal(state.dirty, true);
assert.equal(validProfileDraft(state.draft), false);
state = reduceGlobalUserEditor(createGlobalUserEditorState(primaryUser), { type: 'begin_edit' });
state = reduceGlobalUserEditor(state, {
  type: 'edit',
  field: 'email',
  value: '',
});
assert.equal(validProfileDraft(state.draft), false);

const normalizedCreate = normalizeGlobalUserMutation({ operation: 'create', outcome: 'created', user: primaryUser });
const normalizedUpdate = normalizeGlobalUserMutation({ operation: 'update', outcome: 'updated', user: usertest });
assert.equal(normalizedCreate.user.username, 'primary.operator');
assert.equal(normalizedCreate.user.email, 'primary.operator@example.test');
assert.equal(normalizedUpdate.user.username, 'test0101');
assert.equal(normalizedUpdate.user.email, 'test0101@example.test');
assert.throws(() => normalizeGlobalManagedUser({ ...primaryUser, username: '' }), /missing username/);
assert.throws(() => normalizeGlobalManagedUser({ ...primaryUser, email: '' }), /missing email/);

assert.deepEqual(globalUserFormMountState(false, 'view'), { creationForm: false, profileEditForm: false });
assert.deepEqual(globalUserFormMountState(false, 'edit'), { creationForm: false, profileEditForm: true });
assert.deepEqual(globalUserFormMountState(true, 'view'), { creationForm: true, profileEditForm: false });
assert.deepEqual(globalUserFormMountState(true, 'edit'), { creationForm: true, profileEditForm: false });

console.log(JSON.stringify({
  authoritative_hydration: true,
  explicit_edit_mode: true,
  edit_outside_edit_mode_ignored: true,
  identity_switch_replaces_all_fields: true,
  return_to_identity_restores_all_fields: true,
  cancel_restores_all_fields: true,
  partial_response_preserves_complete_draft: true,
  stale_response_ignored: true,
  stale_save_ignored: true,
  matching_save_returns_to_view: true,
  unchanged_state_is_clean: true,
  empty_username_or_email_is_invalid: true,
  mutation_users_are_normalized: true,
  creation_and_edit_forms_are_mutually_exclusive: true,
  passed: true,
}, null, 2));
