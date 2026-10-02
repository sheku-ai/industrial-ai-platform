import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const portalRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const catalogRoot = resolve(portalRoot, 'i18n');
const configPath = resolve(catalogRoot, 'config.ts');
const catalogLoaderPath = resolve(catalogRoot, 'catalogs.ts');
const backendLocalePath = resolve(portalRoot, '..', 'api', 'app', 'services', 'assistant_locale.py');
const hashBaselinePath = resolve(portalRoot, 'scripts', 'i18n-hash-key-baseline.v1.json');
const pluralCategories = new Set(['zero', 'one', 'two', 'few', 'many', 'other']);

function parseCatalog(source, filename) {
  let offset = 0;
  const duplicates = [];
  const skip = () => { while (/\s/.test(source[offset] ?? '')) offset += 1; };
  const string = () => {
    const start = offset++;
    while (offset < source.length) {
      if (source[offset] === '\\') offset += 2;
      else if (source[offset++] === '"') break;
    }
    return JSON.parse(source.slice(start, offset));
  };
  const value = (path = '') => {
    skip();
    if (source[offset] === '{') {
      offset += 1;
      const keys = new Set();
      skip();
      while (source[offset] !== '}') {
        const key = string();
        if (keys.has(key)) duplicates.push(path ? `${path}.${key}` : key);
        keys.add(key);
        skip();
        if (source[offset++] !== ':') throw new Error(`${filename}: expected ':' at ${offset}`);
        value(path ? `${path}.${key}` : key);
        skip();
        if (source[offset] === ',') { offset += 1; skip(); }
        else if (source[offset] !== '}') throw new Error(`${filename}: expected ',' or '}' at ${offset}`);
      }
      offset += 1;
      return;
    }
    if (source[offset] === '[') {
      offset += 1;
      skip();
      while (source[offset] !== ']') {
        value(path);
        skip();
        if (source[offset] === ',') { offset += 1; skip(); }
        else if (source[offset] !== ']') throw new Error(`${filename}: invalid array at ${offset}`);
      }
      offset += 1;
      return;
    }
    if (source[offset] === '"') { string(); return; }
    while (offset < source.length && !/[\s,}\]]/.test(source[offset])) offset += 1;
  };
  value();
  if (duplicates.length) throw new Error(`${filename}: duplicate keys: ${duplicates.join(', ')}`);
  return JSON.parse(source);
}

function analyzeCatalog(value, locale, prefix = '', analysis = {
  failures: [],
  leaves: new Map(),
  pluralFamilies: new Map(),
}, options = { allowPartialPlurals: false }) {
  if (typeof value === 'string') {
    analysis.leaves.set(prefix, value);
    return analysis;
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    analysis.failures.push(`${locale}: ${prefix || 'catalog'} must be a message or mapping`);
    return analysis;
  }

  const keys = Object.keys(value);
  if (keys.length === 0) {
    analysis.failures.push(`${locale}: ${prefix || 'catalog'} must not be an empty mapping`);
    return analysis;
  }
  const pluralKeys = keys.filter((key) => pluralCategories.has(key));
  if (pluralKeys.length) {
    const invalidCategories = keys.filter((key) => !pluralCategories.has(key));
    if (invalidCategories.length) {
      analysis.failures.push(`${locale}: plural family ${prefix} has invalid categories: ${invalidCategories.join(', ')}`);
    }
    if (!options.allowPartialPlurals && typeof value.other !== 'string') {
      analysis.failures.push(`${locale}: plural family ${prefix} has orphan variants without required other`);
    }
    for (const category of pluralKeys) {
      if (typeof value[category] !== 'string') {
        analysis.failures.push(`${locale}: plural variant ${prefix}.${category} must be a string`);
      } else {
        analysis.leaves.set(`${prefix}.${category}`, value[category]);
      }
    }
    analysis.pluralFamilies.set(prefix, new Set(pluralKeys));
    return analysis;
  }

  for (const [key, child] of Object.entries(value)) {
    analyzeCatalog(child, locale, prefix ? `${prefix}.${key}` : key, analysis, options);
  }
  return analysis;
}

