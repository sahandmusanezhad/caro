/* Listings a person keeps, in their own browser and nowhere else.
 *
 * No account and no server: the ids sit in localStorage under one key, and
 * nothing here sends them anywhere. Every read and write is guarded, because
 * storage can be off (a private window, a blocked site, a full quota) and a
 * page that throws for that would be a page broken by a convenience. A reader
 * that finds something it did not write starts again from nothing. */

const KEY = 'caro.saved.v1';
const MAX = 200;
const EVENT = 'caro-saved';

function read(): string[] {
  try {
    const raw = window.localStorage.getItem(KEY);
    const got = raw ? JSON.parse(raw) : [];
    return Array.isArray(got) ? got.filter((x) => typeof x === 'string').slice(0, MAX) : [];
  } catch {
    return [];
  }
}

function write(ids: string[]): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(ids.slice(0, MAX)));
    window.dispatchEvent(new Event(EVENT));
  } catch {
    /* storage is off; the page goes on without it */
  }
}

export function savedIds(): string[] {
  return read();
}

export function isSaved(id: string): boolean {
  return read().includes(id);
}

/** Saves or unsaves `id`; returns whether it is saved now. */
export function toggleSaved(id: string): boolean {
  const ids = read();
  const at = ids.indexOf(id);
  if (at >= 0) {
    ids.splice(at, 1);
    write(ids);
    return false;
  }
  write([id, ...ids]);
  return true;
}

export function onSavedChange(fn: () => void): () => void {
  window.addEventListener(EVENT, fn);
  window.addEventListener('storage', fn);
  return () => {
    window.removeEventListener(EVENT, fn);
    window.removeEventListener('storage', fn);
  };
}
