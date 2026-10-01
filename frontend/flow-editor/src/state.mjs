export function putOperation(operations, operation) {
  const same = item => ['value','position','label','bind','config_json'].includes(operation.op) && item.op === operation.op && item.node === operation.node && JSON.stringify(item.path ?? []) === JSON.stringify(operation.path ?? []) && (item.target ?? '') === (operation.target ?? '');
  return [...operations.filter(item => !same(item)), operation];
}

export function projectedValue(field, operations, node) {
  return operations.findLast(item => item.node === node && item.op === 'value' && JSON.stringify(item.path) === JSON.stringify(field.path))?.value ?? field.value;
}

export function inputValue(kind, text) {
  // An empty numeric input is invalid, never silently coerced to zero.
  if (!['number', 'integer'].includes(kind) || text.trim() === '') return text;
  const number = Number(text);
  return Number.isFinite(number) ? number : text;
}
