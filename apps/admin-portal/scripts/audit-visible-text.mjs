import { createRequire } from 'node:module';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const ignored = new Set(['node_modules', '.next', 'i18n']);
const visibleAttributes = new Set(['alt', 'aria-description', 'aria-label', 'placeholder', 'title']);
const visibleProperties = new Set([
  'description', 'emptyMessage', 'errorMessage', 'help', 'label', 'loadingMessage',
  'name', 'subtitle', 'title', 'tooltip',
]);
const visibleComponentProperties = new Set(['description', 'emptyMessage', 'help', 'label', 'subtitle', 'title', 'value']);
const protectedFiles = new Map();
const staticMetadata = new Set(['app/layout.tsx:Industrial AI Platform', 'app/layout.tsx:Admin Portal']);
const persistedTechnicalMetadata = new Set(['components/documents/DocumentBuilder.tsx:Configured through Admin Portal.']);
const technicalValue = /^(?:[A-Z0-9][A-Z0-9+./_-]*|[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+)+|https?:\/\/\S+|\/\S+)$/;
const rawI18nKey = /^(?:navigation|shell|language|copy)\.[A-Za-z0-9_.-]+$/;
const presentationName = /(?:description|emptyMessage|error|help|label|loadingMessage|message|notice|placeholder|statusMessage|subtitle|title|tooltip)$/i;
const referenceCatalog = JSON.parse(readFileSync(resolve(root, 'i18n', 'en.json'), 'utf8'));
const files = [];

function catalogValue(key) {
  let current = referenceCatalog;
  for (const segment of key.split('.')) {
    if (!current || typeof current !== 'object' || !(segment in current)) return undefined;
    current = current[segment];
  }
  return current;
}

function literalArgument(call) {
  const argument = call.arguments[0];
  return argument && ts.isStringLiteralLike(argument) ? argument : null;
}

function isStateVariableName(call) {
  const declaration = call.parent;
  if (!ts.isVariableDeclaration(declaration) || !ts.isArrayBindingPattern(declaration.name)) return null;
  const first = declaration.name.elements[0];
  return first && ts.isBindingElement(first) && ts.isIdentifier(first.name) ? first.name.text : null;
}

function visit(directory) {
  for (const name of readdirSync(directory)) {
    if (ignored.has(name)) continue;
    const path = resolve(directory, name);
    if (statSync(path).isDirectory()) visit(path);
    else if (/\.(tsx|ts)$/.test(name)) files.push(path);
  }
}

function normalize(value) {
  return value.replace(/\s+/g, ' ').trim();
}

function hasNaturalLanguage(value) {
  return /\p{L}{2}/u.test(value) && !technicalValue.test(value);
}

function propertyName(node) {
  if (!node) return null;
  if (ts.isIdentifier(node) || ts.isStringLiteral(node)) return node.text;
  return null;
}

function isVisibleJsxAttribute(attribute) {
  if (visibleAttributes.has(attribute.name.text)) return true;
  const element = attribute.parent?.parent;
  const tagName = element?.tagName?.getText?.() ?? '';
  return /^[A-Z]/.test(tagName) && visibleComponentProperties.has(attribute.name.text);
}

function categoryFor(file, value) {
  const protectedCategory = protectedFiles.get(file);
  if (protectedCategory) return protectedCategory;
  if (staticMetadata.has(`${file}:${value}`)) return 'static_bootstrap_metadata';
  if (persistedTechnicalMetadata.has(`${file}:${value}`)) return 'persisted_technical_metadata';
  if (!hasNaturalLanguage(value)) return 'technical_content';
  return 'visible_text';
}

