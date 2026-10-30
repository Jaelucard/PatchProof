import { describe, expect, it } from 'vitest';
import { diffLines } from '../diff';

describe('readable prompt diff', () => {
  it('preserves both prompts exactly, including empty lines', () => {
    const before = 'Extract intent.\n\nInfer the remedy.\nReturn JSON.';
    const after = 'Extract intent.\n\nUse null for uncertainty.\nReturn JSON.';
    const lines = diffLines(before, after);
    expect(lines.filter(line => line.kind !== 'added').map(line => line.text).join('\n')).toBe(before);
    expect(lines.filter(line => line.kind !== 'removed').map(line => line.text).join('\n')).toBe(after);
    expect(lines.filter(line => line.kind === 'removed').map(line => line.text)).toEqual(['Infer the remedy.']);
    expect(lines.filter(line => line.kind === 'added').map(line => line.text)).toEqual(['Use null for uncertainty.']);
  });
  it('shows only additions for appended repair instructions', () => {
    expect(diffLines('a\nb', 'a\nb\nc')).toEqual([{ kind: 'same', text: 'a' }, { kind: 'same', text: 'b' }, { kind: 'added', text: 'c' }]);
  });
  it('does not label identical prompts as changed', () => {
    expect(diffLines('keep\n\n', 'keep\n\n').every(line => line.kind === 'same')).toBe(true);
  });
});
