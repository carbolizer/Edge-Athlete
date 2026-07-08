const routes = [
  { label: "Wall", path: "/" },
  { label: "Coach", path: "/coach" },
  { label: "Rack Detail", path: "/rack-detail" },
  { label: "Athlete", path: "/athlete" },
  { label: "Admin", path: "/admin-setup" },
  { label: "Rack Demo", path: "/rack-demo" },
];

function RouteLauncher() {
  const currentPath = window.location.pathname;

  return (
    <nav className="route-launcher" aria-label="Preview routes">
      <span>Preview</span>
      {routes.map((route) => (
        <a className={currentPath === route.path ? "active" : ""} href={route.path} key={route.path}>
          {route.label}
        </a>
      ))}
    </nav>
  );
}

export default RouteLauncher;
