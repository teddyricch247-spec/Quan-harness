export function fillTemplate(template, vars) {
  return template.replace(/{{\s*([A-Z_]+)\s*}}/g, (match, key) => {
    const value = vars[key];
    return value === undefined || value === null || value === '' ? '(none yet)' : String(value);
  });
}
