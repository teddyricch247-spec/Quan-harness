function describe(action) {
  const { name, arguments: args } = action;
  switch (name) {
    case 'github_list_tree':
      return `listed files${args.branch ? ` (${args.branch})` : ''}`;
    case 'github_read_file':
      return `read ${args.path}`;
    case 'github_write_file':
      return `wrote ${args.path}`;
    case 'github_delete_file':
      return `deleted ${args.path}`;
    case 'github_create_repo':
      return `created repo ${args.name}`;
    case 'vercel_create_project':
      return `linked Vercel project ${args.name}`;
    case 'tavily_search':
      return `searched "${args.query}"`;
    case 'vercel_deployment_status':
      return 'checked deployment status';
    case 'finish_task':
      return 'finished';
    default:
      return name;
  }
}

export default function ToolActionList({ actions }) {
  if (!actions.length) return null;
  return (
    <ul className="tool-actions">
      {actions.map((action, i) => (
        <li key={i}>→ {describe(action)}</li>
      ))}
    </ul>
  );
}
