// ?host= and ?incident= must coexist on the overview (operator decision 2, 260928-l4h): a host
// pane and a highlighted incident can both be open at once, so every link into either query
// param is built from the CURRENT search string rather than a fresh "/?x=" literal -- otherwise
// opening one would silently drop the other.

export function withSearchParam(search: string, key: string, value: string | null): string {
  const params = new URLSearchParams(search);
  if (value === null) {
    params.delete(key);
  } else {
    params.set(key, value);
  }
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

export function hostHref(search: string, id: string): string {
  return withSearchParam(search, "host", id);
}

export function incidentHref(search: string, id: string): string {
  return withSearchParam(search, "incident", id);
}