function isMapping(value) {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function isPluralMessage(value) {
  if (!isMapping(value)) return false;
  const keys = Object.keys(value);
  return keys.length > 0 && keys.every((key) => pluralCategories.has(key));
}

function composeCatalog(base, localized) {
  const effective = { ...base };
  for (const [key, localizedValue] of Object.entries(localized)) {
    const baseValue = base[key];
    if (isMapping(baseValue) && isMapping(localizedValue) && !isPluralMessage(baseValue) && !isPluralMessage(localizedValue)) {
      effective[key] = composeCatalog(baseValue, localizedValue);
    } else if (isMapping(baseValue) && isMapping(localizedValue) && isPluralMessage(baseValue)) {
      effective[key] = { ...baseValue, ...localizedValue };
    } else {
      effective[key] = localizedValue;
    }
  }
  return effective;
}

function placeholders(value) {
  return [...value.matchAll(/\{([a-zA-Z0-9_]+)\}/g)].map((match) => match[1]).sort().join(',');
}

function parseLocaleRegistry(source) {
  const entries = [];
  const pattern = /^\s*(?:'([^']+)'|([a-zA-Z][a-zA-Z0-9-]*)):\s*\{\s*code:\s*'([^']+)',\s*name:\s*'([^']+)',\s*direction:\s*'([^']+)',\s*status:\s*'([^']+)',\s*loader:\s*catalog\(\(\)\s*=>\s*import\('\.\/([^']+)\.json'\)\)\s*\},?$/gm;
  for (const match of source.matchAll(pattern)) {
    entries.push({
      registryKey: match[1] ?? match[2],
      code: match[3],
      name: match[4],
      direction: match[5],
      status: match[6],
      loader: match[7],
    });
  }
  return entries;
}

function parsePythonSet(source, name) {
  const match = source.match(new RegExp(`${name}\\s*=\\s*\\{([\\s\\S]*?)\\}`));
  return match ? [...match[1].matchAll(/"([^"]+)"/g)].map((item) => item[1]) : [];
}

function parsePythonMappingKeys(source, name) {
  const match = source.match(new RegExp(`${name}\\s*=\\s*\\{([\\s\\S]*?)\\n\\}`));
  return match ? [...match[1].matchAll(/^[ \t]*"([^"]+)":/gm)].map((item) => item[1]) : [];
}

function compareSets(label, expected, actual, failures) {
  const missing = [...expected].filter((value) => !actual.has(value));
  const extra = [...actual].filter((value) => !expected.has(value));
  if (missing.length || extra.length) {
    failures.push(`${label}. Missing: ${missing.join(', ') || 'none'}; extra: ${extra.join(', ') || 'none'}`);
  }
}

const structuralFailures = [];
const configSource = readFileSync(configPath, 'utf8');
const catalogLoaderSource = readFileSync(catalogLoaderPath, 'utf8');
const registryEntries = parseLocaleRegistry(configSource);
const registryCodes = registryEntries.map((entry) => entry.code);
const registryCodeSet = new Set(registryCodes);
if (registryEntries.length !== 20) structuralFailures.push(`Frontend locale registry must contain 20 entries; found ${registryEntries.length}`);
if (registryCodeSet.size !== registryEntries.length) structuralFailures.push('Frontend locale registry contains duplicate codes');

for (const entry of registryEntries) {
  if (entry.registryKey !== entry.code) structuralFailures.push(`Registry key ${entry.registryKey} does not match code ${entry.code}`);
  if (entry.loader !== entry.code) structuralFailures.push(`${entry.code}: loader points to ${entry.loader}.json`);
  if (!['ltr', 'rtl'].includes(entry.direction)) structuralFailures.push(`${entry.code}: invalid direction ${entry.direction}`);
  if (!['available', 'preview'].includes(entry.status)) structuralFailures.push(`${entry.code}: invalid status ${entry.status}`);
}

