export interface DiffLine { kind: 'same' | 'removed' | 'added'; text: string }
// Keep long user-provided prompts bounded; prefix/suffix still shows all content.
export function diffLines(before: string, after: string): DiffLine[] {
  const a = before.split('\n'); const b = after.split('\n');
  let start = 0; let end = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  while (end < a.length - start && end < b.length - start && a[a.length - 1 - end] === b[b.length - 1 - end]) end++;
  return [
    ...a.slice(0, start).map(text => ({ kind: 'same' as const, text })),
    ...a.slice(start, a.length - end).map(text => ({ kind: 'removed' as const, text })),
    ...b.slice(start, b.length - end).map(text => ({ kind: 'added' as const, text })),
    ...a.slice(a.length - end).map(text => ({ kind: 'same' as const, text })),
  ];
}
