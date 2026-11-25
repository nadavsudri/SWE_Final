// One authored icon set: 20px grid, 1.6 stroke, square caps to match the ruled-form world.
const P: Record<string, string> = {
  rect: '<rect x="3.5" y="5" width="13" height="10"/>',
  poly: '<path d="M4 7.5 9 3.5l7 3-1.5 9-9 1z"/><circle cx="4" cy="7.5" r="1.2" fill="currentColor"/><circle cx="16" cy="6.5" r="1.2" fill="currentColor"/>',
  edit: '<path d="M4 16 5 12l8-8 3 3-8 8z"/><path d="M11.5 5.5l3 3"/>',
  trash: '<path d="M4 6h12M8 6V4h4v2M6 6l1 10h6l1-10"/>',
  plus: '<path d="M10 4v12M4 10h12"/>',
  minus: '<path d="M4 10h12"/>',
  fit: '<path d="M4 8V4h4M12 4h4v4M16 12v4h-4M8 16H4v-4"/>',
  chevron: '<path d="M6 8l4 4 4-4"/>',
  check: '<path d="M4.5 10.5 8 14l7.5-8"/>',
  alert: '<path d="M10 3 2.5 16.5h15z"/><path d="M10 8v4M10 14.2v.3"/>',
  info: '<circle cx="10" cy="10" r="7"/><path d="M10 9v5M10 6.2v.3"/>',
  upload: '<path d="M10 13V4M6.5 7.5 10 4l3.5 3.5M4 13v3h12v-3"/>',
  x: '<path d="M5 5l10 10M15 5 5 15"/>',
  copy: '<rect x="7" y="7" width="9" height="9"/><path d="M4 13V4h9"/>',
  key: '<circle cx="7" cy="10" r="3"/><path d="M10 10h7M14 10v3M16.5 10v2"/>',
  nokey: '<circle cx="7" cy="10" r="3"/><path d="M10 10h7M14 10v3M3 3l14 14"/>',
  clock: '<circle cx="10" cy="10" r="7"/><path d="M10 6v4l3 2"/>',
  retry: '<path d="M15.5 8A6 6 0 1 0 16 12"/><path d="M16 4v4h-4"/>',
  pin: '<path d="M10 17v-5M6 12h8l-1.5-3V4h-5v5z"/>',
  queued: '<circle cx="10" cy="10" r="5"/>',
};

export function icon(name: string): string {
  return `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="square" stroke-linejoin="miter" aria-hidden="true" focusable="false">${P[name] ?? ""}</svg>`;
}

export function hydrateIcons(root: ParentNode = document): void {
  root.querySelectorAll<HTMLElement>(".ic[data-ic]").forEach((el) => {
    if (!el.firstChild) el.innerHTML = icon(el.dataset.ic!);
  });
}