const englishDefinition = registryEntries.find((entry) => entry.code === 'en');
if (!englishDefinition) structuralFailures.push('Frontend locale registry must define en');
else if (englishDefinition.status !== 'available') structuralFailures.push('English locale must be available');
const spanishDefinition = registryEntries.find((entry) => entry.code === 'es');
if (!spanishDefinition) structuralFailures.push('Frontend locale registry must define es');
else if (spanishDefinition.status !== 'available') structuralFailures.push('Spanish locale must remain available');
if (!registryEntries.some((entry) => entry.status === 'preview')) structuralFailures.push('Frontend locale registry must identify preview locales explicitly');
if (!configSource.includes("localeRegistry[locale].status === 'preview'")) {
  structuralFailures.push('Preview fallback policy must be derived explicitly from locale status');
}
if (!catalogLoaderSource.includes('composeCatalog(english, localized)')) {
  structuralFailures.push('Catalog loader must compose preview translations with the English base catalog');
}
const defaultLocaleMatch = configSource.match(/export const defaultLocale:\s*SupportedLocale\s*=\s*'([^']+)'/);
if (defaultLocaleMatch?.[1] !== 'en') structuralFailures.push('English must remain the default fallback locale');

const catalogFiles = readdirSync(catalogRoot).filter((name) => name.endsWith('.json')).sort();
const catalogCodes = catalogFiles.map((name) => name.slice(0, -5));
compareSets('Catalogs must exactly match the frontend registry', registryCodeSet, new Set(catalogCodes), structuralFailures);

const parsedCatalogs = Object.fromEntries(catalogFiles.map((name) => {
  const source = readFileSync(resolve(catalogRoot, name), 'utf8');
  return [name.slice(0, -5), parseCatalog(source, name)];
}));
const definitionsByCode = new Map(registryEntries.map((entry) => [entry.code, entry]));
const analyses = Object.fromEntries(Object.entries(parsedCatalogs).map(([locale, catalog]) => {
  const analysis = analyzeCatalog(
    catalog,
    locale,
    '',
    undefined,
    { allowPartialPlurals: definitionsByCode.get(locale)?.status === 'preview' },
  );
  structuralFailures.push(...analysis.failures);
  return [locale, analysis];
}));
const reference = analyses.en?.leaves ?? new Map();
const knownHistoricalEnglishPreviewValues = new Set([
  'This capability requires a platform-level permission assigned by a platform administrator.',
  'Review integration capabilities, configured connections and the APIs that support them.',
  'Find documents and answers in the governed knowledge of your active organization.',
  'Loading document types from API…',
  'Loading workers…',
  'Loading worker summary…',
  'Loading platform API state…',
  'Loading execution runtime…',
  'Email delivery is not configured. Adding an identity does not send an invitation email or create credentials.',
  'The identity and organization membership were persisted.',
]);
const effectiveAnalyses = {};

for (const locale of registryCodes) {
  const analysis = analyses[locale];
  if (!analysis) continue;
  const definition = definitionsByCode.get(locale);
  const isPreview = definition?.status === 'preview';
  for (const key of analysis.leaves.keys()) {
    if (!reference.has(key)) structuralFailures.push(`${locale}: unexpected ${key}`);
    else if (!analysis.leaves.get(key)?.trim()) structuralFailures.push(`${locale}: empty ${key}`);
    else if (placeholders(analysis.leaves.get(key)) !== placeholders(reference.get(key))) {
      structuralFailures.push(`${locale}: incompatible placeholders for ${key}`);
    } else if (isPreview && analysis.leaves.get(key) === reference.get(key)) {
      structuralFailures.push(`${locale}: ${key} duplicates English and must be omitted to use explicit fallback`);
    } else if (isPreview && knownHistoricalEnglishPreviewValues.has(analysis.leaves.get(key))) {
      structuralFailures.push(`${locale}: ${key} duplicates a known historical English value and must be omitted to use explicit fallback`);
    }
  }
  for (const family of analysis.pluralFamilies.keys()) {
    if (!analyses.en.pluralFamilies.has(family)) structuralFailures.push(`${locale}: unexpected plural family ${family}`);
  }

  const effectiveCatalog = isPreview ? composeCatalog(parsedCatalogs.en, parsedCatalogs[locale]) : parsedCatalogs[locale];
  const effectiveAnalysis = analyzeCatalog(effectiveCatalog, `${locale} effective`);
  effectiveAnalyses[locale] = effectiveAnalysis;
  structuralFailures.push(...effectiveAnalysis.failures);
  for (const [key, englishValue] of reference) {
    const value = effectiveAnalysis.leaves.get(key);
    if (value === undefined) structuralFailures.push(`${locale} effective: missing ${key}`);
    else if (!value.trim()) structuralFailures.push(`${locale} effective: empty ${key}`);
    else if (placeholders(value) !== placeholders(englishValue)) {
      structuralFailures.push(`${locale} effective: incompatible placeholders for ${key}`);
    }
  }
  for (const key of effectiveAnalysis.leaves.keys()) {
    if (!reference.has(key)) structuralFailures.push(`${locale} effective: unexpected ${key}`);
  }
  for (const [family, referenceCategories] of analyses.en.pluralFamilies) {
    const categories = effectiveAnalysis.pluralFamilies.get(family);
    if (!categories) structuralFailures.push(`${locale} effective: missing plural family ${family}`);
    else compareSets(`${locale} effective: plural categories for ${family}`, referenceCategories, categories, structuralFailures);
  }
  for (const family of effectiveAnalysis.pluralFamilies.keys()) {
    if (!analyses.en.pluralFamilies.has(family)) structuralFailures.push(`${locale} effective: unexpected plural family ${family}`);
  }
}