function reasonFor(category, kind) {
  if (kind === 'nested_translation_call') return 'Translation functions must receive a catalog key, not the translated result of another translation call.';
  if (kind === 'missing_i18n_key') return 'The referenced translation key does not exist in the authoritative English catalog.';
  if (kind === 'raw_i18n_catalog_value') return 'The referenced catalog message resolves to another raw i18n key instead of user-facing copy.';
  if (kind.startsWith('raw_i18n_key')) return 'An internal i18n key is exposed directly as visible or accessible text.';
  if (category === 'protected_product_acceptance') return 'Product Acceptance is explicitly outside the authorized i18n scope.';
  if (category === 'static_bootstrap_metadata') return 'Server bootstrap metadata is emitted before the client-only persisted locale is available.';
  if (category === 'persisted_technical_metadata') return 'This value is persisted as technical API metadata and is not rendered as interface copy.';
  if (category === 'technical_content') {
    if (kind.includes(':columns')) return 'Stable backend field identifier; the table maps it to a localized header at render time.';
    if (kind.includes(':className') || kind.includes(':data-') || kind.includes(':key') || kind.includes(':aria-current')) return 'React, CSS or test-control token; not user-facing copy.';
    if (kind.includes(':value')) return 'Stable technical value passed through a controlled presentation component.';
    return 'Product version or protocol token that must remain unchanged.';
  }
  return 'Product-controlled visible copy must use a catalog key.';
}

visit(resolve(root, 'app'));
visit(resolve(root, 'components'));

const findings = [];
const seen = new Set();