const backendSource = readFileSync(backendLocalePath, 'utf8');
const backendCodes = parsePythonSet(backendSource, 'SUPPORTED_ASSISTANT_LOCALES');
const backendRtlCodes = parsePythonSet(backendSource, 'RTL_ASSISTANT_LOCALES');
if (new Set(backendCodes).size !== backendCodes.length) structuralFailures.push('Backend assistant locale registry contains duplicate codes');
compareSets('Backend assistant locales must match the frontend registry', registryCodeSet, new Set(backendCodes), structuralFailures);
const frontendRtlCodes = new Set(registryEntries.filter((entry) => entry.direction === 'rtl').map((entry) => entry.code));
compareSets('Backend RTL locales must match the frontend registry', frontendRtlCodes, new Set(backendRtlCodes), structuralFailures);
compareSets(
  'Backend no-evidence messages must match supported locales',
  registryCodeSet,
  new Set(parsePythonMappingKeys(backendSource, 'NO_EVIDENCE_MESSAGES')),
  structuralFailures,
);
compareSets(
  'Backend grounded-response templates must match supported locales',
  registryCodeSet,
  new Set(parsePythonMappingKeys(backendSource, 'GROUNDED_RESPONSE_TEMPLATES')),
  structuralFailures,
);

const baseline = JSON.parse(readFileSync(hashBaselinePath, 'utf8'));
if (baseline.version !== 1 || !Array.isArray(baseline.keys)) structuralFailures.push('Legacy hash-key baseline must use version 1 and contain a keys array');
const baselineKeys = new Set(baseline.keys ?? []);
if (baselineKeys.size !== (baseline.keys ?? []).length) structuralFailures.push('Legacy hash-key baseline contains duplicate keys');
const hashPattern = /^copy\.[a-z0-9_]+_[0-9a-f]{8}$/;
const currentHashKeys = new Set([...reference.keys()].filter((key) => hashPattern.test(key)));
compareSets('Legacy copy hash-key baseline changed', baselineKeys, currentHashKeys, structuralFailures);
const unbaselinedHashes = [...reference.keys()].filter((key) => /_[0-9a-f]{8}$/.test(key) && !baselineKeys.has(key));
if (unbaselinedHashes.length) structuralFailures.push(`New hash-style keys are forbidden: ${unbaselinedHashes.join(', ')}`);

if (structuralFailures.length) {
  throw new Error(`Catalog structural validation failed:\n${structuralFailures.join('\n')}`);
}