for (const absolutePath of files.sort()) {
  const file = relative(root, absolutePath);
  const source = readFileSync(absolutePath, 'utf8');
  const sourceFile = ts.createSourceFile(absolutePath, source, ts.ScriptTarget.Latest, true,
    absolutePath.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);

  function record(node, kind, rawValue, forcedCategory) {
    const value = normalize(rawValue);
    if (!value || !/\p{L}/u.test(value)) return;
    const position = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
    const key = `${file}:${position.line + 1}:${position.character + 1}:${kind}:${value}`;
    if (seen.has(key)) return;
    seen.add(key);
    const category = forcedCategory ?? categoryFor(file, value);
    findings.push({
      file,
      line: position.line + 1,
      column: position.character + 1,
      kind,
      category,
      reason: reasonFor(category, kind),
      value,
    });
  }

  function recordPresentationStrings(node, kind) {
    if (ts.isStringLiteralLike(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      record(node, rawI18nKey.test(node.text) ? `raw_i18n_key:${kind}` : kind, node.text, rawI18nKey.test(node.text) ? 'visible_text' : undefined);
      return;
    }
    if (ts.isCallExpression(node) && node.expression.getText(sourceFile) === 't') return;
    ts.forEachChild(node, (child) => recordPresentationStrings(child, kind));
  }

  function inspectTranslationReference(call) {
    const argument = call.arguments[0];
    if (argument && ts.isCallExpression(argument) && argument.expression.getText(sourceFile) === 't') {
      record(call, 'nested_translation_call', call.getText(sourceFile), 'visible_text');
      return;
    }
    const literal = literalArgument(call);
    if (!literal) return;
    const value = catalogValue(literal.text);
    if (value === undefined) record(literal, 'missing_i18n_key', literal.text, 'visible_text');
    else if (typeof value === 'string' && rawI18nKey.test(value)) {
      record(literal, 'raw_i18n_catalog_value', `${literal.text} -> ${value}`, 'visible_text');
    }
  }

  function walk(node) {
    if (ts.isJsxText(node)) {
      const value = normalize(node.text);
      record(node, rawI18nKey.test(value) ? 'raw_i18n_key:jsx_text' : 'jsx_text', node.text, rawI18nKey.test(value) ? 'visible_text' : undefined);
    } else if (ts.isJsxAttribute(node) && node.name.text === 'id'
      && node.parent?.parent?.tagName?.getText?.() === 'LocalizedText'
      && node.initializer && ts.isStringLiteral(node.initializer)) {
      const value = catalogValue(node.initializer.text);
      if (value === undefined) record(node.initializer, 'missing_i18n_key', node.initializer.text, 'visible_text');
      else if (typeof value === 'string' && rawI18nKey.test(value)) {
        record(node.initializer, 'raw_i18n_catalog_value', `${node.initializer.text} -> ${value}`, 'visible_text');
      }
    } else if (ts.isJsxAttribute(node) && node.initializer && ts.isStringLiteral(node.initializer)
      && isVisibleJsxAttribute(node)) {
      record(node, rawI18nKey.test(node.initializer.text) ? `raw_i18n_key:jsx_attribute:${node.name.text}` : `jsx_attribute:${node.name.text}`,
        node.initializer.text, rawI18nKey.test(node.initializer.text) ? 'visible_text' : undefined);
    } else if (ts.isJsxAttribute(node) && node.initializer && ts.isJsxExpression(node.initializer)
      && node.initializer.expression && ts.isStringLiteralLike(node.initializer.expression)
      && isVisibleJsxAttribute(node)) {
      record(node.initializer.expression,
        rawI18nKey.test(node.initializer.expression.text) ? `raw_i18n_key:jsx_attribute:${node.name.text}` : `jsx_attribute:${node.name.text}`,
        node.initializer.expression.text, rawI18nKey.test(node.initializer.expression.text) ? 'visible_text' : undefined);
    } else if (ts.isPropertyAssignment(node) && ts.isStringLiteralLike(node.initializer)
      && visibleProperties.has(propertyName(node.name))) {
      record(node.initializer,
        rawI18nKey.test(node.initializer.text) ? `raw_i18n_key:visible_property:${propertyName(node.name)}` : `visible_property:${propertyName(node.name)}`,
        node.initializer.text, rawI18nKey.test(node.initializer.text) ? 'visible_text' : undefined);
    } else if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)
      && presentationName.test(node.name.text) && node.initializer) {
      recordPresentationStrings(node.initializer, `presentation_variable:${node.name.text}`);
    } else if (ts.isCallExpression(node)) {
      const callee = node.expression.getText(sourceFile);
      if (callee === 't') {
        inspectTranslationReference(node);
      } else if (callee === 'useState') {
        const stateName = isStateVariableName(node);
        const argument = node.arguments[0];
        if (stateName && presentationName.test(stateName) && argument) {
          recordPresentationStrings(argument, `state_initializer:${stateName}`);
        }
      } else if (/^set[A-Za-z0-9_]*(?:Description|EmptyMessage|Error|Help|Label|LoadingMessage|Message|Notice|Placeholder|StatusMessage|Subtitle|Title|Tooltip)$/.test(callee)
        || callee === 'window.confirm') {
        const argument = node.arguments[0];
        if (argument) recordPresentationStrings(argument, `visible_call:${callee}`);
      }
    } else if (ts.isStringLiteralLike(node)) {
      let current = node.parent;
      let visibleExpression = false;
      let excluded = false;
      while (current && !ts.isSourceFile(current)) {
        if (ts.isCallExpression(current)) {
          const callee = current.expression.getText(sourceFile);
          if (callee === 't' || callee === 'String' || callee === 'Boolean') excluded = true;
          else if (!/^(?:asText|productLabel|localizedProductLabel)$/.test(callee)) excluded = true;
          break;
        }
        if (ts.isBinaryExpression(current) && current.operatorToken.kind !== ts.SyntaxKind.QuestionQuestionToken
          && current.operatorToken.kind !== ts.SyntaxKind.PlusToken) {
          excluded = true;
          break;
        }
        if (ts.isJsxAttribute(current)) {
          excluded = true;
          break;
        }
        if (ts.isJsxExpression(current)) {
          if (ts.isJsxAttribute(current.parent) && !isVisibleJsxAttribute(current.parent)) {
            record(node, `technical_jsx_attribute:${current.parent.name.text}`, node.text, 'technical_content');
            excluded = true;
          } else {
            visibleExpression = true;
          }
          break;
        }
        current = current.parent;
      }
      if (visibleExpression && !excluded) {
        record(node, rawI18nKey.test(node.text) ? 'raw_i18n_key:jsx_expression_fallback' : 'jsx_expression_fallback',
          node.text, rawI18nKey.test(node.text) ? 'visible_text' : undefined);
      }
    }
    ts.forEachChild(node, walk);
  }

  walk(sourceFile);
}

const counts = findings.reduce((result, finding) => {
  result[finding.category] = (result[finding.category] ?? 0) + 1;
  return result;
}, {});

for (const finding of findings) {
  process.stdout.write(`${finding.file}:${finding.line}:${finding.column} [${finding.category}/${finding.kind}] ${finding.value} — ${finding.reason}\n`);
}
process.stdout.write(`Summary: ${findings.length} findings; ${Object.entries(counts).map(([key, value]) => `${key}=${value}`).join(', ')}\n`);
process.exitCode = counts.visible_text ? 1 : 0;