const intentionalEnglish = new Map([
  ['*|navigation.productLabel', ['proper_name', 'Registered product name.']],
  ['*|dynamic.aiStudio', ['proper_name', 'Product workspace name.']],
  ['*|copy.linux_83ad8510', ['proper_name', 'Operating system name.']],
  ['*|copy.darwin_695c30da', ['proper_name', 'Operating system name.']],
  ['*|copy.windows_26d9c28d', ['proper_name', 'Operating system name.']],
  ['*|copy.amd64_0a40ab6d', ['acronym', 'Processor architecture identifier.']],
  ['*|copy.arm64_bb16ce02', ['acronym', 'Processor architecture identifier.']],
  ['*|copy.postgresql_24fd6c2d', ['proper_name', 'Database product name.']],
  ['*|copy.sbom_bc385b71', ['acronym', 'International software bill of materials acronym.']],
  ['*|copy.qdrant_388a01a6', ['proper_name', 'Vector database product name.']],
  ['es|common.no', ['contextual_translation', 'Spanish “No” is identical to English.']],
  ['es|aiConfig.capabilityChat', ['international_technical_term', 'Chat is established Spanish AI terminology.']],
  ['es|aiConfig.capabilityEmbeddings', ['international_technical_term', 'Embeddings is established Spanish AI terminology.']],
  ['es|aiConfig.capabilityMultimodal', ['contextual_translation', 'Spanish “Multimodal” is identical to English.']],
  ['es|governanceUx.summary.feedback', ['international_technical_term', 'Feedback is established Spanish product terminology.']],
  ['es|aiSurface.domains.guardrails', ['international_technical_term', 'Guardrails is retained as an AI governance term.']],
  ['es|aiSurface.domains.prompts', ['international_technical_term', 'Prompts is established Spanish AI terminology.']],
  ['es|structureWorkspace.nodeAccessibleLabel', ['contextual_translation', 'This accessible label consists only of localized placeholders.']],
  ['es|copy.prompts_eea5311d', ['international_technical_term', 'Prompt is established Spanish AI terminology.']],
  ['es|copy.prompt_a817d7eb', ['international_technical_term', 'Prompt is established Spanish AI terminology.']],
  ['es|copy.actor_cbd19b5c', ['contextual_translation', 'Spanish “Actor” is identical to English.']],
  ['es|copy.chunks_4a527377', ['international_technical_term', 'Chunk is retained in this technical surface.']],
  ['es|copy.runtime_c4740e4c', ['international_technical_term', 'Runtime is retained in this technical API surface.']],
  ['es|copy.chat_2ced57f1', ['international_technical_term', 'Chat is established Spanish software terminology.']],
  ['es|copy.error_7f2f6a15', ['contextual_translation', 'Spanish “Error” is identical to English.']],
  ['es|copy.worker_99edd8c8', ['international_technical_term', 'Worker identifies a technical background process.']],
  ['es|copy.heartbeat_eb4d4196', ['international_technical_term', 'Heartbeat is retained as a technical runtime signal.']],
  ['es|copy.total_b25928c6', ['contextual_translation', 'Spanish “Total” is identical to English.']],
  ['es|copy.product_acceptance_0826d08b', ['proper_name', 'Protected Product Acceptance capability name.']],
  ['es|copy.heartbeats_33ed2d61', ['international_technical_term', 'Heartbeats identifies technical runtime signals.']],
  ['es|copy.community_bfd58ee3', ['proper_name', 'Product edition name.']],
  ['es|copy.enterprise_b4afff31', ['proper_name', 'Product edition name.']],
  ['es|copy.redis_24071b57', ['proper_name', 'Data store product name.']],
  ['es|copy.id_d789a1e9', ['acronym', 'International identifier acronym.']],
  ['es|copy.error_787aa161', ['contextual_translation', 'Spanish “Error” is identical to English.']],
  ['es|copy.forbid_overlap_6507cb8f', ['international_technical_term', 'Persisted scheduler enum value.']],
  ['es|copy.allow_bounded_218400b1', ['international_technical_term', 'Persisted scheduler enum value.']],
  ['es|copy.replace_pending_430ac6df', ['international_technical_term', 'Persisted scheduler enum value.']],
  ['es|copy.skip_c7e16815', ['international_technical_term', 'Persisted scheduler enum value.']],
  ['es|copy.run_once_f8ed5ce7', ['international_technical_term', 'Persisted scheduler enum value.']],
  ['es|copy.catch_up_bounded_ab9ade87', ['international_technical_term', 'Persisted scheduler enum value.']],
  ['es|copy.principal_f3b86b13', ['contextual_translation', 'Spanish security term “Principal” is identical to English.']],
  ['es|copy.roles_47dcc27d', ['contextual_translation', 'Spanish “Roles” is identical to English.']],
  ['es|copy.gate_5701b5f6', ['international_technical_term', 'Gate is retained as a governed acceptance concept.']],
  ['es|copy.document_ingestion_e8ae0a8a', ['international_technical_term', 'Persisted event type identifier.']],
  ['es|copy.platform_operation_13a7d443', ['international_technical_term', 'Persisted event type identifier.']],
  ['es|copy.no_fd128635', ['contextual_translation', 'Spanish lowercase “no” is identical to English.']],
  ['es|copy.embeddings_f428bd5b', ['international_technical_term', 'Embeddings is established Spanish AI terminology.']],
  ['es|copy.ask_messageplaceholder_69aaa337', ['international_technical_term', 'Message catalog key shown as technical evidence.']],
  ['es|copy.dynamic_searchaccessrequired_2147dc58', ['international_technical_term', 'Message catalog key shown as technical evidence.']],
  ['es|copy.dynamic_documentadministrationrequired_2902ea0a', ['international_technical_term', 'Message catalog key shown as technical evidence.']],
  ['es|copy.dynamic_accessevaluating_88721262', ['international_technical_term', 'Message catalog key shown as technical evidence.']],
  ['es|copy.dynamic_assistantaccessunavailable_fa1966c9', ['international_technical_term', 'Message catalog key shown as technical evidence.']],
  ['es|copy.endpoints_b71c5271', ['international_technical_term', 'Endpoint is established Spanish API terminology.']],
  ['es|copy.openapi_acb3d9a7', ['proper_name', 'API specification name.']],
  ['es|copy.workers_b6ef3acd', ['international_technical_term', 'Workers identifies technical background processes.']],
  ['es|copy.pipelines_c5df1e14', ['international_technical_term', 'Pipelines is established Spanish data-platform terminology.']],
  ['es|copy.production_acceptance_foundation_4e0a9a13', ['proper_name', 'Protected Production Acceptance capability name.']],
  ['es|copy.operational_acceptance_dc1bd1ab', ['proper_name', 'Protected Operational Acceptance capability name.']],
  ['es|copy.not_evaluated_a081a2c7', ['international_technical_term', 'Persisted Product Acceptance status value.']],
  ['es|copy.configuration_preflight_3fe9a1bb', ['proper_name', 'Protected Product Acceptance contract name.']],
  ['es|copy.recovery_evidence_runtime_5453e054', ['proper_name', 'Protected Product Acceptance runtime name.']],
  ['es|copy.backup_evidence_bb7e1f43', ['proper_name', 'Protected Product Acceptance evidence name.']],
  ['es|copy.restore_and_verification_381f3bd4', ['proper_name', 'Protected Product Acceptance workflow name.']],
  ['es|copy.production_gate_matrix_4f701292', ['proper_name', 'Protected Product Acceptance matrix name.']],
  ['es|copy.domain_readiness_4f5c88b6', ['proper_name', 'Protected Product Acceptance classification name.']],
  ['es|copy.not_applicable_79acc720', ['international_technical_term', 'Persisted Product Acceptance applicability value.']],
  ['es|dynamic.slug', ['international_technical_term', 'Slug is established Spanish web-platform terminology.']],
  ['es|dynamic.general', ['contextual_translation', 'Spanish “General” is identical to English.']],
  ['pt|common.status', ['contextual_translation', 'Portuguese technical UI term is conventionally “Status”.']],
  ['de|common.status', ['international_technical_term', 'German enterprise software conventionally uses “Status”.']],
  ['de|common.name', ['contextual_translation', 'German “Name” is identical to English.']],
  ['de|common.code', ['international_technical_term', 'German enterprise software conventionally uses “Code”.']],
  ['de|navigation.administration', ['contextual_translation', 'German “Administration” is identical to English.']],
  ['de|navigation.governance', ['international_technical_term', 'Governance is established German enterprise terminology.']],
  ['de|pages.ai.section', ['contextual_translation', 'German “Administration” is identical to English.']],
  ['de|pages.governance.title', ['international_technical_term', 'Governance is established German enterprise terminology.']],
  ['de|pages.organization.section', ['contextual_translation', 'German “Administration” is identical to English.']],
  ['de|pages.security.section', ['contextual_translation', 'German “Administration” is identical to English.']],
  ['de|ask.assistant', ['international_technical_term', 'Assistant is an established German software term.']],
  ['fr|common.actionColumn', ['contextual_translation', 'French “Actions” is identical to English.']],
  ['fr|common.type', ['contextual_translation', 'French “Type” is identical to English.']],
  ['fr|common.code', ['contextual_translation', 'French “Code” is identical to English.']],
  ['fr|common.description', ['contextual_translation', 'French “Description” is identical to English.']],
  ['fr|formats.durationMinutes.one', ['contextual_translation', 'French singular “minute” is identical to English.']],
  ['fr|formats.durationMinutes.other', ['contextual_translation', 'French plural “minutes” is identical to English.']],
  ['fr|navigation.administration', ['contextual_translation', 'French “Administration” is identical to English.']],
  ['fr|navigation.documents', ['contextual_translation', 'French “Documents” is identical to English.']],
  ['fr|pages.ai.section', ['contextual_translation', 'French “Administration” is identical to English.']],
  ['fr|pages.documents.title', ['contextual_translation', 'French “Documents” is identical to English.']],
  ['fr|pages.organization.section', ['contextual_translation', 'French “Administration” is identical to English.']],
  ['fr|pages.security.section', ['contextual_translation', 'French “Administration” is identical to English.']],
  ['fr|ask.assistant', ['contextual_translation', 'French “Assistant” is identical to English.']],
  ['fr|ask.conversationLabel', ['contextual_translation', 'French “Conversation” is identical to English.']],
  ['fr|ask.message', ['contextual_translation', 'French “Message” is identical to English.']],
  ['fr|ask.sources', ['contextual_translation', 'French “Sources” is identical to English.']],
  ['fr|ask.sourceTitle', ['contextual_translation', 'French “Source” is identical to English.']],
]);
const preservedCounts = { proper_name: 0, acronym: 0, international_technical_term: 0, contextual_translation: 0 };
const pendingTranslations = [];
const previewCoverage = [];
for (const locale of registryCodes.filter((candidate) => candidate !== 'en')) {
  const definition = definitionsByCode.get(locale);
  if (definition?.status === 'preview') {
    const translated = analyses[locale].leaves.size;
    previewCoverage.push(`${locale}=${translated}/${reference.size}`);
    continue;
  }
  const englishFillers = [];
  for (const [key, englishValue] of reference) {
    if (analyses[locale].leaves.get(key) !== englishValue) continue;
    const exception = intentionalEnglish.get(`${locale}|${key}`) ?? intentionalEnglish.get(`*|${key}`);
    if (!exception) englishFillers.push(key);
    else preservedCounts[exception[0]] += 1;
  }
  if (englishFillers.length) {
    pendingTranslations.push(`${locale}: ${englishFillers.length} values still duplicate English (${englishFillers.slice(0, 8).join(', ')}${englishFillers.length > 8 ? ', …' : ''})`);
  }
}

if (pendingTranslations.length) {
  throw new Error(`Catalog structure, plural families, locale registries and ${baselineKeys.size} legacy hash keys are valid.\nTranslation coverage remains incomplete:\n${pendingTranslations.join('\n')}`);
}

process.stdout.write(`Validated ${registryCodes.length} locale catalogs with ${reference.size} leaf messages and ${baselineKeys.size} frozen legacy hash keys. `
  + `Legitimate English-equivalent values: ${Object.entries(preservedCounts).map(([category, count]) => `${category}=${count}`).join(', ')}. `
  + `Preview source coverage: ${previewCoverage.join(', ')}.\n`);
